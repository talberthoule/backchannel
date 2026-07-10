"""Download zonky.io embedded Postgres binaries for the current platform."""

import io
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

PG_VERSION = "16.4.0"
DEST = Path(__file__).resolve().parent.parent / "pgsql"


def artifact_platform() -> str:
    if sys.platform == "win32":
        return "windows-amd64"
    if sys.platform == "darwin":
        if platform.machine() == "arm64":
            return "darwin-arm64v8"
        return "darwin-amd64"
    return "linux-amd64"


def jar_url(plat: str) -> str:
    name = f"embedded-postgres-binaries-{plat}"
    return (
        "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
        f"{name}/{PG_VERSION}/{name}-{PG_VERSION}.jar"
    )


def main() -> None:
    if (DEST / "bin").exists():
        print(f"pgsql already present at {DEST}")
        return
    DEST.mkdir(parents=True, exist_ok=True)
    url = jar_url(artifact_platform())
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as resp:
        jar = io.BytesIO(resp.read())
    with zipfile.ZipFile(jar) as zf:
        txz_name = next(n for n in zf.namelist() if n.endswith(".txz"))
        txz = io.BytesIO(zf.read(txz_name))
    with tarfile.open(fileobj=txz, mode="r:xz") as tf:
        tf.extractall(DEST, filter="tar")  # "tar" keeps the +x bits binaries need
    print(f"extracted postgres to {DEST}")


if __name__ == "__main__":
    main()
