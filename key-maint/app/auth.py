# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

"""HTTP Basic auth that follows the main API's own setting in credentials.env.

An explicit off value or omitted flag leaves key-maint open when the file is
readable. An on value requires the API's OPENBB_API_USERNAME and
OPENBB_API_PASSWORD. Unknown flags, missing credentials with auth on, and an
unreadable file deny access."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.credfile import load

_security = HTTPBasic(auto_error=False)
_ON = ("1", "true", "yes")
_OFF = ("", "0", "false", "no")


def make_guard(auth_file: str):
    def guard(
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
    ) -> None:
        conf = load(auth_file)
        flag = conf.get("OPENBB_API_AUTH", "").lower() if conf is not None else None
        if flag in _OFF:
            return
        conf = conf or {}
        user = conf.get("OPENBB_API_USERNAME") or ""
        pw = conf.get("OPENBB_API_PASSWORD") or ""
        supplied_user = credentials.username if credentials else ""
        supplied_pw = credentials.password if credentials else ""
        ok_user = secrets.compare_digest(supplied_user.encode(), user.encode())
        ok_pw = secrets.compare_digest(supplied_pw.encode(), pw.encode())
        if not (flag in _ON and user and pw and credentials and ok_user and ok_pw):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Basic"},
            )

    return guard
