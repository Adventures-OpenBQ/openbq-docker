"""Portable, keyless WPSR price recovery regressions (stdlib unittest)."""
import asyncio
from datetime import date, datetime
from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from openbb_us_eia.models.petroleum_status_report import EiaPetroleumStatusReportFetcher as Fetcher

SPOT = 'https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_D.xls'
WEEKLY = 'https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_DCUS_NUS_W.xls'
MONTHLY = 'https://www.eia.gov/dnav/pet/xls/PET_PRI_GND_DCUS_NUS_M.xls'


def workbook(sheets, offset=0, dates=None):
    dates = dates or [datetime(2026, 11, 2), datetime(2026, 11, 9)]
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        for number in sheets:
            pd.DataFrame([
                ['Back to Contents', f'Data {number}: Price'],
                ['Sourcekey', f'SERIES{number}'],
                ['Date', 'Price (Dollars per Gallon)'],
                [dates[0], float(number)+offset],
                [dates[1], float(number)+offset+0.25],
            ]).to_excel(writer, sheet_name=f'Data {number}', header=False, index=False)
    stream.seek(0)
    return pd.ExcelFile(stream)


class WpsrRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_price_categories_use_current_sources_and_correct_sheets(self):
        cases = [
            ('spot_prices_crude_gas_heating', 'crude,conventional_gas,rbob,heating_oil', range(1, 5)),
            ('spot_prices_diesel_jet_fuel_propane', 'diesel,jet_fuel,propane', range(5, 8)),
        ]
        async def download(url, use_cache):
            self.assertEqual(url, SPOT)
            self.assertFalse(use_cache)
            return workbook(range(1, 8))
        for category, tables, numbers in cases:
            for table, number in list(zip(tables.split(','), numbers)) + [('all', None)]:
                with self.subTest(category=category, table=table):
                    query = Fetcher.transform_query(dict(category=category, table=table, start_date='2026-11-03', end_date='2026-11-19', use_cache=False))
                    with patch('openbb_us_eia.utils.helpers.download_excel_file', download):
                        data = await Fetcher.aextract_data(query, None)
                    rows = Fetcher.transform_data(query, data)
                    expected_numbers = list(numbers) if number is None else [number]
                    self.assertEqual([(r.symbol, r.value) for r in rows], [(f'SERIES{n}', n+0.25) for n in expected_numbers])
                    self.assertTrue(all(r.date == date(2026, 11, 9) and r.unit == 'Dollars per Gallon' for r in rows))

    async def test_retail_frequencies_use_separate_workbooks_and_remain_distinct(self):
        calls = []
        async def download(url, use_cache):
            calls.append(url)
            self.assertIn(url, [WEEKLY, MONTHLY])
            self.assertTrue(use_cache)
            result = workbook([1], offset=100, dates=[datetime(2026, 10, 15), datetime(2026, 11, 15)]) if url == MONTHLY else workbook([1])
            return result
        for table in ['weekly', 'monthly', 'all', 'weekly,monthly']:
            with self.subTest(table=table):
                calls.clear()
                query = Fetcher.transform_query(dict(category='retail_prices', table=table))
                with patch('openbb_us_eia.utils.helpers.download_excel_file', download):
                    data = await Fetcher.aextract_data(query, None)
                self.assertEqual(calls, [WEEKLY, MONTHLY] if table in ['all', 'weekly,monthly'] else [WEEKLY if table == 'weekly' else MONTHLY])
                rows = Fetcher.transform_data(query, data)
                self.assertEqual(len(rows), 4 if table in ['all', 'weekly,monthly'] else 2)
                for frequency, expected in [('weekly', [(date(2026, 11, 2), 1.0), (date(2026, 11, 9), 1.25)]), ('monthly', [(date(2026, 10, 15), 101.0), (date(2026, 11, 15), 101.25)])]:
                    actual = [(r.date, r.value) for r in rows if r.table.endswith(f'({frequency})')]
                    self.assertEqual(actual, expected if table in ['all', 'weekly,monthly', frequency] else [])
                self.assertEqual({r.table.rsplit(' ', 1)[-1] for r in rows}, {'(weekly)', '(monthly)'} if table in ['all', 'weekly,monthly'] else {f'({table})'})

    async def test_missing_selected_sheet_is_reported_instead_of_partial_success(self):
        query = Fetcher.transform_query(dict(category='spot_prices_diesel_jet_fuel_propane', table='all'))
        with self.assertRaisesRegex(Exception, 'Data 6'):
            Fetcher.transform_data(query, {'file': workbook([5, 7])})


if __name__ == '__main__':
    unittest.main()
