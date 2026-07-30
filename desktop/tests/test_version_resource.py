import ast
import tempfile
import unittest
from pathlib import Path

from scripts.version_resource import file_version, resource_text, write_resource


class VersionResourceTests(unittest.TestCase):
    def test_file_version_pads_to_four_parts(self):
        self.assertEqual(file_version("0.4.0"), (0, 4, 0, 0))
        self.assertEqual(file_version("12.7.30"), (12, 7, 30, 0))

    def test_file_version_rejects_malformed_versions(self):
        for bad in ("0.4", "0.4.0.1", "v0.4.0", "0.4.x"):
            with self.assertRaises(ValueError):
                file_version(bad)

    def test_resource_text_parses_as_a_python_literal(self):
        # PyInstaller eval()s this file, so a syntax error would only surface
        # during a real Windows build.
        ast.parse(resource_text("0.4.0", "Backchannel.exe", "Backchannel"))

    def test_resource_text_carries_product_name_and_version(self):
        text = resource_text("0.4.0", "Backchannel.exe", "Backchannel")
        self.assertIn("StringStruct('ProductName', 'Backchannel')", text)
        self.assertIn("StringStruct('ProductVersion', '0.4.0.0')", text)
        self.assertIn("StringStruct('OriginalFilename', 'Backchannel.exe')", text)
        self.assertIn("filevers=(0, 4, 0, 0)", text)

    def test_resource_text_is_ascii(self):
        resource_text("0.4.0", "Backchannel.exe", "Backchannel").encode("ascii")

    def test_write_resource_names_the_file_after_the_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            written = write_resource(
                directory, "0.4.0", "BackchannelUpdater.exe", "Backchannel Updater"
            )
            self.assertEqual(written.name, "BackchannelUpdater_version.txt")
            self.assertIn("Backchannel Updater", written.read_text(encoding="ascii"))

    def test_write_resource_matches_the_app_version(self):
        # Guards the single source of truth: the resource must track
        # release_notes.APP_VERSION, not a hardcoded copy.
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        from app.release_notes import APP_VERSION

        with tempfile.TemporaryDirectory() as directory:
            written = write_resource(
                directory, APP_VERSION, "Backchannel.exe", "Backchannel"
            )
            self.assertIn(
                f"StringStruct('ProductVersion', '{APP_VERSION}.0')",
                written.read_text(encoding="ascii"),
            )


if __name__ == "__main__":
    unittest.main()
