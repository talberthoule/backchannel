import re
import unittest

from app.config import MODEL_REGISTRY
from app.routers.models import get_model_pricing
from app.services.model_pricing import MODEL_PRICING, PRICING_AS_OF, pricing_for

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RATE_FIELDS = (
    "input_per_million",
    "output_per_million",
    "cached_input_per_million",
    "audio_input_per_million",
)


class ModelPricingTableTests(unittest.TestCase):
    def test_every_registry_model_has_a_pricing_row(self):
        # Drift guard: adding a model to MODEL_REGISTRY without deciding its
        # pricing (a rate dict, or an explicit None for "unpriced") fails here.
        registry_ids = {model["id"] for model in MODEL_REGISTRY}
        missing = registry_ids - set(MODEL_PRICING)
        self.assertEqual(missing, set(), f"registry models missing pricing rows: {sorted(missing)}")

    def test_no_stale_pricing_rows(self):
        # Removing a model from the registry must also remove its pricing row.
        registry_ids = {model["id"] for model in MODEL_REGISTRY}
        stale = set(MODEL_PRICING) - registry_ids
        self.assertEqual(stale, set(), f"pricing rows for models not in the registry: {sorted(stale)}")

    def test_priced_rows_have_sane_rates(self):
        for model_id, pricing in MODEL_PRICING.items():
            if pricing is None:
                continue
            self.assertEqual(set(pricing), set(RATE_FIELDS), model_id)
            for field in ("input_per_million", "output_per_million"):
                self.assertIsInstance(pricing[field], float, f"{model_id}.{field}")
                self.assertGreaterEqual(pricing[field], 0.0, f"{model_id}.{field}")
            for field in ("cached_input_per_million", "audio_input_per_million"):
                if pricing[field] is not None:
                    self.assertGreaterEqual(pricing[field], 0.0, f"{model_id}.{field}")

    def test_local_models_are_free(self):
        for model in MODEL_REGISTRY:
            if model["provider"] != "Local":
                continue
            pricing = pricing_for(model["id"])
            self.assertIsNotNone(pricing, model["id"])
            self.assertEqual(pricing["input_per_million"], 0.0, model["id"])
            self.assertEqual(pricing["output_per_million"], 0.0, model["id"])

    def test_as_of_is_iso_date(self):
        self.assertRegex(PRICING_AS_OF, ISO_DATE)

    def test_pricing_for_unknown_model_is_none(self):
        self.assertIsNone(pricing_for("no-such-model"))


class ModelPricingEndpointTests(unittest.TestCase):
    def test_endpoint_returns_as_of_date_and_full_map(self):
        response = get_model_pricing()
        self.assertEqual(response["as_of"], PRICING_AS_OF)
        self.assertEqual(response["models"], MODEL_PRICING)
        for model in MODEL_REGISTRY:
            self.assertIn(model["id"], response["models"])


if __name__ == "__main__":
    unittest.main()
