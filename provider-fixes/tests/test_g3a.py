# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""G3 code defects: SEC institutions search, Dallas Fed sheets, USDA ERS members and years."""
import asyncio
import io
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

FIXTURES = Path(__file__).parent / "fixtures"


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buffer.getvalue()


class SecInstitutionsSearchTest(unittest.TestCase):
    # A blank search would return every SEC filer (about 1.06 million rows), so it
    # asks for a name instead, and the widget prompts for one.
    def test_blank_query_asks_for_a_name(self):
        from openbb_core.app.model.abstract.error import OpenBBError
        from pandas import DataFrame

        from openbb_sec.models.institutions_search import (
            SecInstitutionsSearchFetcher,
            SecInstitutionsSearchQueryParams,
        )

        frame = DataFrame({"Institution": ["Alpha Bank", "Beta Trust"], "CIK Number": [1, 2]})

        async def get_all_ciks(use_cache=True):
            return frame

        with mock.patch("openbb_sec.utils.helpers.get_all_ciks", get_all_ciks):
            for blank in (None, ""):
                with self.assertRaises(OpenBBError):
                    asyncio.run(SecInstitutionsSearchFetcher.aextract_data(
                        SecInstitutionsSearchQueryParams(query=blank), None))
            query = SecInstitutionsSearchQueryParams(query="beta")
            rows = asyncio.run(SecInstitutionsSearchFetcher.aextract_data(query, None))
            self.assertEqual([r["Institution"] for r in rows], ["Beta Trust"])

    def test_widget_prompts_for_query(self):
        from openbb_core.api.rest_api import app
        from openbb_platform_api.utils.widgets import build_json

        params = build_json(app.openapi(), [])["sec_institutions_search_sec_obb"]["params"]
        query = next(p for p in params if p["paramName"] == "query")
        self.assertIs(query["optional"], False)


class DallasSheetTest(unittest.TestCase):
    def test_banking_conditions_reads_renamed_sheet(self):
        from openbb_federal_reserve.models.regional.dallas_bcs import (
            FederalReserveDallasBankingFetcher,
            FederalReserveDallasBankingQueryParams,
        )

        raw = (FIXTURES / "dallas_bcs.xlsx").read_bytes()
        rows = FederalReserveDallasBankingFetcher.transform_data(
            FederalReserveDallasBankingQueryParams(), [{"_raw": raw}]
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].date, date(2017, 3, 1))
        self.assertEqual(rows[0].model_dump()["Total Loan Volume (current)"], 31.4)

    def test_igrea_reads_renamed_sheet(self):
        from openbb_federal_reserve.models.regional.dallas_igrea import (
            FederalReserveDallasIgreaFetcher,
            FederalReserveDallasIgreaQueryParams,
        )

        raw = (FIXTURES / "dallas_igrea.xlsx").read_bytes()
        rows = FederalReserveDallasIgreaFetcher.transform_data(
            FederalReserveDallasIgreaQueryParams(), [{"_raw": raw}]
        )
        self.assertEqual([r.date for r in rows], [date(1968, m, 1) for m in (1, 2, 3)])
        self.assertAlmostEqual(rows[0].value, -12.055511)


class UsdaArchiveMemberTest(unittest.TestCase):
    def test_vegetables_and_pulses_reads_renamed_member(self):
        from openbb_government_us.usda.utils import ers_vegetables_and_pulses as ers

        text = (
            "Table,Decade,Year,Item,Commodity,EndUse,PublishValue,Unit,Category,GeographicalLevel,Location\n"
            "Table33_Potatoes,1970s,1970,Total supply,Potatoes,Fresh,12984.324,Million pounds,Supply,Country,United States\n"
        )
        content = _zip({"vegetables-pulses-data.csv": text})

        async def fetch(*args, **kwargs):
            return content

        with mock.patch("openbb_government_us.usda.utils.ers_client.afetch_ers_file", fetch):
            rows = asyncio.run(ers.afetch_table("Table33_Potatoes"))
        self.assertEqual([(r["year"], r["value"]) for r in rows], [(1970, 12984.324)])

    def test_livestock_and_meat_reads_renamed_members(self):
        from openbb_government_us.usda.utils import ers_livestock_and_meat_domestic_data as ers

        folder = "livestock-data-machine-readable-files/"
        content = _zip(
            {
                folder + "Meat-Supply-Disappearance.csv": (
                    '"commodity_desc","attribute_desc","unit_desc","year_id","timeperiod_id","timeperiod_desc","amount"\n'
                    '"Beef","Commercial Production","Million pounds",1989,13,"Q1 Jan-Mar",5530\n'
                ),
                folder + "Meat-Statistics.csv": (
                    '"commodity_desc","attribute_desc","table_name","unit_desc","year_id","timeperiod_id","timeperiod_desc","amount"\n'
                    '"Broilers","Federally inspected average live weight","Livestock and poultry live and dressed weights","pounds",2026,"08","Aug-2026",6.62\n'
                ),
            }
        )

        async def fetch(*args, **kwargs):
            return content

        with mock.patch("openbb_government_us.usda.utils.ers_client.afetch_ers_file", fetch):
            supply = asyncio.run(ers.afetch_table("supply_and_disappearance"))
            weights = asyncio.run(ers.afetch_table("live_and_dressed_weights"))
        self.assertEqual([(r["year"], r["amount"]) for r in supply], [(1989, 5530.0)])
        self.assertEqual([(r["period"], r["amount"]) for r in weights], [("Aug", 6.62)])


class FarmHouseholdYearTest(unittest.TestCase):
    def test_preliminary_year_suffix(self):
        from openbb_government_us.usda.utils.ers_farm_household_income_and_characteristics import (
            parse_year,
            year_sort_key,
        )

        self.assertEqual(parse_year("2025P"), 2025)
        self.assertEqual(
            sorted(["2026F", "2025P", "2025", "2024"], key=year_sort_key),
            ["2024", "2025", "2025P", "2026F"],
        )


if __name__ == "__main__":
    unittest.main()
