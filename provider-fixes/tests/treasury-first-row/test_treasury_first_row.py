"""Exercise installed Treasury transform using synthetic FedInvest CSVs only."""
from datetime import date
import unittest
from openbb_government_us.treasury.models.treasury_prices import UsTreasuryPricesFetcher as Fetcher, UsTreasuryPricesQueryParams as Query

ROWS = '912797AB1,Bill,0.00,12/01/2030,,98.1,98.2,98.15\n912810AB2,Bond,4.25,12/01/2040,,101.1,101.2,101.15\n'
HEADER = 'CUSIP,Security Type,Rate,Maturity Date,Call Date,Bid,Offer,EOD Price\n'


class TreasuryFirstRow(unittest.TestCase):
    def transform(self, data=ROWS, **kwargs):
        return Fetcher.transform_data(Query(date=date(2026,11,19), **kwargs),data)

    def test_headerless_returns_every_security_in_order(self):
        records=self.transform()
        self.assertEqual([r.cusip for r in records], ['912797AB1','912810AB2'])
        self.assertEqual(records[0].maturity_date,date(2030,12,1))
        self.assertEqual(records[0].date,date(2026,11,19))
        self.assertIsNone(records[0].call_date)
        self.assertAlmostEqual(records[0].bid,98.1)
        self.assertAlmostEqual(records[1].offer,101.2)

    def test_cusip_filter_finds_first_security(self):
        records=self.transform(cusip='912797AB1')
        self.assertEqual([r.cusip for r in records],['912797AB1'])

    def test_security_type_filter_keeps_first_bill(self):
        records=self.transform(security_type='bill')
        self.assertEqual([r.cusip for r in records],['912797AB1'])

    def test_numeric_cusip_preserves_leading_zeros(self):
        data='001234567,Bill,0,12/01/2030,,98.1,98.2,98.15\n009876543,Note,4,12/01/2031,,99,100,99.5\n'
        records=self.transform(data,cusip='001234567')
        self.assertEqual([r.cusip for r in records],['001234567'])
        self.assertEqual([r.cusip for r in self.transform(data)],['001234567','009876543'])

    def test_header_bearing_csv_remains_supported(self):
        self.assertEqual([r.cusip for r in self.transform(HEADER+ROWS)], ['912797AB1','912810AB2'])

    def test_single_headerless_security_not_lost(self):
        self.assertEqual([r.cusip for r in self.transform(ROWS.splitlines()[0]+'\n')], ['912797AB1'])


if __name__=='__main__':
    unittest.main(verbosity=2)
