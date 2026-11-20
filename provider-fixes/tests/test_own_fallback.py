"""Offline production-path checks for leaving unique identifiers out of fallback spot."""
import unittest
from datetime import date
from unittest.mock import patch

from openbb_cftc.utils import fx_valuation as fv, fx_vol

AS_OF = date(2026, 7, 24)


def forward(identifier, base, quote, rate):
    return {
        "Dissemination Identifier": identifier, "Action type": "NEWT",
        "Event type": "TRAD", "Asset Class": "FX", "UPI FISN": f"NA/Fwd {base} {quote}",
        "UPI Underlier Name": f"{base} {quote}",
        "Notional currency-Leg 1": base, "Notional currency-Leg 2": quote,
        "Notional amount-Leg 1": "1000000", "Notional amount-Leg 2": str(int(1e6*rate)),
        "Exchange rate": str(rate), "Exchange rate basis": f"{base}/{quote}",
        "Effective Date": "2026-07-25", "Expiration Date": "2026-08-31",
        "Cleared":"N", "Package indicator":"FALSE", "Non-standardized term indicator":"FALSE",
    }


def market(own, others):
    with patch.object(fx_vol, "rate_discount_factor", return_value=lambda years: 1.0):
        return fv.fx_market([own, *others], [], fv.extract_fx_trade(own, AS_OF), AS_OF)


class OwnPrintFallback(unittest.TestCase):
    def test_only_unique_forward_is_unpriceable(self):
        own = forward("  unique  ", "EUR", "USD", 1.15)
        self.assertIsNone(market(own, []))

    def test_unidentified_and_duplicate_remain_shared(self):
        self.assertAlmostEqual(market(forward("", "EUR", "USD", 1.15), [])["spot"], 1.15)
        own = forward("same", "EUR", "USD", 1.15)
        other = forward("same", "EUR", "USD", 1.25)
        self.assertAlmostEqual(market(own, [other])["spot"], 1.20)

    def test_independent_direct_print_supplies_anchor(self):
        own = forward("unique", "EUR", "USD", 1.15)
        other = forward("independent", "EUR", "USD", 1.25)
        self.assertAlmostEqual(market(own, [other])["spot"], 1.25)

    def test_independent_usd_cross_survives(self):
        own = forward("unique", "EUR", "CHF", .85)
        own["UPI FISN"] = "NA/Fwd CHF EUR"
        eur = forward("other1", "EUR", "USD", 1.20)
        chf = forward("other2", "CHF", "USD", 1.50)
        self.assertAlmostEqual(market(own, [eur, chf])["spot"], .8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
