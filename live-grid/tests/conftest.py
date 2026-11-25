# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for live-grid tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _tick_spool_in_tmp(tmp_path, monkeypatch):
    """create_app spools unacknowledged ticks beside the watchlist (/data/spool
    by default, openbq-docker v10). No test may write to the real /data."""
    monkeypatch.setenv("LIVE_GRID_SPOOL_DIR", str(tmp_path / "spool"))


@pytest.fixture
def fake_ws_client_factory():
    """Stand-in for feeds._build_client; records every client it builds."""
    built: list[MagicMock] = []

    def factory(api_key: str, feed: str, symbols: list[str]) -> MagicMock:
        client = MagicMock()
        client.feed = feed
        client.symbols = list(symbols)
        client.data_list = []
        client.running = True
        built.append(client)
        return client

    factory.built = built
    return factory
