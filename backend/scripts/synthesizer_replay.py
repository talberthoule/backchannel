"""Offline A/B for the synthesizer's prompt payload (ALP-283 / ALP-285).

Why offline. POST /api/sessions/{id}/analyze (app/routers/analyze.py) is a
single-shot call that never instantiates the orchestrator and never invokes the
synthesizer, so importing a transcript cannot exercise ALP-283 at all. The only
faithful cheap test is to replay a captured insight corpus, at the real cycle
times, through the real serializer from each side.

Both sides load the actual shipped `_build_insights_json` -- the baseline via
`git show <ref>`, the candidate from the working tree -- so neither side is a
reimplementation that could flatter its own result.

Modes:
  payload  input-token totals, baseline vs working tree
  prefix   cacheable-prefix retention between consecutive cycles
  scale    how both of the above vary with call length

Usage, from backend/ :
    export BACKCHANNEL_REPLAY_DATA=/path/to/captured/session
    python scripts/synthesizer_replay.py payload
    python scripts/synthesizer_replay.py prefix
    python scripts/synthesizer_replay.py scale --baseline origin/master

The data directory must hold q.json, t.json and speakers.json as returned by
GET /api/sessions/{id}/questions, /transcripts?limit=5000 and /speakers. It is
deliberately NOT in this repository: a captured corpus is real meeting content
and this repository is public. See scripts/README-synthesizer-replay.md.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

# Calibration: the reference blob measured 204,424 chars / 51,106 tokens, exactly
# 4.0 chars per token. The same ratio predicted the measured synthesizer input
# within 3.8 percent, so it is used rather than a paid count_tokens round trip.
CHARS_PER_TOKEN = 4.0

# Template overhead outside the two volatile blocks, measured on the reference run.
PROMPT_TEMPLATE_TOKENS = 1427

# EventBus cooldown for the synthesizer (services/seed_agents.py).
COOLDOWN_SECONDS = 75

# TranscriptBuffer._DEFAULT_BUFFER_SIZE -- what actually binds the window, not the
# advertised duration (ALP-287).
BUFFER_ENTRIES = 30

# ALP-285's assumed cached-input discount. Explicitly UNVERIFIED for the Gemini
# model versions in use; every "net" figure inherits that uncertainty.
CACHE_DISCOUNT = 0.75

SCALE_CUTOFFS_MIN = [10, 15, 20, 30, 40, 55]

SYNTH_PATH = "backend/app/services/agents/synthesizer.py"


def repo_root() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def data_dir() -> str:
    path = os.environ.get("BACKCHANNEL_REPLAY_DATA")
    if not path:
        sys.exit(
            "Set BACKCHANNEL_REPLAY_DATA to a directory holding q.json, t.json and\n"
            "speakers.json. See scripts/README-synthesizer-replay.md for how to\n"
            "capture them. The corpus is real meeting content and is deliberately\n"
            "not committed to this public repository."
        )
    if not os.path.isdir(path):
        sys.exit(f"BACKCHANNEL_REPLAY_DATA is not a directory: {path}")
    return path


def tokens(text: str) -> float:
    return len(text) / CHARS_PER_TOKEN


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def load_baseline(root: str, ref: str):
    """Import the serializer as it exists at `ref` without touching the worktree."""
    source = subprocess.run(
        ["git", "show", f"{ref}:{SYNTH_PATH}"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout
    fd, path = tempfile.mkstemp(suffix=".py", prefix="synth_baseline_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(source)
    spec = importlib.util.spec_from_file_location("synth_baseline", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["synth_baseline"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_corpus(path: str):
    def read(name):
        raw = json.load(open(os.path.join(path, name), encoding="utf-8"))
        return raw if isinstance(raw, list) else raw.get("items", [])

    speakers = {str(s["id"]): SimpleNamespace(**s) for s in read("speakers.json")}

    questions = []
    for r in read("q.json"):
        ns = SimpleNamespace(**r)
        ns.created_at = parse_ts(r.get("created_at"))
        ns.updated_at = parse_ts(r.get("updated_at"))
        # The baseline serializer walks the speaker relationship; omitting the real
        # Speaker row would under-measure the baseline payload.
        ns.speaker = speakers.get(str(r.get("speaker_id"))) if r.get("speaker_id") else None
        questions.append(ns)
    questions.sort(key=lambda q: (q.created_at, str(q.id)))

    entries = [(parse_ts(t.get("timestamp")), t.get("text") or "") for t in read("t.json")]
    entries = sorted([e for e in entries if e[0]], key=lambda e: e[0])
    return questions, entries


def live_at(questions, t):
    # Mirrors the v0.5.0 query: non-dismissed, excluding asked items.
    return [q for q in questions
            if q.created_at <= t and not q.dismissed and q.item_type != "asked"]


def replay(questions, entries, start, end, baseline, candidate):
    """One pass over the meeting. Returns per-cycle rows."""
    rows = []
    prev_base = prev_cand = None
    prev_stubs = set()
    window_s = max(0, int(getattr(candidate.settings, "SYNTHESIZER_WORKING_SET_SECONDS", 600)))
    t = start + timedelta(seconds=COOLDOWN_SECONDS)

    while t <= end:
        live = live_at(questions, t)
        if not live:
            t += timedelta(seconds=COOLDOWN_SECONDS)
            continue

        transcript = "\n".join([tx for ts, tx in entries if ts <= t][-BUFFER_ENTRIES:])
        base_json = baseline._build_insights_json(live)
        cand_json = candidate._build_insights_json(live, now=t)

        stubs = {str(q.id) for q in live
                 if not candidate._in_working_set(q, t - timedelta(seconds=window_s))}

        rows.append({
            "t": t,
            "live": len(live),
            "stubs": len(stubs),
            "flipped": len(stubs - prev_stubs),
            "base_in": tokens(base_json) + tokens(transcript) + PROMPT_TEMPLATE_TOKENS,
            "cand_in": tokens(cand_json) + tokens(transcript) + PROMPT_TEMPLATE_TOKENS,
            "base_blob": tokens(base_json),
            "cand_blob": tokens(cand_json),
            "base_prefix": common_prefix_len(prev_base, base_json) if prev_base else None,
            "cand_prefix": common_prefix_len(prev_cand, cand_json) if prev_cand else None,
            "base_len": len(base_json),
            "cand_len": len(cand_json),
        })
        prev_base, prev_cand, prev_stubs = base_json, cand_json, stubs
        t += timedelta(seconds=COOLDOWN_SECONDS)
    return rows


def effective(total_in, reuse):
    """Input cost once a cache prefix is priced in."""
    return (total_in - reuse) + reuse * (1 - CACHE_DISCOUNT)


def cmd_payload(rows, args):
    base = sum(r["base_in"] for r in rows)
    cand = sum(r["cand_in"] for r in rows)
    print(f"cycles              : {len(rows)}")
    print(f"baseline input      : {base:>12,.0f}")
    print(f"candidate input     : {cand:>12,.0f}")
    print(f"reduction           : {(base - cand) / base * 100:>11.1f}%")
    print()
    print("final cycle insight blob:")
    print(f"  baseline {rows[-1]['base_blob']:>10,.0f} tokens"
          f"   candidate {rows[-1]['cand_blob']:>10,.0f} tokens")
    print()
    print("The ratio is the trustworthy figure. The absolute over-predicts the")
    print("measured reference run, because real cycles sometimes spaced wider")
    print("than the cooldown.")


def cmd_prefix(rows, args):
    pairs = [r for r in rows if r["base_prefix"] is not None]
    print("Cacheable prefix carried from the previous cycle.")
    print("Ordering is identical on both sides, so this isolates serialization.")
    print()
    print(f"{'time':>9} {'live':>5} {'stubs':>6} {'flip':>5} |"
          f" {'baseline':>18} | {'candidate':>18}")
    print("-" * 82)
    for r in pairs[::4]:
        bp = r["base_prefix"] / r["base_len"] * 100
        cp = r["cand_prefix"] / r["cand_len"] * 100
        print(f"{r['t']:%H:%M:%S} {r['live']:>5} {r['stubs']:>6} {r['flipped']:>5} |"
              f" {r['base_prefix']:>9,} ch {bp:>5.1f}% |"
              f" {r['cand_prefix']:>9,} ch {cp:>5.1f}%")
    print("-" * 82)
    mb = sum(r["base_prefix"] / r["base_len"] for r in pairs) / len(pairs) * 100
    mc = sum(r["cand_prefix"] / r["cand_len"] for r in pairs) / len(pairs) * 100
    print(f"mean prefix retained : baseline {mb:.1f}%   candidate {mc:.1f}%")
    print(f"flips full->stub     : {sum(r['flipped'] for r in pairs)}")
    if mc < mb:
        print()
        print("The candidate reduces the cacheable prefix: a clock-driven")
        print("full/stub classification mutates early records, which breaks the")
        print("append-only property ALP-285 requires.")


def cmd_scale(rows_for, args):
    print(f"{'call len':>9} {'cycles':>7} {'flips':>6} |"
          f" {'prefix base':>12} {'prefix cand':>12} | {'raw win':>8} {'net win':>8}")
    print("-" * 78)
    for minutes in SCALE_CUTOFFS_MIN:
        rows = rows_for(timedelta(minutes=minutes))
        pairs = [r for r in rows if r["base_prefix"] is not None]
        if not pairs:
            continue
        base_in = sum(r["base_in"] for r in rows)
        cand_in = sum(r["cand_in"] for r in rows)
        base_reuse = sum(r["base_prefix"] for r in pairs) / CHARS_PER_TOKEN
        cand_reuse = sum(r["cand_prefix"] for r in pairs) / CHARS_PER_TOKEN
        mb = sum(r["base_prefix"] / r["base_len"] for r in pairs) / len(pairs) * 100
        mc = sum(r["cand_prefix"] / r["cand_len"] for r in pairs) / len(pairs) * 100
        raw = (base_in - cand_in) / base_in * 100
        be, ce = effective(base_in, base_reuse), effective(cand_in, cand_reuse)
        print(f"{minutes:>7} m {len(rows):>7} {sum(r['flipped'] for r in pairs):>6} |"
              f" {mb:>11.1f}% {mc:>11.1f}% | {raw:>7.1f}% {(be - ce) / be * 100:>7.1f}%")
    print("-" * 78)
    print("raw win = payload reduction with no caching, which is today's world")
    print(f"net win = reduction once a prefix cache is priced at {CACHE_DISCOUNT:.0%} off")
    print()
    print("A record cannot flip to stub before ageing past")
    print("SYNTHESIZER_WORKING_SET_SECONDS, so short calls show no conflict.")
    print("Validate on a call long enough to cross that boundary.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["payload", "prefix", "scale"])
    ap.add_argument("--baseline", default="origin/master",
                    help="git ref to compare the working tree against")
    args = ap.parse_args()

    root = repo_root()
    sys.path.insert(0, os.path.join(root, "backend"))
    questions, entries = load_corpus(data_dir())
    baseline = load_baseline(root, args.baseline)
    from app.services.agents import synthesizer as candidate  # noqa: E402

    start = min(entries[0][0], questions[0].created_at)
    full_end = max(entries[-1][0], questions[-1].created_at)
    print(f"baseline {args.baseline}   candidate working tree   "
          f"corpus {len(questions)} insights / {len(entries)} entries\n")

    if args.mode == "scale":
        cmd_scale(lambda h: replay(questions, entries, start, start + h, baseline, candidate), args)
    else:
        rows = replay(questions, entries, start, full_end, baseline, candidate)
        (cmd_payload if args.mode == "payload" else cmd_prefix)(rows, args)


if __name__ == "__main__":
    main()
