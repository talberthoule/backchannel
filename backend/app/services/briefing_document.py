"""The exported call briefing: one self-contained HTML file.

The old export was an honest typographic sheet - a stack of same-weight cards
with no answer at the top and no route to the evidence underneath. This is the
document the sheet was standing in for (ALP-370).

Three decisions shape it.

*One page, one answer first.* A masthead band carries the meeting's identity
and four figures that say what came out of it, then a standfirst says the same
thing in a sentence. Everything after that is detail a reader chooses to enter.

*Evidence stays one click away, never in the way.* Each captured insight keeps
the line that produced it, folded into a native ``<details>``; the whole
transcript sits at the end the same way. No script decides what a reader can
reach, so the file behaves identically in a browser, in an email client, and
on paper.

*One file, forever.* No fonts, scripts, images or stylesheets from anywhere.
System faces only - a serif for the display layer, the platform grotesque for
running text, a monospace for figures and labels. Both charts are hand-set
HTML bars in the single accent hue, direct-labelled: nothing to load, nothing
to execute, and no categorical palette to get wrong.

On the shield: this module only ever receives whatever text the caller loaded.
Under the PII Shield that text is tokenized, and the caller reveals the
rendered document as a whole afterwards, so every vault token has to survive
escaping intact - which it does, since a token carries no HTML-special
characters. Nothing here reads or resolves a vault value itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape

# --------------------------------------------------------------------------
# Palette and type
#
# Colors come from the app's own token spine (frontend/src/index.css): the
# slate ramp and the teal accent, so a forwarded briefing is recognizably the
# same product. Neutrals are the blue-biased slate rather than a pure grey,
# which is what lets teal sit on them without arguing.
#
# The display face is a serif drawn from what every machine already has. It is
# the one characterful choice in the file and it carries the masthead, the
# standfirst and the section titles; running text and data stay on the
# platform grotesque and a monospace, so the personality is in the pairing
# rather than in a download that would not survive the file being kept.
# --------------------------------------------------------------------------

_STYLE = """
:root {
  color-scheme: light;
  --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "SFMono-Regular", "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas, monospace;

  --ground: #e8eef0;
  --paper: #ffffff;
  --ink: #101c1f;
  --ink-2: #4a5c60;
  --ink-3: #7b8d92;
  --rule: #d8e2e4;
  --rule-soft: #edf2f3;
  --accent: #0f766e;
  --mark: #0d9488;
  --mark-soft: #9ed6ce;
  --wash: #eef6f5;
  --band: #0b1d20;
  --band-ink: #eaf4f2;
  --band-ink-2: #8bb0aa;
  --band-rule: #1d3a3c;
  --open: #96591a;
  --risk: #a3352b;
  --done: #0f766e;
  --measure: 64ch;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #070d0e;
    --paper: #121a1c;
    --ink: #e6eeef;
    --ink-2: #a0b2b5;
    --ink-3: #74868a;
    --rule: #243033;
    --rule-soft: #1a2325;
    --accent: #5eead4;
    --mark: #2dd4bf;
    --mark-soft: #1f4b48;
    --wash: #14262a;
    --band: #050b0c;
    --band-ink: #eaf4f2;
    --band-ink-2: #7ea6a0;
    --band-rule: #1a3234;
    --open: #e0a34a;
    --risk: #ef8177;
    --done: #5eead4;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #070d0e;
  --paper: #121a1c;
  --ink: #e6eeef;
  --ink-2: #a0b2b5;
  --ink-3: #74868a;
  --rule: #243033;
  --rule-soft: #1a2325;
  --accent: #5eead4;
  --mark: #2dd4bf;
  --mark-soft: #1f4b48;
  --wash: #14262a;
  --band: #050b0c;
  --band-ink: #eaf4f2;
  --band-ink-2: #7ea6a0;
  --band-rule: #1a3234;
  --open: #e0a34a;
  --risk: #ef8177;
  --done: #5eead4;
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  padding: 32px 20px 56px;
  background: var(--ground);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15.5px;
  line-height: 1.62;
  -webkit-font-smoothing: antialiased;
}
.doc {
  max-width: 62rem;
  margin: 0 auto;
  background: var(--paper);
  overflow: hidden;
  border: 1px solid var(--rule);
}

/* --- masthead: the one loud surface in the file ------------------------- */
.band { background: var(--band); color: var(--band-ink); padding: 40px 52px 0; }
.eyebrow {
  display: flex; align-items: center; gap: 10px; margin: 0;
  font-family: var(--mono); font-size: 10.5px; letter-spacing: .18em;
  text-transform: uppercase; color: var(--band-ink-2);
}
.eyebrow b { font-weight: 500; color: var(--mark); }
.band h1 {
  margin: 14px 0 0; font-family: var(--serif); font-weight: 400;
  font-size: clamp(30px, 5vw, 44px); line-height: 1.1; letter-spacing: -.012em;
  text-wrap: balance;
}
.dateline {
  margin: 12px 0 0; font-family: var(--mono); font-size: 12px;
  color: var(--band-ink-2);
}
.dateline span + span::before { content: " / "; color: var(--band-rule); }
.tally { display: flex; flex-wrap: wrap; margin: 32px -52px 0; border-top: 1px solid var(--band-rule); }
.tally > div {
  flex: 1 1 8rem; padding: 18px 52px 20px; border-right: 1px solid var(--band-rule);
}
.tally > div:first-child { padding-left: 52px; }
.tally > div:last-child { border-right: 0; }
.tally .n {
  font-family: var(--mono); font-size: 27px; line-height: 1;
  font-variant-numeric: tabular-nums; color: var(--band-ink);
}
.tally .n.hot { color: var(--mark); }
.tally .k {
  margin-top: 8px; font-family: var(--mono); font-size: 10px;
  letter-spacing: .13em; text-transform: uppercase; color: var(--band-ink-2);
}

/* --- body --------------------------------------------------------------- */
.body { padding: 44px 52px 40px; }
.lede {
  margin: 0; max-width: var(--measure);
  font-family: var(--serif); font-size: 21px; line-height: 1.5; color: var(--ink);
  text-wrap: pretty;
}
.lede em { font-style: normal; color: var(--accent); }
.standfirst-note {
  margin: 14px 0 0; max-width: var(--measure);
  font-family: var(--mono); font-size: 12px; color: var(--ink-3);
}

section { margin-top: 44px; }
section > h2 {
  display: flex; align-items: baseline; gap: 14px; margin: 0 0 4px;
  padding-bottom: 10px; border-bottom: 2px solid var(--ink);
  font-family: var(--serif); font-weight: 400; font-size: 23px; letter-spacing: -.008em;
}
section > h2 .n {
  margin-left: auto; font-family: var(--mono); font-size: 11.5px;
  letter-spacing: .1em; color: var(--ink-3); font-variant-numeric: tabular-nums;
}
.blurb { margin: 12px 0 0; max-width: var(--measure); color: var(--ink-2); font-size: 14.5px; }

/* records: hairline-separated runs, never cards */
.rec { display: grid; grid-template-columns: 2.4rem 1fr; gap: 0 16px; padding: 20px 0; border-bottom: 1px solid var(--rule-soft); }
.rec:last-child { border-bottom: 0; }
.rec > .i {
  padding-top: 3px; font-family: var(--mono); font-size: 12px;
  font-variant-numeric: tabular-nums; color: var(--mark);
}
.rec h3 { margin: 0; font-size: 16.5px; font-weight: 620; line-height: 1.4; letter-spacing: -.004em; text-wrap: pretty; }
.rec p { margin: 8px 0 0; max-width: var(--measure); }
.rec p.why { color: var(--ink-2); font-size: 14.5px; }
.tags { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 9px; font-family: var(--mono); font-size: 11.5px; color: var(--ink-3); }
.tag { display: inline-flex; align-items: center; gap: 6px; letter-spacing: .04em; }
.tag::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tag.plain::before { display: none; }
.tag.open { color: var(--open); }
.tag.risk { color: var(--risk); }
.tag.done { color: var(--done); }
.tag.flag { color: var(--mark); }

/* evidence: available, never in the way */
details.ev { margin-top: 12px; max-width: var(--measure); }
details.ev > summary {
  display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
  font-family: var(--mono); font-size: 11.5px; letter-spacing: .06em;
  text-transform: uppercase; color: var(--ink-3); list-style: none;
}
details.ev > summary::-webkit-details-marker { display: none; }
details.ev > summary::before { content: "+"; color: var(--mark); font-size: 13px; }
details.ev[open] > summary::before { content: "-"; }
details.ev > summary:hover { color: var(--accent); }
details.ev > summary:focus-visible { outline: 2px solid var(--mark); outline-offset: 3px; }
blockquote.ev {
  margin: 10px 0 0; padding: 12px 16px; background: var(--wash);
  border-left: 2px solid var(--mark); color: var(--ink-2); font-size: 14.5px;
}
blockquote.ev p { margin: 0; }

/* --- figures ------------------------------------------------------------ */
figure { margin: 0; }
.figs { display: grid; grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr)); gap: 36px; margin-top: 38px; }
figcaption {
  font-family: var(--mono); font-size: 10.5px; letter-spacing: .13em;
  text-transform: uppercase; color: var(--ink-3);
  padding-bottom: 9px; border-bottom: 1px solid var(--rule);
}
.bars { margin: 4px 0 0; }
.bars .row { display: grid; grid-template-columns: 8.5rem 1fr 4.4rem; align-items: center; gap: 12px; padding: 7px 0; }
.bars .lbl { font-size: 13.5px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bars .track { height: 9px; background: var(--rule-soft); }
.bars .fill { height: 100%; background: var(--mark); border-radius: 0 4px 4px 0; min-width: 2px; }
.bars .val { font-family: var(--mono); font-size: 12.5px; font-variant-numeric: tabular-nums; text-align: right; color: var(--ink); }
.bars .sub { display: block; font-family: var(--mono); font-size: 10.5px; color: var(--ink-3); }

/* --- lists and appendix ------------------------------------------------- */
ul.plain { margin: 12px 0 0; padding: 0; list-style: none; max-width: var(--measure); }
ul.plain li { padding: 9px 0; border-bottom: 1px solid var(--rule-soft); }
ul.plain li:last-child { border-bottom: 0; }
.empty { margin: 12px 0 0; color: var(--ink-3); font-style: italic; }
.note { margin: 12px 0 0; max-width: var(--measure); padding: 14px 18px; background: var(--wash); color: var(--ink-2); font-size: 14.5px; }

details.appendix { margin-top: 44px; border-top: 2px solid var(--ink); }
details.appendix > summary {
  display: flex; align-items: baseline; gap: 12px; padding: 14px 0 0; cursor: pointer;
  font-family: var(--serif); font-size: 23px; list-style: none;
}
details.appendix > summary::-webkit-details-marker { display: none; }
details.appendix > summary .n { margin-left: auto; font-family: var(--mono); font-size: 11.5px; letter-spacing: .1em; color: var(--ink-3); }
details.appendix > summary:focus-visible { outline: 2px solid var(--mark); outline-offset: 3px; }
.turns { margin-top: 18px; }
.turn { display: grid; grid-template-columns: 5.5rem 1fr; gap: 0 16px; padding: 5px 0; }
.turn .t { font-family: var(--mono); font-size: 11.5px; color: var(--ink-3); font-variant-numeric: tabular-nums; padding-top: 3px; }
.turn .s { font-size: 14.5px; }
.turn .who { font-weight: 620; color: var(--ink-2); }

.colophon {
  display: flex; flex-wrap: wrap; gap: 10px 28px; justify-content: space-between;
  margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--rule);
  font-family: var(--mono); font-size: 11px; letter-spacing: .05em; color: var(--ink-3);
}

@media (max-width: 700px) {
  body { padding: 0; }
  .doc { border: 0; }
  .band { padding: 30px 22px 0; }
  .tally { margin: 24px -22px 0; }
  .tally > div, .tally > div:first-child { padding: 14px 22px 16px; }
  .body { padding: 30px 22px 32px; }
  .rec { grid-template-columns: 1.8rem 1fr; gap: 0 10px; }
  .bars .row { grid-template-columns: 6.5rem 1fr 4rem; }
  .turn { grid-template-columns: 1fr; }
  .turn .t { padding: 0; }
}

@media print {
  body { padding: 0; background: #fff; color: #000; font-size: 10.5pt; }
  .doc { max-width: none; border: 0; }
  /* The band is the screen's boldest surface and the printer's worst idea. */
  .band { background: #fff; color: #000; padding: 0 0 0; border-bottom: 2px solid #000; }
  .eyebrow, .dateline, .tally .k { color: #444; }
  .eyebrow b { color: #000; }
  .tally { margin: 20px 0 16px; border-top: 1px solid #000; }
  .tally > div { padding: 10px 16px 10px 0; border-right: 1px solid #bbb; }
  .tally .n, .tally .n.hot { color: #000; }
  .body { padding: 22px 0 0; }
  details.ev, details.appendix { display: block; }
  details.ev > summary, details.appendix > summary { list-style: none; }
  details.ev[open] blockquote.ev { background: #fff; }
  section, .rec, .turn, figure { break-inside: avoid; }
  h1, h2, h3 { break-after: avoid; }
}

@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
"""


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


@dataclass
class BriefingData:
    """Everything the document draws, already loaded and already decided.

    The router owns the queries and the reveal rule; this holds the result so
    a renderer cannot reach past what the caller was willing to show.
    """

    session: object
    synthesis: object | None = None
    questions: list = field(default_factory=list)
    speakers: list = field(default_factory=list)
    transcript: list = field(default_factory=list)
    directives: list = field(default_factory=list)


_TYPE_LABELS = {
    "question": "Question",
    "observation": "Observation",
    "opportunity": "Opportunity",
    "action_item": "Action item",
    "objection": "Objection",
    "asked": "Asked live",
}

# The order a reader wants: commitments, then money, then resistance, then
# what is still unknown, then background. Not the order the agents produce in.
_TYPE_SECTIONS = [
    ("action_item", "Commitments"),
    ("opportunity", "Opportunities"),
    ("objection", "Objections raised"),
    ("question", "Still open"),
    ("observation", "On the record"),
]


def _label(item_type: str | None) -> str:
    slug = (item_type or "question").strip()
    return _TYPE_LABELS.get(slug, slug.replace("_", " ").capitalize())


def _text(value: object) -> str:
    return str(value or "").strip()


def _e(value: object) -> str:
    return escape(_text(value))


def _fmt(stamp) -> str:
    return stamp.strftime("%d %B %Y, %H:%M") if stamp else "Not recorded"


def _minutes(started, ended) -> int | None:
    if not started or not ended:
        return None
    return int(max(0, (ended - started).total_seconds()) // 60)


def _span(started, ended) -> str:
    minutes = _minutes(started, ended)
    if minutes is None:
        return ""
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def _speaker_label(speaker) -> str:
    display = _text(getattr(speaker, "display_name", ""))
    if display and getattr(speaker, "display_name_enabled", False):
        return display
    return _text(getattr(speaker, "name", "")) or "Unknown"


def _roster(speakers: list) -> dict[str, str]:
    return {str(s.id): _speaker_label(s) for s in speakers}


def _attributed(row, roster: dict[str, str]) -> str:
    raw = getattr(row, "speaker_id", None)
    return roster.get(str(raw), "") if raw else ""


def _section_items(items) -> list[dict]:
    return [
        item for item in (items or [])
        if isinstance(item, dict) and (_text(item.get("title")) or _text(item.get("summary")))
    ]


def synthesis_is_usable(synthesis) -> bool:
    """Whether a stored synthesis has enough in it to lead the document."""
    if synthesis is None or getattr(synthesis, "status", "") not in {"completed", "partial"}:
        return False
    sections = [
        getattr(synthesis, name, None)
        for name in (
            "top_outcomes",
            "client_objectives",
            "top_opportunities",
            "risks_blockers",
            "action_plan",
            "unresolved_discovery_questions",
        )
    ]
    return any(_section_items(section) for section in sections) or bool(getattr(synthesis, "clusters", None))


def section_labels(meeting_type: str) -> dict[str, str]:
    """Section names that fit the conversation that actually happened."""
    by_type = {
        "internal_enablement": ("Learning objectives", "Enablement opportunities", "Open learning questions"),
        "internal_checkin": ("Objectives and needs", "Support opportunities", "Open questions"),
        "vendor_partner": ("Vendor and program objectives", "Partner opportunities", "Open vendor questions"),
        "customer_delivery": ("Project objectives", "Delivery opportunities", "Open delivery questions"),
        "client_sales": ("Client objectives", "Top opportunities", "Unresolved discovery questions"),
    }
    objectives, opportunities, questions = by_type.get(
        meeting_type, ("Objectives", "Top opportunities", "Open questions")
    )
    return {"objectives": objectives, "opportunities": opportunities, "questions": questions}


# --------------------------------------------------------------------------
# Pieces
# --------------------------------------------------------------------------


def _tally(cells: list[tuple[str, object, bool]]) -> str:
    out = []
    for label, value, hot in cells:
        klass = "n hot" if hot else "n"
        out.append(f'<div><div class="{klass}">{_e(value)}</div><div class="k">{_e(label)}</div></div>')
    return f'<div class="tally">{"".join(out)}</div>'


def _masthead(data: BriefingData, kind: str, cells: list[tuple[str, object, bool]]) -> str:
    session = data.session
    started = getattr(session, "started_at", None)
    ended = getattr(session, "ended_at", None)
    dateline = [f"<span>{_e(_fmt(started))}</span>"]
    if span := _span(started, ended):
        dateline.append(f"<span>{_e(span)}</span>")
    count = len(data.speakers)
    dateline.append(f"<span>{count} participant{'s' if count != 1 else ''}</span>")
    return (
        '<header class="band">'
        f'<p class="eyebrow"><b>Backchannel</b> {_e(kind)}</p>'
        f"<h1>{_e(getattr(session, 'name', '')) or 'Session'}</h1>"
        f'<p class="dateline">{"".join(dateline)}</p>'
        f"{_tally(cells)}"
        "</header>"
    )


def _bars(rows: list[tuple[str, int, str]], caption: str) -> str:
    """A single-hue, direct-labelled magnitude chart.

    One series, so no legend and no categorical palette: the label names the
    row and the number at the end is the value, which is the pair a reader
    needs. The bar is the comparison; nothing is encoded in color alone.
    """
    top = max((value for _, value, _ in rows), default=0) or 1
    body = []
    for label, value, note in rows:
        width = max(2, round(value / top * 100))
        sub = f'<span class="sub">{_e(note)}</span>' if note else ""
        body.append(
            f'<div class="row"><div class="lbl" title="{_e(label)}">{_e(label)}</div>'
            f'<div class="track"><div class="fill" style="width:{width}%"></div></div>'
            f'<div class="val">{value}{sub}</div></div>'
        )
    return (
        f"<figure><figcaption>{_e(caption)}</figcaption>"
        f'<div class="bars">{"".join(body)}</div></figure>'
    )


def _figures(data: BriefingData) -> str:
    """Insight mix and who did the talking - both only when they say something.

    A mix chart of one row, or a participation chart for a single speaker, is
    a picture of nothing; those cases fall away rather than padding the page.
    """
    figures = []
    counts: dict[str, int] = {}
    for q in data.questions:
        slug = _text(getattr(q, "item_type", "")) or "question"
        counts[slug] = counts.get(slug, 0) + 1
    if len(counts) > 1:
        ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        figures.append(_bars([(_label(slug), n, "") for slug, n in ordered], "What was captured"))

    if len(data.speakers) > 1 and data.transcript:
        roster = _roster(data.speakers)
        turns: dict[str, int] = {}
        for entry in data.transcript:
            if key := _attributed(entry, roster):
                turns[key] = turns.get(key, 0) + 1
        attributed: dict[str, int] = {}
        for q in data.questions:
            if key := _attributed(q, roster):
                attributed[key] = attributed.get(key, 0) + 1
        if turns:
            rows = sorted(turns.items(), key=lambda pair: (-pair[1], pair[0]))
            figures.append(
                _bars(
                    [(name, n, f"{attributed.get(name, 0)} cited") for name, n in rows],
                    "Turns taken, and insights drawn from them",
                )
            )
    if not figures:
        return ""
    return f'<div class="figs">{"".join(figures)}</div>'


def _tags(bits: list[tuple[str, str]]) -> str:
    if not bits:
        return ""
    spans = "".join(f'<span class="tag {klass}">{_e(text)}</span>' for klass, text in bits)
    return f'<div class="tags">{spans}</div>'


def _evidence(quote: str, label: str = "What was said") -> str:
    if not quote:
        return ""
    return (
        f'<details class="ev"><summary>{_e(label)}</summary>'
        f'<blockquote class="ev"><p>{_e(quote)}</p></blockquote></details>'
    )


def _record(index: int, title: str, tags: str, body: str, why: str, evidence: str) -> str:
    """One run in a section. An empty title is legal and deliberate: the
    standfirst above may already be this item's heading, and repeating it
    reads as a bug rather than as emphasis."""
    heading = f"<h3>{_e(title)}</h3>" if title else ""
    return (
        f'<div class="rec"><div class="i">{index:02d}</div><div>'
        f"{heading}{tags}"
        + (f"<p>{_e(body)}</p>" if body else "")
        + (f'<p class="why">{_e(why)}</p>' if why else "")
        + evidence
        + "</div></div>"
    )


def _section(title: str, inner: str, count: int | None = None, empty: str = "Nothing captured.") -> str:
    tally = f'<span class="n">{count}</span>' if count is not None else ""
    body = inner or f'<p class="empty">{_e(empty)}</p>'
    return f"<section><h2>{_e(title)}{tally}</h2>{body}</section>"


def _synthesis_section(title: str, items, *, heading_in_standfirst: bool = False) -> str:
    """A synthesis section.

    ``heading_in_standfirst`` drops the first item's heading, for the one
    section whose leading item the document already opened with.
    """
    valid = _section_items(items)
    records = []
    for index, item in enumerate(valid, 1):
        heading = _text(item.get("title")) or _text(item.get("summary"))
        summary = _text(item.get("summary")) if _text(item.get("title")) else ""
        if index == 1 and heading_in_standfirst:
            summary = summary or heading
            heading = ""
        tags = []
        if owner := _text(item.get("owner")):
            tags.append(("plain", owner))
        if status := _text(item.get("status")):
            tags.append(("open", status))
        records.append(
            _record(index, heading, _tags(tags), summary, _text(item.get("rationale")), "")
        )
    return _section(title, "".join(records), len(valid))


def _insight_records(questions: list, roster: dict[str, str], limit: int | None = None) -> str:
    records = []
    for index, q in enumerate(questions if limit is None else questions[:limit], 1):
        tags: list[tuple[str, str]] = []
        if getattr(q, "starred", False):
            tags.append(("flag", "Starred"))
        item_type = _text(getattr(q, "item_type", ""))
        if item_type == "question":
            tags.append(("done", "Answered") if getattr(q, "answered", False) else ("open", "Unanswered"))
        elif item_type == "action_item" and getattr(q, "answered", False):
            tags.append(("done", "Closed"))
        if who := _attributed(q, roster):
            tags.append(("plain", who))
        if lens := _text(getattr(q, "lens_label", "")):
            tags.append(("plain", lens))
        if match := _text(getattr(q, "offering_match", "")):
            tags.append(("plain", "Offering matched"))
        else:
            match = ""
        why = _text(getattr(q, "rationale", ""))
        extra = ""
        if match:
            extra = f'<p class="why">{_e(match)}</p>'
        if summary := _text(getattr(q, "answer_summary", "")):
            extra += f'<p class="why">{_e(summary)}</p>'
        if followup := _text(getattr(q, "followup_question", "")):
            extra += f'<p class="why">Next: {_e(followup)}</p>'
        records.append(
            _record(index, _text(q.question), _tags(tags), "", why, extra + _evidence(_text(getattr(q, "source_context", ""))))
        )
    return "".join(records)


def _going_in(data: BriefingData) -> str:
    lines = [_text(getattr(d, "text", d)) for d in data.directives]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    items = "".join(f"<li>{_e(line)}</li>" for line in lines)
    return _section("What we went in for", f'<ul class="plain">{items}</ul>', len(lines))


def _appendix(data: BriefingData) -> str:
    if not data.transcript:
        return ""
    roster = _roster(data.speakers)
    turns = []
    for entry in data.transcript:
        stamp = getattr(entry, "timestamp", None)
        who = _attributed(entry, roster)
        speaker = f'<span class="who">{_e(who)}</span> ' if who else ""
        turns.append(
            f'<div class="turn"><div class="t">{_e(stamp.strftime("%H:%M:%S") if stamp else "")}</div>'
            f'<div class="s">{speaker}{_e(getattr(entry, "text", ""))}</div></div>'
        )
    return (
        '<details class="appendix"><summary>Full transcript'
        f'<span class="n">{len(data.transcript)} lines</span></summary>'
        f'<div class="turns">{"".join(turns)}</div></details>'
    )


def _colophon(session) -> str:
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    return (
        '<div class="colophon"><span>Prepared by Backchannel</span>'
        f"<span>{_e(generated)}</span></div>"
    )


def _document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title>"
        f"<style>{_STYLE}</style></head>"
        f'<body><article class="doc">{body}</article></body></html>'
    )


# --------------------------------------------------------------------------
# The two documents
# --------------------------------------------------------------------------


def render_briefing(data: BriefingData) -> str:
    """The synthesized briefing: the arbiter's read, then the evidence."""
    synthesis = data.synthesis
    labels = section_labels(_text(getattr(data.session, "meeting_type", "")) or "general")
    actions = _section_items(getattr(synthesis, "action_plan", None))
    opportunities = _section_items(getattr(synthesis, "top_opportunities", None))
    risks = _section_items(getattr(synthesis, "risks_blockers", None))
    open_questions = _section_items(getattr(synthesis, "unresolved_discovery_questions", None))
    outcomes = _section_items(getattr(synthesis, "top_outcomes", None))

    masthead = _masthead(
        data,
        "post-call briefing",
        [
            ("Actions", len(actions), True),
            ("Opportunities", len(opportunities), False),
            ("Risks", len(risks), False),
            ("Still open", len(open_questions), False),
        ],
    )

    # The standfirst takes the leading outcome's TITLE, not its summary: the
    # summary is what the first record already says in full, and printing it
    # twice made the opening read like a duplicated paragraph.
    if outcomes:
        first = outcomes[0]
        lede = _text(first.get("title")) or _text(first.get("summary"))
    else:
        lede = (
            f"{len(data.questions)} insights were captured on this call; "
            f"{len(actions)} of them became commitments."
        )
    notes_line = (
        f"{len(data.questions)} insights captured / "
        f"{len(actions)} commitment{'s' if len(actions) != 1 else ''} / "
        f"{len(open_questions)} question{'s' if len(open_questions) != 1 else ''} still open"
    )
    if _text(getattr(synthesis, "status", "")) == "partial":
        notes_line += " / partial synthesis: one lens did not complete"
    note = f'<p class="standfirst-note">{_e(notes_line)}</p>' 

    roster = _roster(data.speakers)
    starred = [q for q in data.questions if getattr(q, "starred", False)]

    sections = [
        _synthesis_section(
            "Where this landed",
            getattr(synthesis, "top_outcomes", None),
            heading_in_standfirst=bool(outcomes) and lede == _text(outcomes[0].get("title")),
        ),
        _synthesis_section("What to do next", getattr(synthesis, "action_plan", None)),
        _synthesis_section(labels["objectives"], getattr(synthesis, "client_objectives", None)),
        _synthesis_section(labels["opportunities"], getattr(synthesis, "top_opportunities", None)),
        _synthesis_section("Risks and blockers", getattr(synthesis, "risks_blockers", None)),
        _synthesis_section(labels["questions"], getattr(synthesis, "unresolved_discovery_questions", None)),
    ]

    clusters = getattr(synthesis, "clusters", None) or []
    if clusters:
        records = [
            _record(
                index,
                _text(getattr(cluster, "title", "")),
                _tags([("plain", f"{_text(getattr(cluster, 'confidence', ''))} confidence")])
                if _text(getattr(cluster, "confidence", "")) else "",
                _text(getattr(cluster, "summary", "")),
                "",
                "",
            )
            for index, cluster in enumerate(clusters, 1)
        ]
        sections.append(_section("Threads running through it", "".join(records), len(clusters)))

    if starred:
        sections.append(
            _section(
                "Flagged during the call",
                _insight_records(starred, roster),
                len(starred),
            )
        )

    if going_in := _going_in(data):
        sections.append(going_in)

    if notes := _text(getattr(synthesis, "arbiter_notes", "")):
        sections.append(_section("Reconciliation notes", f'<div class="note">{_e(notes)}</div>'))

    body = (
        masthead
        + '<div class="body">'
        + f'<p class="lede">{_e(lede)}</p>{note}'
        + _figures(data)
        + "".join(sections)
        + _appendix(data)
        + _colophon(data.session)
        + "</div>"
    )
    return _document(f"{_text(getattr(data.session, 'name', '')) or 'Call'} briefing", body)


def render_record(data: BriefingData) -> str:
    """No synthesis stored: the same document, led by the insights themselves.

    This is not a lesser fallback with a plainer skin. It is the same shell,
    the same figures and the same evidence rule; only the source of the
    sections differs, because there is no arbiter read to lead with.
    """
    roster = _roster(data.speakers)
    by_type: dict[str, list] = {}
    for q in data.questions:
        by_type.setdefault(_text(getattr(q, "item_type", "")) or "question", []).append(q)

    actions = by_type.get("action_item", [])
    unanswered = [q for q in by_type.get("question", []) if not getattr(q, "answered", False)]
    starred = [q for q in data.questions if getattr(q, "starred", False)]

    masthead = _masthead(
        data,
        "call record",
        [
            ("Insights", len(data.questions), True),
            ("Commitments", len(actions), False),
            ("Still open", len(unanswered), False),
            ("Flagged", len(starred), False),
        ],
    )

    if data.questions:
        lede = (
            f"{len(data.questions)} insights came out of this call. "
            f"{len(actions)} became commitments and {len(unanswered)} questions are still open."
        )
    else:
        lede = "No insights were captured on this call. The transcript is below."

    sections = [
        _section(
            heading,
            _insight_records(by_type.get(slug, []), roster),
            len(by_type.get(slug, [])),
            empty=f"No {heading.lower()} were captured.",
        )
        for slug, heading in _TYPE_SECTIONS
        if by_type.get(slug)
    ]
    # Custom lens types keep their own slug and would otherwise vanish.
    for slug, rows in by_type.items():
        if slug not in dict(_TYPE_SECTIONS):
            sections.append(_section(_label(slug), _insight_records(rows, roster), len(rows)))

    if going_in := _going_in(data):
        sections.append(going_in)

    body = (
        masthead
        + '<div class="body">'
        + f'<p class="lede">{_e(lede)}</p>'
        + _figures(data)
        + "".join(sections)
        + _appendix(data)
        + _colophon(data.session)
        + "</div>"
    )
    return _document(f"{_text(getattr(data.session, 'name', '')) or 'Call'} record", body)
