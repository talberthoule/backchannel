"""Download a self-contained LGPL ffmpeg build into desktop/ffmpeg.

Windows and Linux desktop bundles ship this binary so audio conversion
(webm voice recordings, mp3/m4a imports) works without a system ffmpeg.
macOS bundles stay ffmpeg-free, matching docs/releasing.md.
"""

import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "ffmpeg"

_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
WINDOWS_URL = f"{_BTBN}/ffmpeg-master-latest-win64-lgpl.zip"
LINUX_URL = f"{_BTBN}/ffmpeg-master-latest-linux64-lgpl.tar.xz"


def build_url() -> str | None:
    if sys.platform == "win32":
        return WINDOWS_URL
    if sys.platform.startswith("linux"):
        return LINUX_URL
    return None


def binary_name() -> str:
    return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def main() -> None:
    target = DEST / binary_name()
    if target.exists():
        print(f"ffmpeg already present at {target}")
        return
    url = build_url()
    if url is None:
        print("no bundled ffmpeg for this platform; skipping")
        return
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as resp:
        payload = io.BytesIO(resp.read())
    if url.endswith(".zip"):
        with zipfile.ZipFile(payload) as zf:
            binary = next(n for n in zf.namelist() if n.endswith("bin/ffmpeg.exe"))
            target.write_bytes(zf.read(binary))
            license_member = next(
                (n for n in zf.namelist() if n.endswith("LICENSE.txt")), None
            )
            if license_member:
                (DEST / "LICENSE.txt").write_bytes(zf.read(license_member))
    else:
        with tarfile.open(fileobj=payload, mode="r:xz") as tf:
            binary = next(m for m in tf.getmembers() if m.name.endswith("bin/ffmpeg"))
            binary.name = binary_name()
            tf.extract(binary, DEST, filter="tar")  # "tar" keeps the +x bit
            license_member = next(
                (m for m in tf.getmembers() if m.name.endswith("LICENSE.txt")), None
            )
            if license_member:
                license_member.name = "LICENSE.txt"
                tf.extract(license_member, DEST, filter="tar")
    print(f"extracted ffmpeg to {target}")


if __name__ == "__main__":
    main()
