import asyncio
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.services.audio_utils import convert_to_pcm16, make_wav_header
from app.services.diarization_diagnostics import (
    benchmark_sortformer_audio,
    probe_sortformer_environment,
)
from app.services.diarizer_runtime import (
    get_diarizer_runtime_config,
    record_sortformer_benchmark,
    set_selected_diarizer,
    set_speaker_similarity_threshold,
)
from app.services.local_fit import (
    MIN_ASR_SECONDS,
    apply_recommended_intervals,
    clip_has_speech,
    is_asr_clip_too_short,
    run_asr_fit,
    run_local_fit,
    summarize_local_fit,
)
from app.services.capacity_admission import assess_call_capacity
from app.services.transcription_readiness import get_transcription_readiness
from app.services.transcription_runtime import (
    get_transcription_runtime_config,
    set_batch_transcriber_model,
    set_live_preview_model,
)
from app.services.voice_enrollment import (
    MAX_ENROLLMENT_SECONDS,
    MAX_ENROLLMENT_UPLOAD_BYTES,
    VoiceEnrollmentError,
    clear_local_voice_embedding,
    extract_enrollment_embedding,
    load_local_voice_embedding,
    save_local_voice_embedding,
)

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

_SUPPORTED_AUDIO_FORMATS = {".m4a", ".mp3", ".wav", ".ogg", ".flac", ".webm"}

# One full live Sortformer window is the minimum audio that yields a
# live-representative RTF; audio may run 5s past that mark before we trim.
MIN_BENCHMARK_SECONDS = settings.SORTFORMER_WINDOW_MS // 1000
MAX_BENCHMARK_SECONDS = MIN_BENCHMARK_SECONDS + 5
_PCM16_BYTES_PER_SECOND = 16000 * 2


def is_benchmark_pcm_too_short(pcm_data: bytes) -> bool:
    return len(pcm_data) < MIN_BENCHMARK_SECONDS * _PCM16_BYTES_PER_SECOND


def trim_benchmark_pcm(pcm_data: bytes) -> bytes:
    return pcm_data[: MAX_BENCHMARK_SECONDS * _PCM16_BYTES_PER_SECOND]


class DiarizerSelectionUpdate(BaseModel):
    selected_live_diarizer: str | None = None
    speaker_similarity_threshold: float | None = None


class BatchTranscriberUpdate(BaseModel):
    batch_model_id: str | None = None
    live_preview_model_id: str | None = None


class LocalFitIntervalUpdate(BaseModel):
    slug: str
    interval_seconds: int


class LocalFitApplyRequest(BaseModel):
    model_id: str
    updates: list[LocalFitIntervalUpdate]


def is_supported_benchmark_audio_filename(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in _SUPPORTED_AUDIO_FORMATS


def is_enrollment_upload_too_large(size: int) -> bool:
    return size > MAX_ENROLLMENT_UPLOAD_BYTES


@router.get("/diarization")
async def get_diarization_diagnostics(db: AsyncSession = Depends(get_db)):
    environment = probe_sortformer_environment()
    runtime = await get_diarizer_runtime_config(db, environment=environment)
    return {**environment.to_dict(), **runtime.to_dict()}


@router.patch("/diarization/config")
async def update_diarization_config(
    update: DiarizerSelectionUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        if update.selected_live_diarizer is not None:
            runtime = await set_selected_diarizer(db, update.selected_live_diarizer)
        else:
            runtime = await get_diarizer_runtime_config(db)
        if update.speaker_similarity_threshold is not None:
            runtime = await set_speaker_similarity_threshold(db, update.speaker_similarity_threshold)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    environment = probe_sortformer_environment()
    return {**environment.to_dict(), **runtime.to_dict()}


@router.get("/diarization/voice-profile")
async def get_voice_profile_status(db: AsyncSession = Depends(get_db)):
    return {"enrolled": await load_local_voice_embedding(db) is not None}


@router.put("/diarization/voice-profile")
async def replace_voice_profile(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not is_supported_benchmark_audio_filename(filename):
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    content = await file.read(MAX_ENROLLMENT_UPLOAD_BYTES + 1)
    if is_enrollment_upload_too_large(len(content)):
        raise HTTPException(413, "Voice sample is too large.")

    try:
        pcm_data = await asyncio.to_thread(
            convert_to_pcm16,
            content,
            ext.lstrip("."),
            max_seconds=MAX_ENROLLMENT_SECONDS,
        )
    except Exception as exc:
        raise HTTPException(400, f"Audio conversion failed: {exc}") from exc
    try:
        embedding = await asyncio.to_thread(extract_enrollment_embedding, pcm_data)
    except VoiceEnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "Voice profile extraction failed.") from exc

    await save_local_voice_embedding(db, embedding)
    await db.commit()
    return {"enrolled": True}


@router.delete("/diarization/voice-profile", status_code=204)
async def delete_voice_profile(db: AsyncSession = Depends(get_db)):
    await clear_local_voice_embedding(db)
    await db.commit()


@router.get("/transcription")
async def get_transcription_config(db: AsyncSession = Depends(get_db)):
    runtime = await get_transcription_runtime_config(db)
    return runtime.to_dict()


@router.get("/transcription/readiness")
async def get_transcription_readiness_status(db: AsyncSession = Depends(get_db)):
    readiness = await get_transcription_readiness(db)
    return readiness.to_dict()


@router.get("/capacity")
async def get_call_capacity(
    track_count: int = Query(2, ge=1, le=2),
    db: AsyncSession = Depends(get_db),
):
    """Call-start capacity admission: measured headroom for the selected config.

    track_count defaults to 2 (mic plus system audio), the conservative
    dual-track case; pass 1 for a mic-only call. The response is measured
    headroom rather than a boolean, and names what it does and does not yet
    model (see capacity_admission).
    """
    assessment = await assess_call_capacity(db, track_count=track_count)
    return assessment.to_dict()


@router.patch("/transcription/config")
async def update_transcription_config(
    update: BatchTranscriberUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        runtime = await get_transcription_runtime_config(db)
        if update.batch_model_id is not None:
            runtime = await set_batch_transcriber_model(db, update.batch_model_id)
        if update.live_preview_model_id is not None:
            runtime = await set_live_preview_model(db, update.live_preview_model_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return runtime.to_dict()


@router.get("/local-fit")
async def get_local_fit_summary(db: AsyncSession = Depends(get_db)):
    """What the fit test can measure: on-prem text models plus current intervals."""
    return await summarize_local_fit(db)


@router.post("/local-fit/run")
async def run_local_fit_test(db: AsyncSession = Depends(get_db)):
    """Benchmark every on-prem text model and score each live agent role."""
    return await run_local_fit(db)


@router.post("/local-fit/apply")
async def apply_local_fit_intervals(
    body: LocalFitApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply recommended per-model cycle budgets to the matching agents."""
    try:
        applied = await apply_recommended_intervals(
            db, body.model_id, [u.model_dump() for u in body.updates]
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"applied": applied}


@router.post("/local-fit/asr")
async def benchmark_local_asr(file: UploadFile):
    """Measure real-time factor for the local ONNX ASR models on an uploaded clip."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not is_supported_benchmark_audio_filename(filename):
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    content = await file.read()
    try:
        pcm_data = convert_to_pcm16(content, ext.lstrip("."))
    except Exception as exc:
        raise HTTPException(400, f"Audio conversion failed: {exc}") from exc
    if is_asr_clip_too_short(pcm_data):
        raise HTTPException(
            400, f"Clip must be at least {MIN_ASR_SECONDS} seconds of audio."
        )
    if not clip_has_speech(pcm_data):
        raise HTTPException(
            400, "Clip needs audible speech to measure transcription speed."
        )
    return await run_asr_fit(pcm_data)


@router.post("/diarization/sortformer/benchmark")
async def benchmark_sortformer(file: UploadFile, db: AsyncSession = Depends(get_db)):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not is_supported_benchmark_audio_filename(filename):
        raise HTTPException(400, f"Unsupported audio format: {ext}")

    content = await file.read()
    source_format = ext.lstrip(".")
    try:
        pcm_data = await asyncio.to_thread(convert_to_pcm16, content, source_format)
    except Exception as exc:
        raise HTTPException(400, f"Audio conversion failed: {exc}") from exc
    if is_benchmark_pcm_too_short(pcm_data):
        raise HTTPException(
            400,
            f"Benchmark audio must be at least {MIN_BENCHMARK_SECONDS} seconds long "
            "(one live diarization window).",
        )
    pcm_data = trim_benchmark_pcm(pcm_data)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(make_wav_header(pcm_data))
            tmp.write(pcm_data)
            tmp_path = tmp.name

        result = await asyncio.to_thread(benchmark_sortformer_audio, tmp_path)
        await record_sortformer_benchmark(db, result)
        return result.to_dict()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
