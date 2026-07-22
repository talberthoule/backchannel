import re
import unittest

from app.release_notes import APP_VERSION, RELEASE_NOTES
from app.routers.meta import get_meta, list_release_notes

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReleaseNotesDataTests(unittest.TestCase):
    def test_app_version_matches_newest_note(self):
        self.assertEqual(RELEASE_NOTES[0]["version"], APP_VERSION)

    def test_versions_are_semver_unique_and_newest_first(self):
        versions = [note["version"] for note in RELEASE_NOTES]
        for version in versions:
            self.assertRegex(version, SEMVER)
        self.assertEqual(len(set(versions)), len(versions))
        numeric = [tuple(int(p) for p in v.split(".")) for v in versions]
        self.assertEqual(numeric, sorted(numeric, reverse=True))

    def test_notes_have_required_fields(self):
        for note in RELEASE_NOTES:
            self.assertRegex(note["date"], ISO_DATE)
            self.assertTrue(note["title"].strip())
            self.assertTrue(note["body"].strip())

    def test_notes_are_ascii(self):
        # Repo convention: new content stays ASCII (see CLAUDE.md).
        for note in RELEASE_NOTES:
            note["title"].encode("ascii")
            note["body"].encode("ascii")


class MetaEndpointTests(unittest.TestCase):
    def test_meta_returns_app_version(self):
        self.assertEqual(get_meta(), {"version": APP_VERSION})

    def test_release_notes_endpoint_returns_all_notes(self):
        self.assertEqual(list_release_notes(), RELEASE_NOTES)


if __name__ == "__main__":
    unittest.main()
