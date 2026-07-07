"""Download ONNX models for speaker diarization (Silero VAD + WeSpeaker ResNet152-LM)."""

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


def download_models():
    os.makedirs(MODELS_DIR, exist_ok=True)

    for filename, url in MODELS.items():
        dest = os.path.join(MODELS_DIR, filename)
        if os.path.exists(dest):
            size_mb = os.path.getsize(dest) / (1024 * 1024)
            print(f"  {filename} already exists ({size_mb:.1f} MB), skipping")
            continue

        print(f"  Downloading {filename} ...")
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  Saved {filename} ({size_mb:.1f} MB)")

    print("All models ready.")


if __name__ == "__main__":
    download_models()
