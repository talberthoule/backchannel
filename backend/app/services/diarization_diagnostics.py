"""Diagnostics for optional live diarization engines."""

from __future__ import annotations

import importlib
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


SORTFORMER_MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2"
SORTFORMER_RTF_THRESHOLD = 0.7


@dataclass(frozen=True)
class SortformerEnvironment:
    torch_available: bool
    sortformer_available: bool
    cuda_available: bool
    device: str
    gpu_name: str | None
    gpu_memory_gb: float | None
    model_id: str
    status: str
    recommended_live_diarizer: str
    reason: str
    # "cuda", "rocm", or "none". ROCm torch builds report through the
    # torch.cuda API, so cuda_available stays true for AMD GPUs too.
    gpu_backend: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkMeasurement:
    audio_seconds: float
    processing_seconds: float
    device: str
    model_id: str


@dataclass(frozen=True)
class BenchmarkResult:
    status: str
    recommended_live_diarizer: str
    real_time_factor: float
    audio_seconds: float
    processing_seconds: float
    device: str
    model_id: str
    threshold: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if math.isinf(self.real_time_factor):
            data["real_time_factor"] = None
        return data


def probe_sortformer_environment(
    import_module: Callable[[str], Any] = importlib.import_module,
    model_id: str = SORTFORMER_MODEL_ID,
) -> SortformerEnvironment:
    try:
        torch = import_module("torch")
    except Exception as exc:
        return SortformerEnvironment(
            torch_available=False,
            sortformer_available=False,
            cuda_available=False,
            device="cpu",
            gpu_name=None,
            gpu_memory_gb=None,
            model_id=model_id,
            status="unavailable",
            recommended_live_diarizer="lightweight",
            reason=f"Torch is not available: {exc}",
        )

    cuda_available = bool(getattr(torch.cuda, "is_available", lambda: False)())
    device = "cuda" if cuda_available else "cpu"
    gpu_backend = _gpu_backend(torch, cuda_available)
    gpu_name = None
    gpu_memory_gb = None

    if cuda_available:
        gpu_name = _safe_cuda_name(torch)
        gpu_memory_gb = _safe_cuda_memory(torch)

    try:
        asr_models = import_module("nemo.collections.asr.models")
        sortformer_available = _get_sortformer_class(asr_models) is not None
    except Exception as exc:
        return SortformerEnvironment(
            torch_available=True,
            sortformer_available=False,
            cuda_available=cuda_available,
            device=device,
            gpu_name=gpu_name,
            gpu_memory_gb=gpu_memory_gb,
            model_id=model_id,
            status="unavailable",
            recommended_live_diarizer="lightweight",
            reason=f"NeMo Sortformer is not available: {exc}",
            gpu_backend=gpu_backend,
        )

    if not sortformer_available:
        return SortformerEnvironment(
            torch_available=True,
            sortformer_available=False,
            cuda_available=cuda_available,
            device=device,
            gpu_name=gpu_name,
            gpu_memory_gb=gpu_memory_gb,
            model_id=model_id,
            status="unavailable",
            recommended_live_diarizer="lightweight",
            reason="NeMo ASR is installed, but no Sortformer model class was found.",
            gpu_backend=gpu_backend,
        )

    status = "ready" if cuda_available else "benchmark_required"
    if cuda_available:
        backend_label = "ROCm" if gpu_backend == "rocm" else "CUDA"
        reason = f"Sortformer is installed with {backend_label} acceleration. Run the benchmark before enabling it for live calls."
    else:
        reason = (
            "Sortformer is installed, but no CUDA or ROCm GPU was detected. "
            "It will run on CPU; a passing benchmark still unlocks Enhanced mode."
        )
    return SortformerEnvironment(
        torch_available=True,
        sortformer_available=True,
        cuda_available=cuda_available,
        device=device,
        gpu_name=gpu_name,
        gpu_memory_gb=gpu_memory_gb,
        model_id=model_id,
        status=status,
        recommended_live_diarizer="lightweight",
        reason=reason,
        gpu_backend=gpu_backend,
    )


def classify_benchmark(
    measurement: BenchmarkMeasurement,
    threshold: float = SORTFORMER_RTF_THRESHOLD,
) -> BenchmarkResult:
    if measurement.audio_seconds <= 0:
        real_time_factor = math.inf
    else:
        real_time_factor = measurement.processing_seconds / measurement.audio_seconds

    passed = real_time_factor <= threshold
    return BenchmarkResult(
        status="passed" if passed else "failed",
        recommended_live_diarizer="sortformer" if passed else "lightweight",
        real_time_factor=real_time_factor,
        audio_seconds=measurement.audio_seconds,
        processing_seconds=measurement.processing_seconds,
        device=measurement.device,
        model_id=measurement.model_id,
        threshold=threshold,
        reason=(
            "Sortformer processed the sample fast enough for live use."
            if passed
            else "Sortformer did not process the sample fast enough for live use."
        ),
    )


def benchmark_sortformer_audio(
    audio_path: str | Path,
    model_id: str = SORTFORMER_MODEL_ID,
    threshold: float = SORTFORMER_RTF_THRESHOLD,
) -> BenchmarkResult:
    audio_seconds = _audio_duration_seconds(audio_path)
    environment = probe_sortformer_environment(model_id=model_id)
    if not environment.sortformer_available:
        return BenchmarkResult(
            status="unavailable",
            recommended_live_diarizer="lightweight",
            real_time_factor=math.inf,
            audio_seconds=audio_seconds,
            processing_seconds=0.0,
            device=environment.device,
            model_id=model_id,
            threshold=threshold,
            reason=environment.reason,
        )

    try:
        model = _load_sortformer_model(model_id)
        _prepare_model(model, environment.device)
        started = time.perf_counter()
        _run_diarization(model, audio_path)
        processing_seconds = time.perf_counter() - started
    except Exception as exc:
        return BenchmarkResult(
            status="failed",
            recommended_live_diarizer="lightweight",
            real_time_factor=math.inf,
            audio_seconds=audio_seconds,
            processing_seconds=0.0,
            device=environment.device,
            model_id=model_id,
            threshold=threshold,
            reason=f"Sortformer benchmark failed: {exc}",
        )

    measurement = BenchmarkMeasurement(
        audio_seconds=audio_seconds,
        processing_seconds=processing_seconds,
        device=environment.device,
        model_id=model_id,
    )
    return classify_benchmark(measurement, threshold=threshold)


def _gpu_backend(torch: Any, cuda_available: bool) -> str:
    if not cuda_available:
        return "none"
    hip_version = getattr(getattr(torch, "version", None), "hip", None)
    return "rocm" if hip_version else "cuda"


def _safe_cuda_name(torch: Any) -> str | None:
    try:
        return str(torch.cuda.get_device_name(0))
    except Exception:
        return None


def _safe_cuda_memory(torch: Any) -> float | None:
    try:
        props = torch.cuda.get_device_properties(0)
        return round(float(props.total_memory) / (1024 ** 3), 2)
    except Exception:
        return None


def _get_sortformer_class(asr_models: Any) -> Any | None:
    return getattr(asr_models, "SortformerEncLabelModel", None)


def _load_sortformer_model(model_id: str) -> Any:
    asr_models = importlib.import_module("nemo.collections.asr.models")
    sortformer_cls = _get_sortformer_class(asr_models)
    if sortformer_cls is None:
        raise RuntimeError("SortformerEncLabelModel is not available in NeMo.")
    return sortformer_cls.from_pretrained(model_name=model_id)


def _prepare_model(model: Any, device: str) -> None:
    if hasattr(model, "to"):
        model.to(device)
    if hasattr(model, "eval"):
        model.eval()


def _run_diarization(model: Any, audio_path: str | Path) -> Any:
    if not hasattr(model, "diarize"):
        raise RuntimeError("Loaded Sortformer model does not expose diarize().")

    path = str(audio_path)
    try:
        return model.diarize(audio=[path], batch_size=1)
    except TypeError:
        return model.diarize(audio=path)


def _audio_duration_seconds(audio_path: str | Path) -> float:
    try:
        import soundfile as sf

        info = sf.info(str(audio_path))
        return float(info.frames) / float(info.samplerate)
    except Exception:
        return 0.0
