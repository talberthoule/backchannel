"""Suppress the same utterance being transcribed and saved twice (ALP-301).

On calls that capture both microphone and system audio, roughly 45 percent of
transcript entries are near-duplicates: the same speech surfaces twice, seconds
or milliseconds apart, under two different speaker identities, with the wording
drifting slightly because the two copies came from different segment boundaries
and were transcribed independently. Measured on session 343339c5: 462 duplicate
pairs out of 1189 entries, every one of them cross-speaker, and 401 of those
between two microphone-track identities rather than across tracks.

The cost is threefold. Every text agent reads the doubled transcript, so its
input is inflated for the whole call; diarization spends a speaker slot on the
twin, which is how a two-person call ends up presenting four participants; and
the transcript the operator reads and exports is half redundant.

This filter sits at the single point where a live segment becomes a saved
entry, ahead of speaker resolution, so a suppressed twin never creates the
phantom speaker either.

Two deliberate limits. It keeps the first arrival, because there is no general
way to tell which of two near-identical transcriptions is the better one, and
first-wins is at least deterministic. And it only judges utterances of a few
words or more: short backchannels ("yeah", "right, okay") legitimately repeat
across speakers, and suppressing those would delete real conversation.
"""

import logging
import re
import time
from collections import deque

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall((text or "").lower()))


def _overlap(left: frozenset[str], right: frozenset[str]) -> float:
    """Containment rather than Jaccard.

    The twin is often a partial re-hearing - "the pure play cloud providers on
    the left" against "the peer-to-peer cloud providers on the left." Jaccard
    punishes the length difference and misses those; dividing by the shorter
    side asks the question that matters, which is whether one utterance is
    substantially contained in the other.
    """
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


class LiveTranscriptDeduper:
    """Rolling window of recent utterances, used to reject re-emissions."""

    def __init__(
        self,
        window_seconds: float,
        similarity: float,
        min_words: int,
        clock=time.monotonic,
    ):
        self._window_seconds = window_seconds
        self._similarity = similarity
        self._min_words = min_words
        self._clock = clock
        self._recent: deque[tuple[float, frozenset[str]]] = deque()

    def admit(self, text: str) -> bool:
        """True when this utterance should be saved.

        Recording happens here rather than in a separate call so a caller
        cannot admit an entry and forget to remember it, which would let the
        third and fourth copies through.
        """
        now = self._clock()
        cutoff = now - self._window_seconds
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()

        words = _words(text)
        if len(words) < self._min_words:
            # Too short to distinguish a duplicate from a genuine echo of
            # agreement. Not remembered either: a stream of "yeah"s would
            # otherwise fill the window and mask a real duplicate behind it.
            return True

        for _, previous in self._recent:
            if _overlap(words, previous) >= self._similarity:
                return False

        self._recent.append((now, words))
        return True


class _AlwaysAdmit:
    def admit(self, text: str) -> bool:  # noqa: ARG002 - interface parity
        return True


def build_transcript_deduper(settings) -> "LiveTranscriptDeduper | _AlwaysAdmit":
    """Deduper for one call, or a pass-through when disabled."""
    if not getattr(settings, "TRANSCRIPT_DEDUP_ENABLED", True):
        return _AlwaysAdmit()
    return LiveTranscriptDeduper(
        window_seconds=settings.TRANSCRIPT_DEDUP_WINDOW_SECONDS,
        similarity=settings.TRANSCRIPT_DEDUP_SIMILARITY,
        min_words=settings.TRANSCRIPT_DEDUP_MIN_WORDS,
    )
