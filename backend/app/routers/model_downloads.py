"""What the app is fetching, how far along, and what failed.

One read for every model download in the process, so the browser can show a
banner while weights arrive instead of leaving a first-use fetch to look like
a hang (ALP-373).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.services import model_downloads
from app.services.pii import ner

router = APIRouter(prefix="/api/model-downloads", tags=["model-downloads"])

# Keys a client is allowed to retry. Resolved when the retry runs rather than
# captured at import, so the starter is always the current one.
_RETRYABLE = {ner.DOWNLOAD_KEY: lambda: ner.install()}


@router.get("")
async def list_downloads():
    return model_downloads.snapshot()


@router.post("/{key}/retry", status_code=202)
async def retry(key: str):
    """Start a failed download over.

    Only downloads the app knows how to start on its own are retryable; a
    local ASR model is fetched by the transcription that needs it, so there is
    nothing sensible to kick off from here.
    """
    starter = _RETRYABLE.get(key)
    if starter is None:
        raise HTTPException(404, f"No retryable download named {key}.")
    if model_downloads.is_running(key):
        return model_downloads.get(key)
    model_downloads.forget(key)
    asyncio.create_task(asyncio.to_thread(starter))
    return {"key": key, "state": model_downloads.QUEUED}


@router.delete("/{key}", status_code=204)
async def dismiss(key: str):
    """Drop a finished or failed entry so it stops being reported."""
    if model_downloads.is_running(key):
        raise HTTPException(409, "That download is still running.")
    model_downloads.forget(key)
