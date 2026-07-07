"""Ordered transcription queue for diarized audio segments."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TranscribeFn = Callable[[bytes], Awaitable[str | None]]
EmitFn = Callable[[str, bytes, str], Awaitable[None]]


@dataclass(frozen=True)
class TranscriptionResult:
    speaker_auto_id: str
    pcm_bytes: bytes
    text: str | None


class OrderedTranscriptionQueue:
    """Run transcriptions with bounded concurrency and emit results in input order."""

    def __init__(
        self,
        transcribe: TranscribeFn,
        emit: EmitFn,
        max_concurrency: int = 3,
        transcribe_timeout_seconds: float | None = 90.0,
        emit_timeout_seconds: float | None = 60.0,
    ):
        self._transcribe = transcribe
        self._emit = emit
        self._transcribe_timeout_seconds = transcribe_timeout_seconds
        self._emit_timeout_seconds = emit_timeout_seconds
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._results: dict[int, TranscriptionResult] = {}
        self._next_job_index = 0
        self._next_emit_index = 0
        self._closed = False

    def add(self, speaker_auto_id: str, pcm_bytes: bytes) -> int:
        if self._closed:
            raise RuntimeError("Cannot add transcription job after queue drain")
        index = self._next_job_index
        self._next_job_index += 1
        task = asyncio.create_task(self._run(index, speaker_auto_id, pcm_bytes))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return index

    async def drain(self):
        self._closed = True
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        await self._emit_ready()

    async def _run(self, index: int, speaker_auto_id: str, pcm_bytes: bytes):
        text = None
        try:
            async with self._semaphore:
                if self._transcribe_timeout_seconds is None:
                    text = await self._transcribe(pcm_bytes)
                else:
                    text = await asyncio.wait_for(
                        self._transcribe(pcm_bytes),
                        timeout=self._transcribe_timeout_seconds,
                    )
        except asyncio.TimeoutError:
            logger.error("Transcription job %s timed out", index)
        except Exception as exc:
            logger.error("Transcription job %s failed: %s", index, exc)

        async with self._lock:
            self._results[index] = TranscriptionResult(speaker_auto_id, pcm_bytes, text)
        await self._emit_ready()

    async def _emit_ready(self):
        async with self._lock:
            while self._next_emit_index in self._results:
                result = self._results.pop(self._next_emit_index)
                self._next_emit_index += 1
                if not result.text:
                    continue
                try:
                    if self._emit_timeout_seconds is None:
                        await self._emit(result.speaker_auto_id, result.pcm_bytes, result.text)
                    else:
                        await asyncio.wait_for(
                            self._emit(result.speaker_auto_id, result.pcm_bytes, result.text),
                            timeout=self._emit_timeout_seconds,
                        )
                except asyncio.TimeoutError:
                    logger.error("Ordered transcript emit timed out")
                except Exception as exc:
                    logger.error("Ordered transcript emit failed: %s", exc)
