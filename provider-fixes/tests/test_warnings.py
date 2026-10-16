# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""openbb-core overlay: OBBject warnings stay with the request that raised them."""
import asyncio
import unittest
import warnings
from types import SimpleNamespace
from unittest import mock

from openbb_core.app.command_runner import ParametersBuilder, StaticCommandRunner
from openbb_core.app.model.abstract.warning import OpenBBWarning
from openbb_core.app.model.obbject import OBBject

CONTEXT = SimpleNamespace(
    user_settings=SimpleNamespace(preferences=SimpleNamespace(show_warnings=False)),
    system_settings=SimpleNamespace(
        api_settings=SimpleNamespace(custom_headers=None), logging_suppress=True
    ),
)


async def warns(**_):
    await asyncio.sleep(0.1)
    warnings.warn("Could not retrieve indicators for dataflow 'FFS'", OpenBBWarning)
    return OBBject(results=[])


async def quiet(**_):
    await asyncio.sleep(0.3)
    return OBBject(results=[])


def _execute(func, provider):
    return StaticCommandRunner._execute_func(
        route=f"/{provider}",
        args=(),
        execution_context=CONTEXT,
        func=func,
        kwargs={"provider_choices": SimpleNamespace(provider=provider)},
    )


class WarningScopeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ParametersBuilder, "build", lambda **kw: kw["kwargs"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_overlapping_requests_keep_their_own_warnings(self):
        async def run():
            noisy = asyncio.create_task(_execute(warns, "econdbfake"))
            await asyncio.sleep(0.02)  # the quiet request starts while the noisy one runs
            return await asyncio.gather(noisy, _execute(quiet, "congressfake"))

        for _ in range(2):  # the second round catches a hook left behind by the first
            noisy, bills = asyncio.run(run())
            self.assertIsNone(bills.warnings)
            self.assertEqual(len(noisy.warnings), 1)
            self.assertEqual(noisy.warnings[0].category, "OpenBBWarning")
            self.assertIn("'FFS'", noisy.warnings[0].message)

    def test_single_request_still_collects(self):
        obbject = asyncio.run(_execute(warns, "econdbfake"))
        self.assertEqual([w.category for w in obbject.warnings], ["OpenBBWarning"])


if __name__ == "__main__":
    unittest.main()
