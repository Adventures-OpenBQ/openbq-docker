# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""FINRA bond list: the MBS row cap (ROW_CAPS) bounds TRACE paging and says so, offline."""
import asyncio
import unittest
import warnings
from contextlib import asynccontextmanager
from unittest import mock

from openbb_core.app.model.abstract.warning import OpenBBWarning
from openbb_finra.models import bond_list
from openbb_finra.models.bond_list import FinraBondListFetcher, FinraBondListQueryParams
from openbb_finra.utils import client
from openbb_finra.utils.client import TraceSession


class FakeTrace:
    """A TRACE dataset of `total` tiny rows; the real query and collect_pages page it."""

    def __init__(self, total: int):
        self.total = total
        self.pages: list[tuple[int, int]] = []
        self.max_rows: list = []

    def patches(self):
        fake = self
        query = TraceSession.query

        async def page(self, dataset, payload, offset, limit):
            fake.pages.append((offset, limit))
            end = min(offset + limit, fake.total)
            return [{"finraSecurityIdentifier": f"S{i}"} for i in range(offset, end)], fake.total

        async def spy(self, dataset, payload, max_rows=None):
            fake.max_rows.append(max_rows)
            return await query(self, dataset, payload, max_rows)

        @asynccontextmanager
        async def session():
            yield TraceSession(None, "token")

        return (
            mock.patch.object(TraceSession, "page", page),
            mock.patch.object(TraceSession, "query", spy),
            mock.patch.object(client, "trace_session", session),
        )

    def run(self, bond_type: str):
        p1, p2, p3 = self.patches()
        with p1, p2, p3, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            query = FinraBondListQueryParams(bond_type=bond_type)
            rows = asyncio.run(FinraBondListFetcher.aextract_data(query, None))
        return rows, [w for w in caught if issubclass(w.category, OpenBBWarning)]


CAP = bond_list.ROW_CAPS["MBS"]


def message(cap: int) -> str:
    return f"MBS is capped at the first {cap:,} TRACE records (by FINRA security id)."


class MbsCapTest(unittest.TestCase):
    def test_mbs_over_cap_pages_only_to_the_cap_and_warns(self):
        trace = FakeTrace(CAP + 10_000)
        rows, caught = trace.run("MBS")
        self.assertEqual(trace.max_rows, [CAP])
        self.assertEqual(sum(limit for _, limit in trace.pages), CAP)
        self.assertEqual(max(offset + limit for offset, limit in trace.pages), CAP)
        self.assertEqual(len(rows), CAP)
        self.assertEqual([str(w.message) for w in caught], [message(CAP)])

    def test_mbs_under_cap_does_not_warn(self):
        trace = FakeTrace(12)
        rows, caught = trace.run("MBS")
        self.assertEqual((trace.max_rows, len(rows), caught), ([CAP], 12, []))

    def test_other_types_are_not_capped(self):
        for bond_type in ("CA", "TS"):
            with self.subTest(bond_type=bond_type):
                trace = FakeTrace(12)
                rows, caught = trace.run(bond_type)
                self.assertEqual((trace.max_rows, len(rows), caught), ([None], 12, []))

    def test_warning_reaches_the_api_response(self):
        # Through the real app and the per-provider loop thread; a small cap keeps it quick.
        from fastapi.testclient import TestClient
        from openbb_core.api.rest_api import app

        trace = FakeTrace(25)
        p1, p2, p3 = trace.patches()
        with p1, p2, p3, mock.patch.dict(bond_list.ROW_CAPS, {"MBS": 10}):
            response = TestClient(app, raise_server_exceptions=False).get(
                "/api/v1/finra/fixedincome/bonds?provider=finra&bond_type=MBS"
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["results"]), 10)
        self.assertEqual(
            body["warnings"],
            [{"category": "OpenBBWarning", "message": message(10)}],
        )


if __name__ == "__main__":
    unittest.main()
