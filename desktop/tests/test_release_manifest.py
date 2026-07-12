import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from desktop.scripts.build_release_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "desktop" / "scripts" / "build_release_manifest.py"
TAG = "v1.2.3"
COMMIT = "a" * 40
PUBLISHED_AT = "2026-07-12T18:00:00Z"
ASSETS = (
    ("windows-x64", "Windows x64", "Backchannel-windows-x64.zip", "application/zip"),
    ("macos-arm64", "macOS arm64", "Backchannel-macos-arm64.zip", "application/zip"),
    ("linux-x64", "Linux x64", "Backchannel-linux-x64.tar.gz", "application/gzip"),
)


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.asset_dir = self.root / "assets"
        self.asset_dir.mkdir()
        self.metadata_dir = self.root / "metadata"
        self.payloads = {}
        for index, (_, _, filename, _) in enumerate(ASSETS, start=1):
            payload = bytes([index]) * index
            (self.asset_dir / filename).write_bytes(payload)
            self.payloads[filename] = payload

    def manifest(self, **overrides):
        arguments = {
            "asset_dir": self.asset_dir,
            "tag": TAG,
            "commit": COMMIT,
            "published_at": PUBLISHED_AT,
        }
        arguments.update(overrides)
        return build_manifest(**arguments)

    def run_cli(
        self, *, tag=TAG, current_latest=None, manifest_out=None, latest_out=None
    ):
        manifest_out = manifest_out or self.metadata_dir / "manifest.json"
        latest_out = latest_out or self.metadata_dir / "latest.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "--asset-dir",
            str(self.asset_dir),
            "--tag",
            tag,
            "--commit",
            COMMIT,
            "--published-at",
            "2026-07-12T18:00:00+00:00",
            "--manifest-out",
            str(manifest_out),
            "--latest-out",
            str(latest_out),
        ]
        if current_latest is not None:
            command.extend(("--current-latest", str(current_latest)))
        return subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True
        )

    def test_exact_three_assets_have_deterministic_fields_and_order(self):
        manifest = self.manifest()

        self.assertEqual(
            list(manifest), ["version", "published_at", "commit", "assets"]
        )
        self.assertEqual(manifest["version"], TAG)
        self.assertEqual(manifest["published_at"], PUBLISHED_AT)
        self.assertEqual(manifest["commit"], COMMIT)
        self.assertEqual(
            [asset["id"] for asset in manifest["assets"]],
            [asset[0] for asset in ASSETS],
        )
        for actual, (asset_id, platform, filename, content_type) in zip(
            manifest["assets"], ASSETS
        ):
            payload = self.payloads[filename]
            self.assertEqual(
                actual,
                {
                    "id": asset_id,
                    "platform": platform,
                    "filename": filename,
                    "key": f"releases/{TAG}/{filename}",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "content_type": content_type,
                },
            )

    def test_hashes_large_asset_and_records_positive_size(self):
        filename = ASSETS[0][2]
        payload = b"a" * (1024 * 1024) + b"tail"
        (self.asset_dir / filename).write_bytes(payload)

        asset = self.manifest()["assets"][0]

        self.assertEqual(asset["size"], len(payload))
        self.assertEqual(asset["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertIn("1024 * 1024", SCRIPT.read_text(encoding="utf-8"))

    def test_rejects_missing_extra_symlink_and_empty_assets(self):
        missing = self.asset_dir / ASSETS[0][2]
        missing.unlink()
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.manifest()

        missing.write_bytes(b"restored")
        (self.asset_dir / "extra.txt").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.manifest()

        (self.asset_dir / "extra.txt").unlink()
        target = self.asset_dir / ASSETS[0][2]
        target.unlink()
        target.symlink_to(self.asset_dir / ASSETS[1][2])
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.manifest()

        target.unlink()
        target.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.manifest()

    def test_rejects_invalid_tag_commit_and_timestamp(self):
        invalid = (
            ({"tag": "1.2.3"}, "tag"),
            ({"tag": "v01.2.3"}, "tag"),
            ({"tag": "v1.02.3"}, "tag"),
            ({"commit": "A" * 40}, "commit"),
            ({"commit": "a" * 39}, "commit"),
            ({"published_at": "2026-07-12T18:00:00-05:00"}, "UTC"),
            ({"published_at": "2026-02-30T18:00:00Z"}, "timestamp"),
        )
        for arguments, message in invalid:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, message):
                    self.manifest(**arguments)

    def test_normalizes_explicit_utc_offset_to_z(self):
        manifest = self.manifest(published_at="2026-07-12T18:00:00+00:00")
        self.assertEqual(manifest["published_at"], PUBLISHED_AT)

    def test_legacy_mode_accepts_only_exact_windows_macos_pair(self):
        (self.asset_dir / ASSETS[2][2]).unlink()
        manifest = self.manifest(allow_legacy_partial=True)
        self.assertEqual(
            [asset["id"] for asset in manifest["assets"]],
            ["windows-x64", "macos-arm64"],
        )

        (self.asset_dir / ASSETS[1][2]).unlink()
        with self.assertRaisesRegex(ValueError, "legacy"):
            self.manifest(allow_legacy_partial=True)

        (self.asset_dir / ASSETS[1][2]).write_bytes(b"mac")
        (self.asset_dir / "unexpected.zip").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "legacy"):
            self.manifest(allow_legacy_partial=True)

    def test_current_latest_rejects_regression_but_allows_equality(self):
        current = self.root / "current-latest.json"
        current.write_text('{"version":"v1.10.0"}\n', encoding="utf-8")
        result = self.run_cli(current_latest=current)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("regress Latest", result.stderr)

        current.write_text('{"version":"v1.2.3"}\n', encoding="utf-8")
        result = self.run_cli(tag="v1.10.0", current_latest=current)
        self.assertEqual(result.returncode, 0, result.stderr)

        current.write_text('{"version":"v1.2.3"}\n', encoding="utf-8")
        result = self.run_cli(current_latest=current)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_current_latest_must_be_strict_one_field_json(self):
        current = self.root / "current-latest.json"
        malformed = (
            "not-json",
            "[]",
            '{"version":"1.2.3"}',
            '{"version":"v01.2.3"}',
            '{"version":"v1.2.3","extra":true}',
        )
        for value in malformed:
            with self.subTest(value=value):
                current.write_text(value, encoding="utf-8")
                result = self.run_cli(current_latest=current)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Latest", result.stderr)

    def test_cli_writes_exact_compact_sorted_json_bytes(self):
        manifest_out = self.metadata_dir / "manifest.json"
        latest_out = self.metadata_dir / "latest.json"
        result = self.run_cli(manifest_out=manifest_out, latest_out=latest_out)

        self.assertEqual(result.returncode, 0, result.stderr)
        expected = json.dumps(
            self.manifest(), sort_keys=True, separators=(",", ":")
        ).encode() + b"\n"
        self.assertEqual(manifest_out.read_bytes(), expected)
        self.assertEqual(latest_out.read_bytes(), b'{"version":"v1.2.3"}\n')

    def test_cli_failure_leaves_no_partial_outputs(self):
        (self.asset_dir / ASSETS[2][2]).unlink()
        manifest_out = self.metadata_dir / "manifest.json"
        latest_out = self.metadata_dir / "latest.json"

        result = self.run_cli(manifest_out=manifest_out, latest_out=latest_out)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(manifest_out.exists())
        self.assertFalse(latest_out.exists())


if __name__ == "__main__":
    unittest.main()
