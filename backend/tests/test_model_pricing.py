import re
import unittest

from app.config import MODEL_REGISTRY
from app.routers.models import ModelPricing as ModelPricingSchema, get_model_pricing
from app.services.model_pricing import MODEL_PRICING, PRICING_AS_OF, pricing_for

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RATE_FIELDS = (
    "input_per_million",
    "output_per_million",
    "cached_input_per_million",
    "audio_input_per_million",
    "per_minute",
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
        """Rates are non-negative floats where present.

        Token rates were required to be floats until ALP-300 added duration
        billing: gpt-live-transcribe publishes only a per-minute rate, and
        forcing 0.0 token rates on it would have priced any token-shaped
        payload from that model as free. They may now be None, but a row that
        is priced at all has to be priced somehow - see the companion test.
        """
        for model_id, pricing in MODEL_PRICING.items():
            if pricing is None:
                continue
            self.assertEqual(set(pricing), set(RATE_FIELDS), model_id)
            for field in RATE_FIELDS:
                if pricing[field] is None:
                    continue
                self.assertIsInstance(pricing[field], float, f"{model_id}.{field}")
                self.assertGreaterEqual(pricing[field], 0.0, f"{model_id}.{field}")

    def test_a_priced_row_carries_at_least_one_usable_rate(self):
        # Guards the hole the previous test left when token rates became
        # optional: an all-None dict is indistinguishable from unpriced, and
        # would render as "-" while claiming to be priced.
        for model_id, pricing in MODEL_PRICING.items():
            if pricing is None:
                continue
            token_priced = (
                pricing["input_per_million"] is not None
                and pricing["output_per_million"] is not None
            )
            self.assertTrue(
                token_priced or pricing["per_minute"] is not None,
                f"{model_id} has a pricing dict with no usable rate; use None instead",
            )

    def test_duration_billed_models_price_per_minute_only(self):
        pricing = pricing_for("gpt-live-transcribe")
        self.assertIsNotNone(pricing)
        self.assertEqual(0.017, pricing["per_minute"])
        self.assertIsNone(pricing["input_per_million"])
        self.assertIsNone(pricing["output_per_million"])

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

    def test_response_schema_preserves_every_published_rate(self):
        """A rate the response schema does not name is dropped in transit.

        get_model_pricing returns the raw table, so calling it directly can
        never catch this; the loss happens when FastAPI serializes through
        response_model. per_minute was added to the table and reached the
        endpoint as null for exactly this reason (ALP-300), so the round trip
        is asserted through the schema itself.
        """
        for model_id, rates in MODEL_PRICING.items():
            if rates is None:
                continue
            self.assertEqual(rates, ModelPricingSchema(**rates).model_dump(), model_id)


if __name__ == "__main__":
    unittest.main()
