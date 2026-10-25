# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""EIA widgets whose unfiltered default exceeds the pagination ceiling open on the newest page."""
import unittest

NEWEST_PAGE = {
    f"eia_{name}_eia_obb"
    for name in (
        "aeo",
        "electricity_electric_power_operations",
        "electricity_electric_power_operations_for_individual_power_plants",
        "electricity_grid_demand_by_subregion",
        "electricity_grid_demand",
        "electricity_grid_generation_by_fuel",
        "electricity_grid_interchange",
        "electricity_inventory_of_operable_generators",
        "ieo",
        "international",
        "nuclear_outages_facility_level_nuclear_outages",
        "nuclear_outages_generator_level_nuclear_outages",
        "petroleum_consumption_sales_prime_supplier_sales_volumes",
        "petroleum_consumption_sales_refiner_motor_gasoline_sales_volumes",
        "petroleum_consumption_sales_refiner_sales_volumes_of_other_petroleum_products",
        "petroleum_imports_exports_and_movements_exports_by_destination",
        "petroleum_imports_exports_and_movements_pad_district_exports_by_destination",
        "petroleum_imports_exports_and_movements_pad_district_imports_by_country_of_origin",
        "petroleum_prices_gasoline_prices_by_formulation_grade_sales_type",
        "petroleum_refining_and_processing_refinery_blender_net_production",
        "petroleum_stocks_stocks_by_type",
        "petroleum_summary_prices_sales_volumes_stocks_by_state",
        "petroleum_summary_supply_and_disposition",
        "petroleum_summary_weekly_supply_estimates",
        "seds",
    )
}


def setUpModule():
    global OPENAPI, WIDGETS
    from openbb_core.api.rest_api import app
    from openbb_platform_api.utils.widgets import build_json

    OPENAPI = app.openapi()
    WIDGETS = build_json(OPENAPI, [])


def params(widget_id):
    return {p["paramName"]: p for p in WIDGETS[widget_id]["params"]}


class EiaNewestPageTest(unittest.TestCase):
    def test_listed_widgets_default_to_newest_5000_rows(self):
        self.assertEqual(len(NEWEST_PAGE), 25)
        for widget_id in sorted(NEWEST_PAGE):
            with self.subTest(widget_id):
                p = params(widget_id)
                self.assertEqual(p["limit"]["value"], 5000)
                self.assertEqual(p["sort"]["value"], "desc")

    def test_other_eia_widgets_keep_their_defaults(self):
        others = [w for w in WIDGETS if w.startswith("eia_") and w not in NEWEST_PAGE]
        self.assertEqual(len(others), 194)
        for widget_id in others:
            with self.subTest(widget_id):
                p = params(widget_id)
                self.assertNotIn("sort", p)
                self.assertNotEqual(p.get("limit", {}).get("value"), 5000)

    def test_api_defaults_unchanged(self):
        from openbb_us_eia.models.aeo import EiaAeoQueryParams

        query = EiaAeoQueryParams()
        self.assertIsNone(query.limit)
        self.assertEqual(query.sort, "asc")
        api = {
            p["name"]: p["schema"].get("default")
            for p in OPENAPI["paths"]["/api/v1/eia/aeo"]["get"]["parameters"]
        }
        self.assertIsNone(api["limit"])
        self.assertEqual(api["sort"], "asc")


if __name__ == "__main__":
    unittest.main()
