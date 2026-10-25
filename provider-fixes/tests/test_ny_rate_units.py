# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""NY Fed decimal rates must select Workspace's scaling percentage formatter."""
import ast
import importlib.util
import json
from pathlib import Path
import unittest


class NewYorkRatePresentationTests(unittest.TestCase):
    def test_served_static_widgets_preserve_fractional_rate_units(self):
        spec = importlib.util.find_spec("openbb_federal_reserve")
        widgets = json.loads((Path(spec.origin).parent / "assets/regional/ny_widgets.json").read_text())
        count = 0
        for route in ("effr", "sofr", "overnight_bank_funding"):
            columns = widgets[f"ny_{route}_federal_reserve_obb"]["data"]["table"]["columnsDefs"]
            for column in columns:
                field = column["field"]
                if field == "rate" or field.startswith(("target_range_", "percentile_", "intraday_")):
                    count += 1
                    with self.subTest(route=route, field=field):
                        self.assertEqual(column.get("formatterFn"), "normalizedPercent")
                elif field == "standard_deviation":
                    self.assertEqual(column.get("formatterFn"), "percent")
                elif field == "volume":
                    self.assertEqual(column.get("formatterFn"), "none")
        self.assertEqual(count, 19)

    def test_fractional_rate_columns_use_normalized_percent(self):
        spec = importlib.util.find_spec("openbb_federal_reserve")
        source = Path(spec.origin).parent / "regional" / "new_york.py"
        tree = ast.parse(source.read_text())
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name not in {
                "effr", "sofr", "overnight_bank_funding"
            }:
                continue
            found.add(node.name)
            config = next(
                ast.literal_eval(kw.value)
                for dec in node.decorator_list if isinstance(dec, ast.Call)
                for kw in dec.keywords if kw.arg == "widget_config"
            )
            columns = config["data"]["table"]["columnsDefs"]
            expected = {"rate", "percentile_1", "percentile_25", "percentile_75", "percentile_99"}
            if node.name == "effr":
                expected |= {"target_range_upper", "target_range_lower", "intraday_low", "intraday_high"}
            actual = {
                c["field"] for c in columns
                if c["field"] == "rate" or c["field"].startswith(("target_range_", "percentile_", "intraday_"))
            }
            self.assertEqual(actual, expected)
            for column in columns:
                field = column["field"]
                if field == "rate" or field.startswith(("target_range_", "percentile_", "intraday_")):
                    with self.subTest(route=node.name, field=field):
                        self.assertEqual(column.get("formatterFn"), "normalizedPercent")
                elif field == "volume":
                    self.assertEqual(column.get("formatterFn"), "none")
                elif field == "standard_deviation":
                    # Unlike the intraday rates, the provider does not divide
                    # this field by 100 in normalize_percent.
                    self.assertEqual(column.get("formatterFn"), "percent")
        self.assertEqual(found, {"effr", "sofr", "overnight_bank_funding"})


if __name__ == "__main__":
    unittest.main()
