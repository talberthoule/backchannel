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


def wait_for_health(
    proc: subprocess.Popen, lock: Path, deadline: float
) -> int | None:
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return None
        try:
            instance = json.loads(lock.read_text())
            port = instance["port"]
            token = instance["token"]
            url = f"http://127.0.0.1:{port}/api/health"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
                if (
                    resp.status == 200
                    and "ok" in body
                    and resp.headers.get("X-Backchannel-Instance") == token
                ):
                    return port
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(1)
    return None


def stop_process(proc: subprocess.Popen, stop: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            return False
        stop.touch()
        try:
            proc.wait(timeout=1)
            return True
        except subprocess.TimeoutExpired:
            pass
    return True


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(
            os.environ, BACKCHANNEL_HEADLESS="1", BACKCHANNEL_DATA_DIR=tmp
        )
        proc = subprocess.Popen([str(bundle_exe())], env=env)
        lock = Path(tmp) / "launcher.json"
        try:
            deadline = time.monotonic() + 300  # first run does initdb
            port = wait_for_health(proc, lock, deadline)
            if port is None:
                if proc.poll() is not None:
                    print(
                        f"FAIL: launcher exited early (exit code {proc.returncode})",
                        file=sys.stderr,
                    )
                else:
                    print("FAIL: timed out waiting for health", file=sys.stderr)
                dump_logs(Path(tmp))
                return 1
            print(f"OK: healthy on port {port}")
        finally:
            if not stop_process(proc, Path(tmp) / "stop", timeout=90):
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
