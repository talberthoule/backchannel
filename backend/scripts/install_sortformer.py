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

# AMD's official PyTorch-on-Windows (ROCm) wheels. These are direct wheel URLs
# rather than a pip index, are built for Python 3.12 only (cp312), and require
# the Adrenalin 26.2.2+ driver. Supported GPUs include RDNA4 (gfx1200/gfx1201,
# e.g. Radeon RX 9070 / 9070 XT). Docs:
# https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/windows/install-pytorch.html
_ROCM_WINDOWS_BASE_URL = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1"
ROCM_WINDOWS_SDK_PACKAGES = [
    f"{_ROCM_WINDOWS_BASE_URL}/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl",
    f"{_ROCM_WINDOWS_BASE_URL}/rocm_sdk_devel-7.2.1-py3-none-win_amd64.whl",
    f"{_ROCM_WINDOWS_BASE_URL}/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl",
    f"{_ROCM_WINDOWS_BASE_URL}/rocm-7.2.1.tar.gz",
]
ROCM_WINDOWS_TORCH_PACKAGES = [
    f"{_ROCM_WINDOWS_BASE_URL}/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    f"{_ROCM_WINDOWS_BASE_URL}/torchaudio-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
    f"{_ROCM_WINDOWS_BASE_URL}/torchvision-0.24.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl",
]


def nvidia_gpu_present() -> bool:
    return shutil.which("nvidia-smi") is not None


def amd_gpu_present() -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return False
    names = result.stdout.lower()
    return "radeon" in names or "amd" in names


def use_rocm_windows_wheels(index_value: str) -> bool:
    """True when auto-detection should install AMD's Windows ROCm torch wheels."""
    if index_value.strip().lower() not in ("", "auto"):
        return False
    if sys.platform != "win32" or nvidia_gpu_present() or not amd_gpu_present():
        return False
    if sys.version_info[:2] != (3, 12):
        print(
            "AMD GPU detected, but the ROCm Windows torch wheels require Python 3.12 "
            f"(running {sys.version_info[0]}.{sys.version_info[1]}); "
            "installing CPU wheels instead. Use a Python 3.12 environment for GPU acceleration.",
            flush=True,
        )
        return False
    return True


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
    index_value = os.getenv("PYTORCH_INDEX_URL", "auto")
    if use_rocm_windows_wheels(index_value):
        _run_pip(["install", "--no-cache-dir", *ROCM_WINDOWS_SDK_PACKAGES])
        _run_pip(["install", "--no-cache-dir", *ROCM_WINDOWS_TORCH_PACKAGES])
        return

    torch_index_url = resolve_torch_index_url(index_value)
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
