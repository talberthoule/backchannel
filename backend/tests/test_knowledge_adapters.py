import unittest
from types import SimpleNamespace

from app.services.knowledge.base import char_budget, truncate_to_budget
from app.services.knowledge.offerings_adapter import OfferingsAdapter, render_offerings
from app.services.knowledge.records_adapter import RecordsAdapter, render_records
from app.services.knowledge.registry import get_adapter


def _offering(**kwargs) -> SimpleNamespace:
    base = {
        "vendor": "",
        "product_name": "",
        "category": "",
        "subcategory": "",
        "description": "",
        "use_cases": "",
        "note": "",
        "tags": "",
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class RenderOfferingsTests(unittest.TestCase):
    def test_matches_legacy_catalog_format(self):
        offerings = [
            _offering(
                vendor="Cisco",
                product_name="Umbrella",
                category="Security",
                subcategory="DNS",
                description="Cloud-delivered DNS security.",
                use_cases="Web filtering.",
                note="Sold with deployment services.",
                tags="Security",
            ),
            _offering(
                vendor="Cisco",
                product_name="Duo",
                category="Security",
                description="MFA.",
            ),
            _offering(
                vendor="Zscaler",
                product_name="ZIA",
                category="Security",
                description="SSE platform.",
            ),
        ]

        expected = (
            "\n### Cisco\n"
            "- **Umbrella** [Security > DNS]: Cloud-delivered DNS security."
            " Use cases: Web filtering. Note: Sold with deployment services. Tags: Security\n"
            "- **Duo** [Security]: MFA.\n"
            "\n### Zscaler\n"
            "- **ZIA** [Security]: SSE platform."
        )
        self.assertEqual(render_offerings(offerings), expected)

    def test_empty_catalog_placeholder(self):
        self.assertEqual(render_offerings([]), "(No offerings in catalog)")


class RenderRecordsTests(unittest.TestCase):
    def test_records_render_as_titled_sections(self):
        records = [
            SimpleNamespace(title="Service A", body="Does A things."),
            SimpleNamespace(title="", body="Untitled body."),
            SimpleNamespace(title="Empty", body="   "),
        ]
        expected = "### Service A\nDoes A things.\n\nUntitled body."
        self.assertEqual(render_records(records), expected)

    def test_empty_records_render_empty(self):
        self.assertEqual(render_records([]), "")


class TruncateToBudgetTests(unittest.TestCase):
    def test_under_budget_untouched(self):
        self.assertEqual(truncate_to_budget("short", 100, "src"), "short")

    def test_truncates_at_last_newline_and_warns(self):
        text = "line one\nline two\nline three"
        with self.assertLogs("app.services.knowledge.base", level="WARNING"):
            result = truncate_to_budget(text, 15, "src")
        self.assertEqual(result, "line one")

    def test_truncates_hard_when_no_newline(self):
        with self.assertLogs("app.services.knowledge.base", level="WARNING"):
            result = truncate_to_budget("x" * 50, 10, "src")
        self.assertEqual(result, "x" * 10)


class CharBudgetTests(unittest.TestCase):
    def test_none_source_uses_settings_default(self):
        from app.config import settings

        self.assertEqual(char_budget(None), settings.KNOWLEDGE_CONTEXT_CHAR_BUDGET)

    def test_source_config_override(self):
        source = SimpleNamespace(name="s", config='{"char_budget": 1234}')
        self.assertEqual(char_budget(source), 1234)

    def test_invalid_config_falls_back(self):
        from app.config import settings

        source = SimpleNamespace(name="s", config="not json")
        self.assertEqual(char_budget(source), settings.KNOWLEDGE_CONTEXT_CHAR_BUDGET)


class RegistryTests(unittest.TestCase):
    def test_none_source_resolves_to_offerings_adapter(self):
        adapter = get_adapter(None)
        self.assertIsInstance(adapter, OfferingsAdapter)

    def test_collection_and_files_resolve_to_records_adapter(self):
        for source_type in ("collection", "files"):
            source = SimpleNamespace(name="s", source_type=source_type, id=None, config="{}")
            self.assertIsInstance(get_adapter(source), RecordsAdapter)

    def test_unknown_source_type_returns_none(self):
        source = SimpleNamespace(name="s", source_type="http_rag", id=None, config="{}")
        self.assertIsNone(get_adapter(source))


if __name__ == "__main__":
    unittest.main()
