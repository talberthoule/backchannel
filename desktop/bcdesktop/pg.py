"""Lifecycle management for the bundled zonky.io PostgreSQL binaries."""

import os
import secrets
import subprocess
from pathlib import Path


class EmbeddedPostgres:
    def __init__(self, pg_dir: Path, data_dir: Path):
        self.bin = Path(pg_dir) / "bin"
        self.pgdata = Path(data_dir) / "pgdata"
        self.pwfile = Path(data_dir) / "pgpassword"
        self.log = Path(data_dir) / "postgres.log"

    def password(self) -> str:
        if not self.pwfile.exists():
            self.pwfile.parent.mkdir(parents=True, exist_ok=True)
            self.pwfile.write_text(secrets.token_hex(16))
            os.chmod(self.pwfile, 0o600)
        return self.pwfile.read_text().strip()

    def _run(self, cmd: list) -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            raise RuntimeError(
                f"{cmd[0]} failed (exit {proc.returncode}): {detail}"
            )

    def ensure_initdb(self) -> None:
        if (self.pgdata / "PG_VERSION").exists():
            return
        self.password()
        self._run([
            str(self.bin / "initdb"),
            "-D", str(self.pgdata),
            "-U", "backchannel",
            "-A", "scram-sha-256",
            "--pwfile", str(self.pwfile),
            "--no-locale",
            "-E", "UTF8",
        ])

    def recover_stale(self) -> None:
        # A postmaster.pid left by a crash blocks the next start. pg_ctl
        # status exits non-zero when no server is actually running.
        pidfile = self.pgdata / "postmaster.pid"
        if not pidfile.exists():
            return
        status = subprocess.run(
            [str(self.bin / "pg_ctl"), "-D", str(self.pgdata), "status"],
            capture_output=True,
        )
        if status.returncode != 0:
            pidfile.unlink()

    def start(self, port: int) -> None:
        # No pipes here: the detached postmaster inherits them and
        # subprocess.run would block forever waiting for EOF. Server
        # output goes to self.log via -l anyway.
        subprocess.run(
            [
                str(self.bin / "pg_ctl"),
                "-D", str(self.pgdata),
                "-o", f"-p {port} -c listen_addresses=127.0.0.1",
                "-l", str(self.log),
                "-w",
                "start",
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if not (self.pgdata / "postmaster.pid").exists():
            return
        self._run([
            str(self.bin / "pg_ctl"),
            "-D", str(self.pgdata),
            "-m", "fast",
            "-w",
            "stop",
        ])

    def database_url(self, port: int) -> str:
        # token_hex passwords are URL-safe by construction.
        return (
            f"postgresql+asyncpg://backchannel:{self.password()}"
            f"@127.0.0.1:{port}/postgres"
        )
