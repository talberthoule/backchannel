"""Pattern and roster recognizers for the PII Shield.

Each recognizer returns ``Span`` objects over the input text. Overlaps are
resolved later by ``resolve_spans``: the longer span wins, and on equal length
the category with the higher priority (a card number beats a phone number
that happens to share digits).

These are deliberately conservative in one direction. A false positive costs
a little analysis quality (the model sees ``[ORG_2]`` where it could have seen
a product name); a false negative sends personal data to a model, which is
the failure the shield exists to prevent. The balance is struck per
recognizer below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PERSON = "PERSON"
ORG = "ORG"
LOCATION = "LOCATION"
EMAIL = "EMAIL"
PHONE = "PHONE"
SSN = "SSN"
CARD = "CARD"
IP = "IP"
ADDRESS = "ADDRESS"

# Every category the shield knows, in the order the settings card lists them.
CATEGORIES: tuple[str, ...] = (PERSON, ORG, LOCATION, EMAIL, PHONE, SSN, CARD, IP, ADDRESS)

# Higher wins when two spans of equal length overlap.
_PRIORITY = {
    CARD: 9, SSN: 8, EMAIL: 7, PHONE: 6, IP: 5, ADDRESS: 4, PERSON: 3, ORG: 2, LOCATION: 1,
}

CATEGORY_LABELS = {
    PERSON: "People's names",
    ORG: "Organizations and companies",
    LOCATION: "Places",
    EMAIL: "Email addresses",
    PHONE: "Phone numbers",
    SSN: "National identifiers (SSN)",
    CARD: "Payment card numbers",
    IP: "IP addresses",
    ADDRESS: "Street addresses",
}


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    category: str
    text: str
    score: float
    source: str
    # The value the token stands for when it differs from the matched text:
    # a first name matched from the roster maps to the person's full name.
    canonical: str | None = None

    @property
    def value(self) -> str:
        return self.canonical or self.text

    @property
    def length(self) -> int:
        return self.end - self.start


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# North American numbers with the usual separators, plus international
# numbers written with a leading +. A bare run of digits is never a phone:
# years, prices and quantities are far more common in a meeting.
_PHONE = re.compile(
    r"(?<![\w$.-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}(?![\w-])"
    r"|(?<![\w$])\+\d{1,3}[\s.-]?(?:\(\d{1,4}\)[\s.-]?)?(?:\d[\s.-]?){6,11}\d(?![\w-])"
)

_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")

_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")

_IPV4 = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"
)

_STREET_SUFFIX = (
    "street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|court|ct|way|place|pl|"
    "circle|cir|terrace|ter|parkway|pkwy|highway|hwy|trail|trl|square|sq|plaza|loop"
)
_ADDRESS = re.compile(
    rf"\b\d{{1,6}}\s+(?:[A-Z][A-Za-z'.-]*\s+){{1,4}}(?:{_STREET_SUFFIX})\.?"
    rf"(?:,?\s+(?:suite|ste|apt|apartment|unit|floor|fl|#)\s*\.?\s*[\w-]+)?\b",
    re.IGNORECASE,
)

# Someone naming themselves or a colleague. Speech transcripts rarely carry
# honorifics, but introductions are frequent and reliable.
_INTRODUCTION = re.compile(
    r"\b(?:my name is|my name's|this is|I am|I'm|speaking with|joined by|here with|introduce)\s+"
    r"((?:[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?)(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){0,2})\b"
)
# Capitalized words that follow an introduction cue but are not names.
_NOT_NAMES = frozenset({
    "The", "A", "An", "Not", "Just", "Going", "Here", "There", "So", "Also",
    "Really", "Very", "Still", "Now", "Today", "Back", "Happy", "Sorry",
    "Glad", "Good", "Great", "Okay", "Ok", "Yes", "No", "Sure", "Thanks",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
})


def _luhn_ok(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        value = ord(char) - 48
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _card_ok(match_text: str) -> bool:
    digits = re.sub(r"\D", "", match_text)
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


def _phone_ok(match_text: str) -> bool:
    return 10 <= len(re.sub(r"\D", "", match_text)) <= 15


# (category, pattern, score, accept) - accept() is the checksum or sanity
# test a bare match still has to pass.
_PATTERN_RECOGNIZERS: tuple[tuple[str, re.Pattern[str], float, "callable | None"], ...] = (
    (EMAIL, _EMAIL, 1.0, None),
    (SSN, _SSN, 0.95, None),
    (CARD, _CARD, 0.95, _card_ok),
    (PHONE, _PHONE, 0.85, _phone_ok),
    (IP, _IPV4, 0.8, None),
    (ADDRESS, _ADDRESS, 0.8, None),
)


def find_patterns(text: str, categories: set[str]) -> list[Span]:
    """Structured identifiers: pattern plus, where one exists, a checksum."""
    spans: list[Span] = []
    for category, pattern, score, accept in _PATTERN_RECOGNIZERS:
        if category not in categories:
            continue
        for m in pattern.finditer(text):
            if accept is None or accept(m.group()):
                spans.append(Span(m.start(), m.end(), category, m.group(), score, "pattern"))
    if PERSON in categories:
        spans.extend(_find_introductions(text))
    return spans


def _find_introductions(text: str) -> list[Span]:
    spans: list[Span] = []
    for m in _INTRODUCTION.finditer(text):
        name = m.group(1)
        if name.split()[0] not in _NOT_NAMES:
            spans.append(Span(m.start(1), m.end(1), PERSON, name, 0.7, "introduction"))
    return spans


@dataclass(frozen=True)
class RosterEntry:
    value: str
    category: str


_WORD_CHARS = r"A-Za-z0-9'À-ɏ"


def find_roster(text: str, roster: list[RosterEntry], categories: set[str]) -> list[Span]:
    """Known names and terms: the session's speakers and the protected-terms list.

    The full value matches case-insensitively as a whole word. For a person's
    multi-word name each part of three letters or more also matches on its own,
    but only with its original capitalization, so a speaker called Bill Brown
    is caught as "Bill" or "Brown" while "the bill" and "brown paper" pass.
    """
    spans: list[Span] = []
    for entry in roster:
        value = entry.value.strip()
        if not value or entry.category not in categories:
            continue
        pattern = re.compile(rf"(?<![{_WORD_CHARS}]){re.escape(value)}(?![{_WORD_CHARS}])", re.IGNORECASE)
        for m in pattern.finditer(text):
            spans.append(Span(m.start(), m.end(), entry.category, m.group(), 1.0, "roster"))
        if entry.category != PERSON:
            continue
        parts = [p for p in re.split(r"[\s,]+", value) if len(p) >= 3 and p[0].isupper()]
        if len(parts) < 2:
            continue
        for part in parts:
            part_pattern = re.compile(rf"(?<![{_WORD_CHARS}]){re.escape(part)}(?![{_WORD_CHARS}])")
            for m in part_pattern.finditer(text):
                spans.append(Span(m.start(), m.end(), PERSON, m.group(), 0.9, "roster", canonical=value))
    return spans


# At equal length the roster wins outright: it knows that "Brown" is Bill
# Brown and that "Cyberdyne" is a company, where the model only guesses a
# category. Patterns come next (an email is an email whatever a model says).
_SOURCE_RANK = {"roster": 4, "pattern": 3, "introduction": 2, "ner": 1}


def resolve_spans(spans: list[Span]) -> list[Span]:
    """Drop overlaps: longest first, then source, category priority, score."""
    ordered = sorted(
        spans,
        key=lambda s: (-s.length, -_SOURCE_RANK.get(s.source, 0), -_PRIORITY.get(s.category, 0), -s.score, s.start),
    )
    kept: list[Span] = []
    for span in ordered:
        if span.length <= 0:
            continue
        if any(span.start < other.end and other.start < span.end for other in kept):
            continue
        kept.append(span)
    return sorted(kept, key=lambda s: s.start)


def normalize_value(value: str, category: str) -> str:
    """The lookup form of a value: one token per distinct real-world identity.

    Emails and names fold case; numbers drop their separators so "555-0100"
    and "555 0100" share a token. The stored (revealed) value keeps the first
    spelling seen.
    """
    value = value.strip()
    if category in (PHONE, SSN, CARD):
        return re.sub(r"\D", "", value)
    if category in (EMAIL, PERSON, ORG, LOCATION, ADDRESS):
        return re.sub(r"\s+", " ", value).casefold()
    return value
