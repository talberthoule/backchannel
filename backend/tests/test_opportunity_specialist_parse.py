import unittest

from app.services.agents.opportunity_specialist import _parse_mappings


class ParseMappingsTests(unittest.TestCase):
    def test_bare_json_array(self):
        raw = '[{"id": "abc", "offering_match": "match"}]'
        self.assertEqual(_parse_mappings(raw), [{"id": "abc", "offering_match": "match"}])

    def test_fenced_json_array(self):
        raw = '```json\n[{"id": "abc", "offering_match": "match"}]\n```'
        self.assertEqual(_parse_mappings(raw), [{"id": "abc", "offering_match": "match"}])

    def test_garbage_with_embedded_array(self):
        raw = 'Here are the mappings: [{"id": "abc", "offering_match": "m"}] hope that helps!'
        self.assertEqual(_parse_mappings(raw), [{"id": "abc", "offering_match": "m"}])

    def test_empty_and_empty_array(self):
        self.assertEqual(_parse_mappings(""), [])
        self.assertEqual(_parse_mappings("[]"), [])
        self.assertEqual(_parse_mappings("```json\n[]\n```"), [])

    def test_unparseable_returns_none(self):
        self.assertIsNone(_parse_mappings("no json here"))
        self.assertIsNone(_parse_mappings("[ this is { not json ]"))

    def test_non_list_json_returns_empty(self):
        self.assertEqual(_parse_mappings('{"id": "abc"}'), [])


if __name__ == "__main__":
    unittest.main()
