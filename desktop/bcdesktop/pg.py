"""Lifecycle management for the bundled zonky.io PostgreSQL binaries."""

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


class EmbeddedPostgres:
    def __init__(self, pg_dir: Path, data_dir: Path):
        self.root = Path(data_dir)
        self.bin = Path(pg_dir) / "bin"
        self.pgdata = Path(data_dir) / "pgdata"
        self.pwfile = Path(data_dir) / "pgpassword"
        self.log = Path(data_dir) / "postgres.log"
        self.pg_ctl_log = Path(data_dir) / "pg_ctl.log"

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

    def _grant_windows_acl(self) -> None:
        # ponytail: GH runners / admin users - postgres re-execs with a
        # restricted token (Administrators becomes deny-only), so the data
        # dir needs an explicit ACE for the plain user SID.
        if sys.platform != "win32":
            return
        user = os.environ.get("USERNAME")
        if not user:
            return
        subprocess.run(
            ["icacls", str(self.root), "/grant", f"{user}:(OI)(CI)F", "/T", "/Q"],
            capture_output=True,
        )

    def ensure_initdb(self) -> None:
        if (self.pgdata / "PG_VERSION").exists():
            return
        if self.pgdata.exists():
            # A pgdata dir without PG_VERSION was never a valid cluster
            # (e.g. initdb crashed or was killed mid-run). initdb refuses
            # to write into a non-empty directory, so clear it first.
            shutil.rmtree(self.pgdata)
        self.password()
        self._grant_windows_acl()
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
        # No pipes for stdin/stdout: the detached postmaster inherits them
        # and subprocess.run would block forever waiting for EOF. Server
        # output goes to self.log via -l anyway. pg_ctl's own stderr (its
        # exit diagnostics, not the postmaster's) goes to a real file
        # instead of DEVNULL so start failures are debuggable; a file
        # handle doesn't block on child inheritance either.
        with open(self.pg_ctl_log, "w") as err:
            proc = subprocess.run(
                [
                    str(self.bin / "pg_ctl"),
                    "-D", str(self.pgdata),
                    "-o", f"-p {port} -c listen_addresses=127.0.0.1",
                    "-l", str(self.log),
                    "-w",
                    "start",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
            )
        if proc.returncode != 0:
            tail = ""
            try:
                lines = self.pg_ctl_log.read_text(errors="replace").splitlines()
                tail = "\n".join(lines[-20:])
            except OSError:
                pass
            raise RuntimeError(
                f"pg_ctl start failed (exit {proc.returncode}): {tail}"
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
