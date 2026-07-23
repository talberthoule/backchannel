"""Shared audio utility functions."""

import struct
from math import ceil

import numpy as np


def make_wav_header(
    pcm_data: bytes,
    sample_rate: int = 16000,
    bits_per_sample: int = 16,
    channels: int = 1,
) -> bytes:
    """Create a minimal WAV header for raw PCM data."""
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8

    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,
        b'WAVE',
        b'fmt ',
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size,
    )
    return header


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert PCM16 bytes to float32 numpy array in [-1, 1]."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def convert_to_pcm16(
    file_bytes: bytes,
    source_format: str,
    *,
    max_seconds: float | None = None,
) -> bytes:
    """Convert audio file bytes to PCM16 16kHz mono using soundfile/ffmpeg."""
    import io
    import subprocess
    import tempfile

    # Try soundfile first (handles WAV, FLAC, OGG)
    try:
        import soundfile as sf
        with sf.SoundFile(io.BytesIO(file_bytes)) as source:
            sr = source.samplerate
            target_samples = int(max_seconds * 16000) + 1 if max_seconds is not None else None
            source_frames = ceil(target_samples * sr / 16000) if target_samples is not None else -1
            data = source.read(frames=source_frames, dtype="int16", always_2d=True)
        # Mix to mono
        if data.shape[1] > 1:
            data = data.mean(axis=1).astype(np.int16)
        else:
            data = data[:, 0]
        # Resample to 16kHz if needed
        if sr != 16000:
            # Simple linear resample
            indices = np.linspace(0, len(data) - 1, int(len(data) * 16000 / sr))
            data = np.interp(indices, np.arange(len(data)), data.astype(np.float32))
            data = data.astype(np.int16)
        return data.tobytes()
    except Exception:
        pass

    # Fallback to ffmpeg for formats like m4a, mp3
    with tempfile.NamedTemporaryFile(suffix=f".{source_format}", delete=False) as tmp_in:
        tmp_in.write(file_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path + ".raw"
    try:
        output_limit = int(max_seconds * 16000) + 1 if max_seconds is not None else None
        duration_args = ["-t", f"{output_limit / 16000:.8f}"] if output_limit is not None else []
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", tmp_in_path,
                *duration_args,
                "-ar", "16000", "-ac", "1", "-f", "s16le",
                tmp_out_path,
            ],
            capture_output=True,
            check=True,
        )
        with open(tmp_out_path, "rb") as f:
            return f.read(output_limit * 2 if output_limit is not None else -1)
    finally:
        import os
        os.unlink(tmp_in_path)
        if os.path.exists(tmp_out_path):
            os.unlink(tmp_out_path)
