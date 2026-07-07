"""Install optional NeMo Sortformer dependencies when enabled."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


CUDA_TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu130"
CPU_TORCH_INDEX_URL = "https://download.pytorch.org/whl/cpu"
_FALSE_VALUES = {"0", "false", "no", "off"}


def nvidia_gpu_present() -> bool:
    return shutil.which("nvidia-smi") is not None


def resolve_torch_index_url(value: str) -> str:
    """Accept a full index URL, a PyTorch channel shorthand, or "auto".

    "auto" (also the default for empty values) picks CUDA wheels only when
    an NVIDIA GPU is visible (nvidia-smi on PATH) and the much smaller CPU
    wheels otherwise -- CPU inference speed is identical between the two.
    Shorthands map to https://download.pytorch.org/whl/<channel>, e.g.
    "cpu", "cu130" (NVIDIA CUDA), or "rocm6.4" (AMD ROCm, Linux only).
    """
    value = value.strip()
    if not value or value.lower() == "auto":
        return CUDA_TORCH_INDEX_URL if nvidia_gpu_present() else CPU_TORCH_INDEX_URL
    if value.startswith(("http://", "https://")):
        return value
    return f"https://download.pytorch.org/whl/{value}"


def should_install_sortformer() -> bool:
    return os.getenv("INSTALL_SORTFORMER", "true").strip().lower() not in _FALSE_VALUES


def ensure_sortformer_installed(required: bool = True) -> bool:
    if not should_install_sortformer():
        print("Sortformer install disabled by INSTALL_SORTFORMER=false", flush=True)
        return False

    try:
        if not _module_available("torch"):
            _install_torch()
        if not _module_available("nemo.collections.asr.models"):
            _install_nemo()
        return True
    except Exception as exc:
        message = f"Sortformer dependency installation failed: {exc}"
        if required:
            raise RuntimeError(message) from exc
        print(message, flush=True)
        return False


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _install_torch() -> None:
    torch_index_url = resolve_torch_index_url(os.getenv("PYTORCH_INDEX_URL", "auto"))
    _run_pip(
        [
            "install",
            "--no-cache-dir",
            "torch",
            "torchvision",
            "torchaudio",
            "--index-url",
            torch_index_url,
        ]
    )


def _install_nemo() -> None:
    requirements_path = Path(__file__).resolve().parents[1] / "requirements-sortformer.txt"
    _run_pip(["install", "--no-cache-dir", "-r", str(requirements_path)])


def _run_pip(args: list[str]) -> None:
    command = [sys.executable, "-m", "pip", *args]
    print(f"Running: {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)


if __name__ == "__main__":
    ensure_sortformer_installed(required=True)
