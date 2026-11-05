# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Art's Charts manages custom studies (spec 2026-11-04 §1, §2); openbq_ta runs them.

Install = stage, import, rename: the file is written under a staging name, imported in
this process (any error refuses the install and goes back to the caller), and renamed into
place, so live-grid -- which re-reads the folder by mtime -- never sees a half-written file.
The pack (arts_charts_pack.py) is installed the same way at startup.
"""
from __future__ import annotations

import os
from pathlib import Path

from openbq_ta.registry import StudyError
from openbq_ta.studies import STEM, installed, load_file, sync_dir, unload

PACK = Path(__file__).with_name("arts_charts_pack.py")
PACK_STEM = "arts_charts_pack"


def studies_dir() -> Path | None:
    raw = os.getenv("TA_STUDIES_DIR", "").strip()
    return Path(raw) if raw else None


def api_enabled() -> bool:
    return os.getenv("TA_STUDIES_API", "").strip().lower() in ("1", "true", "yes", "on")


def load_pack() -> None:
    """The pack, from this package, when it is not already loaded."""
    if PACK_STEM not in installed():
        load_file(PACK, PACK_STEM)


def install(directory: Path, stem: str, source: str) -> list[str]:
    """Write `source` as `<stem>.py` and load it, replacing that stem's studies.

    Loaded from the staged file first: a bad upload leaves the previous version on disk
    and re-registers it, so a typo costs the sender a 400 rather than costing the chart a
    study it had.
    """
    if not STEM.fullmatch(stem):
        raise StudyError("a study file name is lower-case letters, digits and _")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    final, temp = directory / f"{stem}.py", directory / f".{stem}.py.upload"
    temp.write_text(source)
    unload(stem)
    try:
        names = load_file(temp, stem=stem)
    except StudyError:
        temp.unlink(missing_ok=True)
        if final.exists():
            load_file(final)
        raise
    temp.replace(final)
    return names


def remove(directory: Path, stem: str) -> list[str]:
    names = unload(stem)
    (Path(directory) / f"{stem}.py").unlink(missing_ok=True)
    return names


def load_all() -> None:
    """At startup: the pack into the shared folder, then every study in it. Without a folder,
    the pack alone, from this package."""
    directory = studies_dir()
    if directory is None:
        load_pack()
        return
    install(directory, PACK_STEM, PACK.read_text())
    sync_dir(directory)
