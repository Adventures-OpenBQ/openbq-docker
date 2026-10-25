# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v6 MCP server: the API's provider keys, no in-process API auth, a memory cap."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MCP = yaml.safe_load((ROOT / 'docker-compose.v6.yml').read_text())['services']['openbq-mcp']
API = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())['services']['openbq-api']


def test_mcp_gets_the_api_provider_keys():
    assert MCP['env_file'] == API['env_file']


def test_mcp_in_process_calls_skip_the_api_basic_auth():
    assert MCP['environment']['OPENBB_API_AUTH'] == 'false'


def test_mcp_has_the_api_memory_cap():
    assert MCP['mem_limit'] == API['mem_limit']
