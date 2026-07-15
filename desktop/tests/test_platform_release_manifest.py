import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        result = subprocess.run(
            [
                sys.executable, str(CLI), "--asset", str(asset),
                "--platform-id", "linux-x64", "--tag", TAG,
                "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                "--release-out", str(release_out),
                "--platform-out", str(platform_out),
            ], cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_release = json.dumps(
            build_release_identity(TAG, COMMIT, PUBLISHED_AT),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        expected_platform = json.dumps(
            build_platform_manifest(asset, TAG, COMMIT, "linux-x64"),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        self.assertEqual(release_out.read_bytes(), expected_release)
        self.assertEqual(platform_out.read_bytes(), expected_platform)


if __name__ == "__main__":
    unittest.main()
