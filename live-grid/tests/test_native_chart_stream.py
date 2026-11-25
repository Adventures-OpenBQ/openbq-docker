"""Opt-in native q probe runs in a child to preserve PyKX thread ownership."""

import os
from pathlib import Path
import subprocess
import sys
import pytest


def test_native_chart_stream_authenticated_snapshot_late_candle_resume():
    if not os.getenv("OPENBQ_TEST_Q"):
        pytest.skip("OPENBQ_TEST_Q is required for native q integration")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "support/native_chart_probe.py")],
        capture_output=True,
        text=True,
        timeout=40,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
