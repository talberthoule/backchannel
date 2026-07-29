import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.update_signing import (
    canonical_update_bytes,
    platform_signing_request,
    sign_platform_manifest,
)
from desktop.scripts.build_release_manifest import (
    ASSETS,
    build_platform_manifest,
    build_release_identity,
)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "desktop" / "scripts" / "build_platform_manifest.py"
TAG = "v1.2.3"
COMMIT = "a" * 40
PUBLISHED_AT = "2026-07-15T18:00:00Z"
PRIVATE = bytes(range(1, 33))


class PlatformReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def asset(self, platform_id, payload=b"bundle"):
        filename = next(value[2] for value in ASSETS if value[0] == platform_id)
        path = self.root / filename
        path.write_bytes(payload)
        return path

    def test_release_identity_is_exact_and_normalizes_utc(self):
        self.assertEqual(
            build_release_identity(TAG, COMMIT, "2026-07-15T18:00:00+00:00"),
            {"version": TAG, "published_at": PUBLISHED_AT, "commit": COMMIT},
        )

    def test_each_platform_uses_only_its_trusted_tuple(self):
        for platform_id, platform, filename, content_type in ASSETS:
            with self.subTest(platform_id=platform_id):
                payload = platform_id.encode()
                path = self.asset(platform_id, payload)
                self.assertEqual(
                    build_platform_manifest(path, TAG, COMMIT, platform_id),
                    {
                        "version": TAG,
                        "commit": COMMIT,
                        "asset": {
                            "id": platform_id,
                            "platform": platform,
                            "filename": filename,
                            "key": f"releases/{TAG}/{filename}",
                            "size": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "content_type": content_type,
                        },
                    },
                )

    def test_rejects_unknown_id_wrong_name_symlink_and_empty_file(self):
        path = self.asset("windows-x64")
        with self.assertRaisesRegex(ValueError, "platform"):
            build_platform_manifest(path, TAG, COMMIT, "unknown")
        wrong = self.root / "wrong.zip"
        wrong.write_bytes(b"bundle")
        with self.assertRaisesRegex(ValueError, "filename"):
            build_platform_manifest(wrong, TAG, COMMIT, "windows-x64")
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(ValueError, "symlink"):
                build_platform_manifest(path, TAG, COMMIT, "windows-x64")
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            build_platform_manifest(path, TAG, COMMIT, "windows-x64")

    def test_cli_writes_compact_deterministic_metadata(self):
        asset = self.asset("linux-x64", b"linux")
        release_out = self.root / "metadata" / "release.json"
        platform_out = self.root / "metadata" / "linux-x64.json"
        keys_file = self.root / "release_signing_keys.json"
        notes_file = self.root / "notes.md"
        notes_file.write_text("## Reliable updates\n\nSafer restarts.\n", encoding="utf-8")
        public = Ed25519PrivateKey.from_private_bytes(PRIVATE).public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        keys_file.write_text(
            json.dumps(
                {
                    "active": "test-key",
                    "keys": {
                        "test-key": base64.urlsafe_b64encode(public)
                        .rstrip(b"=")
                        .decode()
                    },
                }
            ),
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY": (
                base64.urlsafe_b64encode(PRIVATE).rstrip(b"=").decode()
            ),
        }
        result = subprocess.run(
            [
                sys.executable, str(CLI), "--asset", str(asset),
                "--platform-id", "linux-x64", "--tag", TAG,
                "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                "--keys-file", str(keys_file),
                "--release-notes-file", str(notes_file),
                "--release-out", str(release_out),
                "--platform-out", str(platform_out),
            ], cwd=ROOT, env=environment, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_release = json.dumps(
            build_release_identity(TAG, COMMIT, PUBLISHED_AT),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        unsigned_platform = {
            **build_platform_manifest(asset, TAG, COMMIT, "linux-x64"),
            "published_at": PUBLISHED_AT,
            "release_notes": notes_file.read_text(encoding="utf-8"),
        }
        expected_platform = json.dumps(
            sign_platform_manifest(unsigned_platform, "test-key", PRIVATE),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        self.assertEqual(release_out.read_bytes(), expected_release)
        self.assertEqual(platform_out.read_bytes(), expected_platform)
        self.assertNotIn(environment["BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"], result.stdout)
        self.assertNotIn(environment["BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"], result.stderr)

    def test_cli_requires_signing_secret_before_writing(self):
        asset = self.asset("windows-x64")
        result = subprocess.run(
            [
                sys.executable, str(CLI), "--asset", str(asset),
                "--platform-id", "windows-x64", "--tag", TAG,
                "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                "--keys-file", str(self.root / "missing.json"),
                "--release-notes-file", str(self.root / "missing.md"),
                "--release-out", str(self.root / "release.json"),
                "--platform-out", str(self.root / "platform.json"),
            ],
            cwd=ROOT,
            env={
                key: value
                for key, value in os.environ.items()
                if key != "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"
            },
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "release.json").exists())
        self.assertFalse((self.root / "platform.json").exists())

    def test_cli_writes_public_canonical_signing_request_only(self):
        asset = self.asset("linux-x64", b"linux")
        request_out = self.root / "request.bin"
        platform_out = self.root / "platform.json"
        keys_file, notes_file = self._signing_inputs()
        result = subprocess.run(
            [
                sys.executable, str(CLI), "--asset", str(asset),
                "--platform-id", "linux-x64", "--tag", TAG,
                "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                "--keys-file", str(keys_file),
                "--release-notes-file", str(notes_file),
                "--signing-request-out", str(request_out),
            ],
            cwd=ROOT,
            env={
                key: value for key, value in os.environ.items()
                if key != "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        unsigned = {
            **build_platform_manifest(asset, TAG, COMMIT, "linux-x64"),
            "published_at": PUBLISHED_AT,
            "release_notes": notes_file.read_text(encoding="utf-8"),
        }
        expected, _ = platform_signing_request(unsigned, "test-key")
        self.assertEqual(request_out.read_bytes(), canonical_update_bytes(expected))
        self.assertFalse(platform_out.exists())

    def test_cli_attaches_detached_signature_matching_local_output(self):
        asset = self.asset("linux-x64", b"linux")
        request_out = self.root / "request.bin"
        release_out = self.root / "release.json"
        platform_out = self.root / "platform.json"
        keys_file, notes_file = self._signing_inputs()
        base = [
            sys.executable, str(CLI), "--asset", str(asset),
            "--platform-id", "linux-x64", "--tag", TAG,
            "--commit", COMMIT, "--published-at", PUBLISHED_AT,
            "--keys-file", str(keys_file), "--release-notes-file", str(notes_file),
        ]
        request = subprocess.run(
            [*base, "--signing-request-out", str(request_out)],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(request.returncode, 0, request.stderr)
        signature = base64.urlsafe_b64encode(
            Ed25519PrivateKey.from_private_bytes(PRIVATE).sign(request_out.read_bytes())
        ).rstrip(b"=").decode("ascii")
        detached = subprocess.run(
            [
                *base, "--detached-key-id", "test-key",
                "--detached-signature", signature,
                "--release-out", str(release_out), "--platform-out", str(platform_out),
            ], cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(detached.returncode, 0, detached.stderr)
        expected_platform = self.root / "expected-platform.json"
        local = subprocess.run(
            [
                *base, "--release-out", str(self.root / "expected-release.json"),
                "--platform-out", str(expected_platform),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY": (
                    base64.urlsafe_b64encode(PRIVATE).rstrip(b"=").decode()
                ),
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(local.returncode, 0, local.stderr)
        self.assertEqual(platform_out.read_bytes(), expected_platform.read_bytes())

    def test_cli_rejects_invalid_detached_inputs_without_writing_outputs(self):
        asset = self.asset("linux-x64")
        keys_file, notes_file = self._signing_inputs()
        for label, options in (
            ("invalid signature", ["--detached-key-id", "test-key", "--detached-signature", "x" * 86]),
            ("missing signature", ["--detached-key-id", "test-key"]),
            ("wrong key", ["--detached-key-id", "other-key", "--detached-signature", "x" * 86]),
        ):
            with self.subTest(label=label):
                release_out = self.root / f"{label}-release.json"
                platform_out = self.root / f"{label}-platform.json"
                result = subprocess.run(
                    [
                        sys.executable, str(CLI), "--asset", str(asset),
                        "--platform-id", "linux-x64", "--tag", TAG,
                        "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                        "--keys-file", str(keys_file),
                        "--release-notes-file", str(notes_file), *options,
                        "--release-out", str(release_out),
                        "--platform-out", str(platform_out),
                    ], cwd=ROOT, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(release_out.exists())
                self.assertFalse(platform_out.exists())

    def _signing_inputs(self):
        keys_file = self.root / "release_signing_keys.json"
        notes_file = self.root / "notes.md"
        notes_file.write_text("Release notes", encoding="utf-8")
        public = Ed25519PrivateKey.from_private_bytes(PRIVATE).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        keys_file.write_text(json.dumps({"active": "test-key", "keys": {
            "test-key": base64.urlsafe_b64encode(public).rstrip(b"=").decode()
        }}), encoding="utf-8")
        return keys_file, notes_file


if __name__ == "__main__":
    unittest.main()
