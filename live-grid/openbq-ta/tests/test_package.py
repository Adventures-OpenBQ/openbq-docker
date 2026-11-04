# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The package itself: its version and its licence headers."""
from pathlib import Path

import openbq_ta

ROOT = Path(__file__).resolve().parents[1]


def test_the_package_reports_its_version():
    assert openbq_ta.__version__ == "0.1.0"


def test_every_package_file_is_apache_only():
    # Needles are built at runtime so this file does not contain them itself.
    needles = ("Business " + "Source", "AG" + "PL")
    for path in [*ROOT.glob("openbq_ta/*.py"), *ROOT.glob("tests/*.py")]:
        text = path.read_text()
        assert text.splitlines()[1] == "# SPDX-License-Identifier: Apache-2.0", path
        assert not any(n in text for n in needles), path
