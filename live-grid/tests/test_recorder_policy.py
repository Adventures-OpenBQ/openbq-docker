# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""A valid queued tick is not poison because its service identity was rejected."""
from datetime import datetime, timedelta, timezone

import pytest

from app.recorder import TickRecorder
from app.spool import TickSpool


@pytest.mark.parametrize("error", ["KdbAuthenticationError", "KdbAuthorizationError", "KdbProtocolError"])
def test_policy_failure_retains_spool_then_corrected_identity_recovers(tmp_path, error):
    from openbq_kdb import protocol

    failure = getattr(protocol, error)
    now = [0.0]
    clock = lambda: now[0]  # noqa: E731
    utc = lambda: datetime(2026, 11, 20, tzinfo=timezone.utc) + timedelta(seconds=now[0])  # noqa: E731
    spool = TickSpool(tmp_path / "spool", clock=clock, utcnow=utc)
    rows = [(datetime(2026, 11, 20, 14, 30), "AAPL", 100.0 + i, 1.0) for i in range(3)]
    spool.append(rows)

    class Store:
        blocked = True
        accepted = []

        def ticks_present(self, frame):
            return 0

        def write_ticks(self, frame):
            if self.blocked:
                raise failure("KDB_POLICY")
            self.accepted.extend(frame.to_dict("records"))
            return len(frame)

    store = Store()
    rec = TickRecorder(store, spool=spool, clock=clock)
    for _ in range(20):
        rec.flush()
        now[0] += 120
    assert spool.count == 3
    assert spool.quarantined == 0 and rec.dropped == 0
    assert rec.stats()["configuration_blocked"] is True
    store.blocked = False
    now[0] += 120
    assert rec.flush() == 3
    assert len(store.accepted) == 3 and spool.count == 0
    assert rec.stats()["configuration_blocked"] is False
    spool.close()
