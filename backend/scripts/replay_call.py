"""Replay a recorded call into the live WebSocket pipeline, silently.

Feeds stored per-track audio to /ws/{session_id} exactly as the browser does:
one-byte track prefix plus PCM16 16 kHz mono, in 100 ms chunks, paced to
wall-clock. Everything the live path does then happens for real - diarization,
batch transcription, every agent loop, token accounting, and the post-call
drain - with no audio device involved and nobody listening.

Why the split tracks rather than the mixed file: the mixed recording is
mic + system summed, and on a speakerphone the remote voice is already present
in the mic a couple of hundred milliseconds later, so the sum carries an
audible echo. The live pipeline never saw that - it diarizes each track
separately and mixes only for the audio gateway. Replaying the split tracks is
both echo-free and a faithful reproduction; replaying the mixed file would feed
the pipeline something it never received.

Pacing is realtime by default and should stay that way for any measurement.
Agent cadence is wall-clock (objection handler every 10 s, analyst every 40 s,
synthesizer on a 75 s cooldown), so replaying faster gives the agents fewer
cycles per unit of transcript and the token totals stop being comparable.
--speed exists to smoke-test this script, not to produce numbers.

Usage, from backend/:
    python scripts/replay_call.py --audio-dir /app/data/audio/<session-uuid>
    python scripts/replay_call.py --audio-dir <dir> --name "Replay A" --meeting-type general
    python scripts/replay_call.py --audio-dir <dir> --speed 20 --minutes 3   # smoke test only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import wave

try:
    import websockets
except ImportError:  # pragma: no cover - dependency guard
    print("websockets is required: pip install websockets", file=sys.stderr)
    raise

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * BYTES_PER_SAMPLE * CHUNK_MS // 1000  # 3200
TRACK_MIC = 0
TRACK_SYS = 1


def _read_pcm(path: str) -> bytes:
    with wave.open(path) as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit(
                f"{path}: expected 16 kHz mono PCM16, got {w.getframerate()} Hz "
                f"{w.getnchannels()}ch {w.getsampwidth() * 8}-bit"
            )
        return w.readframes(w.getnframes())


def load_tracks(audio_dir: str, segment: int) -> tuple[bytes, bytes]:
    """Prefer the split tracks; fall back to the mixed file as mic-only.

    A mixed-only session has no way to reconstruct the two tracks, so it
    replays as a single mic track. Speaker attribution will differ from the
    original run and the token comparison is weakened - the script says so
    rather than pretending otherwise.
    """
    mic_path = os.path.join(audio_dir, f"segment_{segment}_mic.wav")
    sys_path = os.path.join(audio_dir, f"segment_{segment}_sys.wav")
    mixed_path = os.path.join(audio_dir, f"segment_{segment}.wav")

    if os.path.exists(mic_path) and os.path.exists(sys_path):
        return _read_pcm(mic_path), _read_pcm(sys_path)

    if os.path.exists(mixed_path):
        print(
            "WARNING: no split tracks for this segment; replaying the mixed file as a\n"
            "         single mic track. The original run diarized two tracks, so speaker\n"
            "         attribution will not match and token totals are only indicative.",
            file=sys.stderr,
        )
        return _read_pcm(mixed_path), b""

    raise SystemExit(f"no segment_{segment} audio found in {audio_dir}")


async def create_session(base_url: str, name: str, meeting_type: str, context: str) -> str:
    import urllib.request

    body = json.dumps(
        {"name": name, "meeting_type": meeting_type, "meeting_context": context, "notes": ""}
    ).encode()
    req = urllib.request.Request(
        f"{base_url}/api/sessions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)["id"]


async def _drain_server_messages(ws, state: dict):
    """Consume server traffic so the socket never stalls, and log the milestones."""
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            kind = message.get("type")
            data = message.get("data", {})
            if kind == "transcript":
                state["transcripts"] += 1
            elif kind == "question":
                state["insights"] += 1
            elif kind == "status":
                s = data.get("state")
                if s in {"connecting", "active", "transcription_unready", "completed"}:
                    print(f"  [status] {s}: {data.get('message', '')}")
                elif s == "post_processing":
                    stage = data.get("stage", "")
                    if stage and stage != state.get("last_stage"):
                        state["last_stage"] = stage
                        print(f"  [post] {stage}: {data.get('message', '')}")
                elif s in {"diarization_overloaded", "transcription_error", "audio_error"}:
                    print(f"  [WARN] {s}: {data.get('message', '')}")
                if s == "completed":
                    state["completed"] = True
    except Exception:
        # Socket closed by the server after completion; nothing to recover.
        pass


async def stream(
    ws_url: str,
    mic: bytes,
    system: bytes,
    speed: float,
    limit_seconds: float | None,
) -> dict:
    state = {"transcripts": 0, "insights": 0, "completed": False, "last_stage": None}
    total = max(len(mic), len(system))
    if limit_seconds:
        cap = int(limit_seconds * SAMPLE_RATE * BYTES_PER_SAMPLE)
        total = min(total, cap)
    chunks = (total + CHUNK_BYTES - 1) // CHUNK_BYTES
    audio_seconds = total / (SAMPLE_RATE * BYTES_PER_SAMPLE)

    async with websockets.connect(ws_url, max_size=None, ping_interval=20) as ws:
        reader = asyncio.create_task(_drain_server_messages(ws, state))

        if system:
            await ws.send(json.dumps({"type": "track_state", "track": 1, "active": True}))

        started = time.monotonic()
        for index in range(chunks):
            offset = index * CHUNK_BYTES
            mic_chunk = mic[offset:offset + CHUNK_BYTES]
            sys_chunk = system[offset:offset + CHUNK_BYTES]

            if mic_chunk:
                await ws.send(bytes([TRACK_MIC]) + mic_chunk)
            if sys_chunk:
                await ws.send(bytes([TRACK_SYS]) + sys_chunk)

            # Pace against elapsed wall time rather than sleeping a fixed step,
            # so send latency does not accumulate into drift over an hour.
            target = (index + 1) * (CHUNK_MS / 1000.0) / speed
            drift = target - (time.monotonic() - started)
            if drift > 0:
                await asyncio.sleep(drift)

            if index % 600 == 0 and index:
                done = index * CHUNK_MS / 1000.0
                print(
                    f"  {done / 60:5.1f} / {audio_seconds / 60:.1f} min fed"
                    f"   transcripts={state['transcripts']}  insights={state['insights']}"
                )

        print("  audio exhausted; sending stop and waiting for post-processing")
        await ws.send(json.dumps({"type": "stop", "drain": "full"}))

        # The final drain runs several LLM passes; wait for the completed status
        # rather than a fixed timeout, but do not hang forever on a dead socket.
        for _ in range(1800):
            if state["completed"]:
                break
            await asyncio.sleep(1)

        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio-dir", required=True, help="directory holding segment_N*.wav")
    parser.add_argument("--segment", type=int, default=1)
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--ws-url", default=None, help="defaults to base-url with ws scheme")
    parser.add_argument("--session-id", default=None, help="replay into an existing session instead of creating one")
    parser.add_argument("--name", default=None)
    parser.add_argument("--meeting-type", default="general")
    parser.add_argument("--meeting-context", default="")
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="playback multiplier. Leave at 1.0 for anything you intend to measure: "
             "agent cadence is wall-clock, so faster replay changes token totals.",
    )
    parser.add_argument("--minutes", type=float, default=None, help="stop after this much audio (smoke tests)")
    args = parser.parse_args()

    mic, system = load_tracks(args.audio_dir, args.segment)
    audio_seconds = max(len(mic), len(system)) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    if args.minutes:
        audio_seconds = min(audio_seconds, args.minutes * 60)

    if args.speed != 1.0:
        print(
            f"WARNING: --speed {args.speed} makes token totals NOT comparable to a live call.\n"
            "         Agent loops sleep on wall-clock intervals, so a faster replay gives them\n"
            "         fewer cycles per unit of transcript. Use 1.0 for measurement.",
            file=sys.stderr,
        )

    session_id = args.session_id or asyncio.run(
        create_session(
            args.base_url,
            args.name or f"Replay of {os.path.basename(args.audio_dir)[:8]}",
            args.meeting_type,
            args.meeting_context,
        )
    )

    ws_base = args.ws_url or args.base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}/ws/{session_id}"

    print(f"session   : {session_id}")
    print(f"audio     : {audio_seconds / 60:.1f} min"
          f"  ({'split mic+sys' if system else 'mixed as mic-only'})")
    print(f"pace      : {args.speed}x -> about {audio_seconds / 60 / args.speed:.1f} min of wall time")
    print(f"websocket : {ws_url}")
    print()

    state = asyncio.run(stream(ws_url, mic, system, args.speed, audio_seconds))

    print()
    print(f"transcripts emitted : {state['transcripts']}")
    print(f"insights emitted    : {state['insights']}")
    print(f"post-processing     : {'completed' if state['completed'] else 'DID NOT COMPLETE'}")
    print()
    print(f"token usage: {args.base_url}/api/sessions/{session_id}/token-usage")
    return 0 if state["completed"] else 1


if __name__ == "__main__":
    sys.exit(main())
