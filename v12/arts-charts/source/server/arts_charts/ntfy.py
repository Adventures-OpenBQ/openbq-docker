# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Pushes to ntfy (spec §4, S4): one JSON publish per push, with the worker's token.

ntfy's JSON form (POST to the server root, `topic` in the body) carries the
title, message, click link, attachment URL and action buttons as plain
UTF-8 JSON -- no header encoding, no upload. The attachment is a link to the
inbox item's stored snapshot, which the phone fetches over the tailnet like
the click link.
"""
from __future__ import annotations

import httpx


class NtfyError(Exception):
    """A publish that did not land; the text names no URL and no token."""


class Ntfy:
    def __init__(self, url: str, topic: str, token: str | None = None, timeout: float = 10.0):
        self._url, self._topic, self._timeout = url.rstrip("/") + "/", topic, timeout
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def publish(self, message: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, headers=self._headers,
                                             json={"topic": self._topic, **message})
        except httpx.HTTPError as exc:
            raise NtfyError(f"ntfy unreachable ({type(exc).__name__})") from None
        if response.status_code >= 300:
            raise NtfyError(f"ntfy answered {response.status_code}")
