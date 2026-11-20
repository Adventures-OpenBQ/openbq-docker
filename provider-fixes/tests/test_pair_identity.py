from unittest.mock import patch
import unittest
from openbb_cftc.utils import fx_vol
from test_own_fallback import AS_OF, forward, market

class PairIdentity(unittest.TestCase):
    def test_equal_ids_in_usd_cross_legs_are_independent(self):
        own=forward(' same ','EUR','CHF',.85)
        own['UPI FISN']='NA/Fwd CHF EUR'
        eur=forward('same','EUR','USD',1.20)
        chf=forward('same','CHF','USD',1.50)
        self.assertAlmostEqual(market(own,[eur,chf])['spot'],.8)
    def test_unique_id_in_another_curve_pair_does_not_exclude_raw_pair(self):
        observed=forward('unique','EUR','USD',1.10)
        own=forward('unique','EUR','CHF',.85)
        curve=fx_vol.pair_curve([observed],'EURUSD',AS_OF)
        self.assertAlmostEqual(fx_vol.market_spot(curve,[own],'EUR','CHF',AS_OF,'unique')[0],.85)
    def test_spaced_raw_identifier_and_reversed_pair_legs_exclude_own(self):
        own=forward('  unique  ','EUR','USD',1.15)
        curve=fx_vol.pair_curve([own],'EURUSD',AS_OF)
        reverse=forward(' unique ','USD','EUR',1/1.15)
        self.assertIsNone(fx_vol.market_spot(curve,[reverse],'EUR','USD',AS_OF,'unique')[0])

    def test_unrecognized_raw_orientation_is_not_excluded(self):
        # EURCHF's observation FISN is CHF EUR; this opposite raw FISN is
        # not recognized by its curve and follows the shared fallback rule.
        own=forward('unique','EUR','CHF',.85)
        curve=fx_vol.pair_curve([own],'EURCHF',AS_OF)
        self.assertNotIn('unique',curve)
        self.assertAlmostEqual(fx_vol.market_spot(curve,[own],'EUR','CHF',AS_OF,'unique')[0],.85)
