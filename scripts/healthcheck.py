#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Probe API readiness using its configured Basic credential, without logging it."""
import base64
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    request = Request(sys.argv[1])
    if os.getenv('OPENBB_API_AUTH', 'false').lower() in {'true', 't', '1', 'yes', 'y'}:
        username = os.getenv('OPENBB_API_USERNAME')
        password = os.getenv('OPENBB_API_PASSWORD')
        if username is None or password is None:
            return 1
        token = base64.b64encode(f'{username}:{password}'.encode()).decode()
        request.add_header('Authorization', 'Basic ' + token)
    try:
        with urlopen(request, timeout=8) as response:
            return 0 if response.status == 200 else 1
    except (URLError, TimeoutError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
