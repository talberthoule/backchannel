import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.routers.offerings import _normalize_offering_import_row


class OfferingsImportMappingTests(unittest.TestCase):
    def test_maps_current_columns(self):
        row = _normalize_offering_import_row({
            "vendor": "Acme Networks",
            "product_name": "Acme Cloud Firewall",
            "category": "Security",
            "subcategory": "Network Security",
            "description": "Cloud-managed firewall.",
            "use_cases": "Perimeter security",
            "note": "Sold with deployment services.",
            "tags": "Networking, Managed Service",
        })

        self.assertEqual("Acme Networks", row["vendor"])
        self.assertEqual("Network Security", row["subcategory"])
        self.assertEqual("Sold with deployment services.", row["note"])
        self.assertEqual("Networking, Managed Service", row["tags"])

    def test_legacy_columns_map_to_new_fields(self):
        row = _normalize_offering_import_row({
            "vendor": "Acme Networks",
            "product_name": "Acme Cloud Firewall",
            "category": "Security",
            "discipline": "Network Security",
            "delivery_model": "Managed Service",
            "practice": "Security",
        })

        self.assertEqual("Network Security", row["subcategory"])
        self.assertEqual("Managed Service", row["note"])
        self.assertEqual("Security", row["tags"])

    def test_explicit_subcategory_wins_over_legacy_discipline(self):
        row = _normalize_offering_import_row({
            "vendor": "Acme Networks",
            "product_name": "Acme Cloud Firewall",
            "category": "Security",
            "subcategory": "Cloud Security",
            "discipline": "Network Security",
        })

        self.assertEqual("Cloud Security", row["subcategory"])

    def test_missing_vendor_defaults_to_service_integrator(self):
        row = _normalize_offering_import_row({"product_name": "Advisory Retainer"})
        self.assertEqual("Service Integrator", row["vendor"])


if __name__ == "__main__":
    unittest.main()
