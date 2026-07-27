"""Diagnostics for optional live diarization engines."""

from __future__ import annotations

import importlib
import math
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


SORTFORMER_MODEL_ID = "nvidia/diar_streaming_sortformer_4spk-v2"
SORTFORMER_LIVE_TRACKS = 2
SORTFORMER_CONTENTION_RESERVE = 1.5
SORTFORMER_BENCHMARK_WINDOWS = 3
SORTFORMER_RTF_THRESHOLD = 1 / (
    SORTFORMER_LIVE_TRACKS * SORTFORMER_CONTENTION_RESERVE
)
SORTFORMER_THIN_MARGIN = 0.25


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
    contention_adjusted_real_time_factor: float = math.inf
    peak_memory_mb: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if math.isinf(self.real_time_factor):
            data["real_time_factor"] = None
        if math.isinf(self.contention_adjusted_real_time_factor):
            data["contention_adjusted_real_time_factor"] = None
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
    peak_memory_mb: float | None = None,
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
        reason=describe_benchmark_headroom(
            real_time_factor,
            threshold=threshold,
            passed=passed,
        ),
        contention_adjusted_real_time_factor=(
            real_time_factor * SORTFORMER_CONTENTION_RESERVE
        ),
        peak_memory_mb=peak_memory_mb,
    )


def describe_benchmark_headroom(
    real_time_factor: float,
    *,
    threshold: float = SORTFORMER_RTF_THRESHOLD,
    passed: bool,
) -> str:
    measured = (
        1 / real_time_factor
        if math.isfinite(real_time_factor) and real_time_factor > 0
        else 0.0
    )
    required = 1 / threshold if math.isfinite(threshold) and threshold > 0 else math.inf
    margin = (measured / required) - 1 if math.isfinite(required) else -1.0
    comparison = (
        f"Sortformer sustained {measured:.2f}x realtime against "
        f"{required:.1f}x required for two live tracks with load reserve"
    )
    if not passed:
        return f"{comparison} ({abs(min(margin, 0)):.0%} short). Enhanced stays locked."
    if margin < SORTFORMER_THIN_MARGIN:
        return (
            f"{comparison} ({max(margin, 0):.0%} headroom). Margin is thin; "
            "lightweight diarization remains safer under heavier load."
        )
    return f"{comparison} ({margin:.0%} headroom)."


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

    memory_stop = threading.Event()
    memory_sampler: threading.Thread | None = None
    try:
        memory_samples = [_resident_memory_bytes()]
        memory_sampler = threading.Thread(
            target=_sample_resident_memory,
            args=(memory_stop, memory_samples),
            daemon=True,
        )
        memory_sampler.start()
        model = _load_sortformer_model(model_id)
        _prepare_model(model, environment.device)
        memory_samples.append(_resident_memory_bytes())
        processing_seconds = 0.0
        for _ in range(SORTFORMER_BENCHMARK_WINDOWS):
            started = time.perf_counter()
            _run_diarization(model, audio_path)
            processing_seconds += time.perf_counter() - started
            memory_samples.append(_resident_memory_bytes())
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
    finally:
        memory_stop.set()
        if memory_sampler is not None and memory_sampler.is_alive():
            memory_sampler.join()

    measurement = BenchmarkMeasurement(
        audio_seconds=audio_seconds * SORTFORMER_BENCHMARK_WINDOWS,
        processing_seconds=processing_seconds,
        device=environment.device,
        model_id=model_id,
    )
    return classify_benchmark(
        measurement,
        threshold=threshold,
        peak_memory_mb=_peak_memory_delta_mb(memory_samples),
    )


def _peak_memory_delta_mb(samples: list[int | None]) -> float | None:
    baseline = samples[0] if samples else None
    observed = [value for value in samples if value is not None]
    if baseline is None or not observed:
        return None
    peak = max(observed)
    return round((peak - baseline) / (1024 ** 2), 1) if peak > baseline else None


def _sample_resident_memory(
    stop: threading.Event,
    samples: list[int | None],
) -> None:
    while not stop.wait(0.05):
        samples.append(_resident_memory_bytes())


def _resident_memory_bytes() -> int | None:
    if os.name == "nt":
        try:
            import ctypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            get_memory = kernel32.K32GetProcessMemoryInfo
            get_memory.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ProcessMemoryCounters),
                ctypes.c_ulong,
            ]
            get_memory.restype = ctypes.c_int
            if get_memory(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            ):
                return int(counters.WorkingSetSize)
        except Exception:
            return None

    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        pass

    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except Exception:
        return None


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
