# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""DDP's public endpoints reject the default programmatic client profile."""
from contextlib import ExitStack
from unittest.mock import patch
import unittest
from requests import Response


class DdpRequestHeaders(unittest.TestCase):
    def transport(self, url, **kwargs):
        headers = kwargs.get("headers", {})
        response = Response()
        response.status_code = 200 if headers.get("User-Agent", "").startswith("Mozilla/5.0") and "text/html" in headers.get("Accept", "") else 403
        response.url = url
        if "Choose.aspx" in url:
            response._content = b'<a href="Output.aspx?series=0123456789abcdef0123456789abcdef">Selected rates [Daily]</a>'
        elif "statcalendar.json" in url:
            response._content = b'[]'
        else:
            response._content = b'<Structure/>'
        return response

    def context(self):
        stack = ExitStack()
        stack.enter_context(patch("openbb_core.provider.utils.helpers.make_request", side_effect=self.transport))
        stack.enter_context(patch("openbb_federal_reserve.utils.cache.cached", side_effect=lambda key, ttl, producer: producer()))
        return stack

    def test_catalogue_reads_the_selected_table_with_compatible_client_headers(self):
        from openbb_federal_reserve.utils.ddp import list_datasets
        with self.context():
            self.assertEqual(list_datasets("H.15"), [{"table": "Selected rates", "dataset": "H.15", "release_name": "Selected Interest Rates"}])

    def test_structure_can_be_read_with_the_same_public_client_profile(self):
        from openbb_federal_reserve.utils.ddp import fetch_structure
        with self.context(), patch("openbb_federal_reserve.utils.sdmx.parse_structure", return_value={"FREQ": {"D": "Daily"}}):
            self.assertEqual(fetch_structure("H15"), {"FREQ": {"D": "Daily"}})

    def test_sdmx_data_download_preserves_the_parsed_economic_rows(self):
        from openbb_federal_reserve.utils.ddp import fetch_dataset
        rows = [{"date": "2026-11-19", "value": 4.5, "series_id": "RIFLGFCY10_N.B"}]
        with self.context(), patch("openbb_federal_reserve.utils.sdmx.parse_series", return_value=[]), patch("openbb_federal_reserve.utils.sdmx.to_rows", return_value=rows):
            self.assertEqual(fetch_dataset("H15", "0123456789abcdef0123456789abcdef"), rows)
