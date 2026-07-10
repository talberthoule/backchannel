"""Smoke test the built desktop bundle: start headless, hit health, stop."""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def dump_logs(data_dir: Path) -> None:
    for name in ("backchannel.log", "postgres.log"):
        log = data_dir / name
        if log.exists():
            print(f"----- tail of {name} -----", file=sys.stderr)
            print(
                "\n".join(log.read_text(errors="replace").splitlines()[-50:]),
                file=sys.stderr,
            )
        else:
            print(f"----- {name} missing -----", file=sys.stderr)


def bundle_exe() -> Path:
    exe = Path("dist") / "Backchannel" / "Backchannel"
    if sys.platform == "win32":
        exe = exe.with_suffix(".exe")
    if not exe.exists():
        raise SystemExit(f"bundle not found: {exe}")
    return exe


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(
            os.environ, BACKCHANNEL_HEADLESS="1", BACKCHANNEL_DATA_DIR=tmp
        )
        proc = subprocess.Popen([str(bundle_exe())], env=env)
        lock = Path(tmp) / "launcher.json"
        try:
            deadline = time.monotonic() + 300  # first run does initdb
            port = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    print(
                        f"FAIL: launcher exited early (exit code {proc.returncode})",
                        file=sys.stderr,
                    )
                    dump_logs(Path(tmp))
                    return 1
                if lock.exists():
                    port = json.loads(lock.read_text())["port"]
                    break
                time.sleep(1)
            if port is None:
                print("FAIL: timed out waiting for launcher.json", file=sys.stderr)
                dump_logs(Path(tmp))
                return 1
            url = f"http://127.0.0.1:{port}/api/health"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
            if resp.status != 200 or "ok" not in body:
                print(f"FAIL: bad health response: {body}", file=sys.stderr)
                dump_logs(Path(tmp))
                return 1
            print(f"OK: healthy on port {port}")
        finally:
            (Path(tmp) / "stop").touch()
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                print("FAIL: launcher did not shut down cleanly", file=sys.stderr)
                dump_logs(Path(tmp))
                return 1
        if proc.returncode != 0:
            print(f"FAIL: exit code {proc.returncode}", file=sys.stderr)
            dump_logs(Path(tmp))
            return 1
        print("OK: clean shutdown")
        return 0


if __name__ == "__main__":
    sys.exit(main())
