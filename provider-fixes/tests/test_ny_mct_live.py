from datetime import date
from pathlib import Path
import unittest
from openbb_federal_reserve.models.regional.new_york_mct import FederalReserveNewYorkCoreTrendInflationFetcher as F

RAW=(Path(__file__).parent / 'fixtures' / 'new-york-mct.csv').read_text()
class MCT(unittest.TestCase):
    def test_current_cached_iso_csv_produces_real_rows_and_values(self):
        rows=F.transform_data(F.transform_query({}),[{'_raw':RAW}])
        self.assertEqual(len(rows),801)
        self.assertEqual(rows[0].date,date(1960,1,1))
        self.assertAlmostEqual(rows[0].mct,1.24)
        self.assertTrue(all(r.mct is not None for r in rows))
    def test_current_iso_dates_obey_requested_bounds(self):
        rows=F.transform_data(F.transform_query({'start_date':'1960-02-01','end_date':'1960-03-01'}),[{'_raw':RAW}])
        self.assertEqual([r.date for r in rows],[date(1960,2,1),date(1960,3,1)])
    def test_legacy_us_dates_and_malformed_rows_remain_supported(self):
        lines=RAW.splitlines();rows=lines[:4]+[lines[4].replace('1960-01-01','01/01/1960'),lines[5].replace('1960-02-01','bad-date')]
        result=F.transform_data(F.transform_query({}),[{'_raw':'\n'.join(rows)}])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].date,date(1960,1,1))
        self.assertAlmostEqual(result[0].mct,1.24)

if __name__=='__main__':unittest.main(verbosity=2)
