import json
import unittest

from app.routers.knowledge import normalize_record_import_row


class NormalizeRecordImportRowTests(unittest.TestCase):
    def test_basic_title_body(self):
        row = {"title": "Service A", "body": "Does A things."}
        normalized = normalize_record_import_row(row)
        self.assertEqual(normalized["title"], "Service A")
        self.assertEqual(normalized["body"], "Does A things.")
        self.assertEqual(normalized["meta"], "{}")

    def test_header_case_and_spaces_normalized(self):
        row = {"Title": "  A  ", " Body ": "b"}
        normalized = normalize_record_import_row(row)
        self.assertEqual(normalized["title"], "A")
        self.assertEqual(normalized["body"], "b")

    def test_extra_columns_go_to_meta(self):
        row = {"title": "A", "body": "b", "Category": "Security", "vendor": "Cisco", "empty": ""}
        normalized = normalize_record_import_row(row)
        meta = json.loads(normalized["meta"])
        self.assertEqual(meta, {"category": "Security", "vendor": "Cisco"})

    def test_missing_fields_default_empty(self):
        normalized = normalize_record_import_row({"category": "x"})
        self.assertEqual(normalized["title"], "")
        self.assertEqual(normalized["body"], "")

    def test_none_values_treated_as_empty(self):
        normalized = normalize_record_import_row({"title": None, "body": "b", "note": None})
        self.assertEqual(normalized["title"], "")
        self.assertEqual(json.loads(normalized["meta"]), {})


if __name__ == "__main__":
    unittest.main()
