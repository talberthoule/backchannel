"""Download ONNX models for speaker diarization (Silero VAD + WeSpeaker ResNet152-LM).

Default run fetches only what the app needs at runtime. Pass --optional to also
fetch the evaluation-only models used by scripts/diarizer_ab.py.
"""

import argparse
import os
import urllib.request

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")

MODELS = {
    "silero_vad.onnx": "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx",
    # WeSpeaker ResNet152-LM speaker embedding (VoxCeleb, EER 0.495% vox1-O).
    # Replaces the legacy ecapa_tdnn.onnx file, which actually contained
    # WeSpeaker ResNet34-LM (EER 0.723%) under a misleading name.
    "voxceleb_resnet152_LM.onnx": "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet152-LM/resolve/main/voxceleb_resnet152_LM.onnx",
}

# Opt-in downloads. Not fetched by a normal install; nothing at runtime reads
# them. scripts/diarizer_ab.py uses these to A/B embedding models offline.
OPTIONAL_MODELS = {
    # WeSpeaker ResNet34-LM (VoxCeleb, EER 0.723% vox1-O), ~25 MB against the
    # ResNet152-LM's ~75 MB. This is the same architecture the legacy
    # ecapa_tdnn.onnx file held, published here under its true name.
    "voxceleb_resnet34_LM.onnx": "https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34-LM/resolve/main/voxceleb_resnet34_LM.onnx",
}


def _fetch(models: dict) -> None:
    for filename, url in models.items():
        dest = os.path.join(MODELS_DIR, filename)
        if os.path.exists(dest):
            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"  {filename} already exists ({size_mb:.1f} MB), skipping")
            continue

        print(f"  Downloading {filename} ...")
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  Saved {filename} ({size_mb:.1f} MB)")


def download_models(include_optional: bool = False):
    os.makedirs(MODELS_DIR, exist_ok=True)
    _fetch(MODELS)
    if include_optional:
        print("Optional evaluation models:")
        _fetch(OPTIONAL_MODELS)
    print("All models ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download diarization ONNX models")
    parser.add_argument(
        "--optional",
        action="store_true",
        help="also fetch evaluation-only models (WeSpeaker ResNet34-LM)",
    )
    download_models(include_optional=parser.parse_args().optional)
