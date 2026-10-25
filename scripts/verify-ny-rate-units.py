# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Check the catalogue actually served to Workspace, not just router source."""
import json
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1].rstrip("/") + "/widgets.json", timeout=90) as response:
    widgets = json.load(response)
checked = 0
for route in ("effr", "sofr", "overnight_bank_funding"):
    columns = widgets[f"ny_{route}_federal_reserve_obb"]["data"]["table"]["columnsDefs"]
    for column in columns:
        field = column["field"]
        if field == "rate" or field.startswith(("target_range_", "percentile_", "intraday_")):
            assert column.get("formatterFn") == "normalizedPercent", (route, field)
            checked += 1
        elif field == "standard_deviation":
            assert column.get("formatterFn") == "percent", (route, field)
assert checked == 19, checked
print(json.dumps({"status": "passed", "fractional_rate_columns": checked}))
