# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""The exchange selects month numbers; the API additionally promises a year."""
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
from openbb_tmx.models.covered_call_screener import TmxCoveredCallScreenerFetcher as F
from openbb_tmx.utils.mx import _parse_series


class CoveredCallExpiration(unittest.IsolatedAsyncioTestCase):
    def rows(self):
        return [
            {"symbol": "RY", "expiration": _parse_series("2026-12-18 C 100")[0], "strike": 100.0},
            {"symbol": "RY", "expiration": _parse_series("2027-12-17 C 110")[0], "strike": 110.0},
            {"symbol": "RY", "expiration": _parse_series("2026-11-20 C 90")[0], "strike": 90.0},
        ]

    async def test_iso_month_uses_exchange_number_and_filters_year(self):
        query = F.transform_query({"expiration": "2026-12"})
        with patch("openbb_tmx.utils.mx.screen_covered_calls", new_callable=AsyncMock, return_value=self.rows()) as fetch:
            rows = await F.aextract_data(query, None)
        self.assertEqual(fetch.await_args.kwargs["expiration"], "12")
        self.assertEqual([str(row["expiration"]) for row in rows], ["2026-12-18"])
        self.assertEqual(F.transform_data(query, rows)[0].expiration.isoformat(), "2026-12-18")

    async def test_unfiltered_screen_preserves_existing_request_and_rows(self):
        expected = self.rows()
        with patch("openbb_tmx.utils.mx.screen_covered_calls", new_callable=AsyncMock, return_value=expected) as fetch:
            rows = await F.aextract_data(F.transform_query({}), None)
        fetch.assert_awaited_once_with(symbol=None, expiration=None, premium=5.0, gain=5.0, use_cache=True)
        self.assertEqual(rows, expected)

    async def test_legacy_month_number_preserves_all_years(self):
        with patch("openbb_tmx.utils.mx.screen_covered_calls", new_callable=AsyncMock, return_value=self.rows()) as fetch:
            rows = await F.aextract_data(F.transform_query({"expiration": "12"}), None)
        self.assertEqual(fetch.await_args.kwargs["expiration"], "12")
        self.assertEqual([str(row["expiration"]) for row in rows], ["2026-12-18", "2027-12-17"])

    def test_invalid_expiration_names_the_field(self):
        for value in ["2026-13", "2026-00", "2026-1", "0000-12", "0", "13", "December"]:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as raised:
                    F.transform_query({"expiration": value})
                self.assertEqual(raised.exception.errors()[0]["loc"], ("expiration",))
