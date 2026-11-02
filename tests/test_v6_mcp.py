# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v6 MCP server: the API's provider keys, no in-process API auth, a memory cap."""
import json
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


def test_mcp_announces_the_server_name_widgets_match_on():
    # Workspace pairs a widget with an MCP tool only when mcp_tool.mcp_server equals the
    # connected server's name; platform_api stamps generated widgets "Open Data Platform".
    name = MCP['environment']['OPENBB_MCP_NAME']
    assert name == 'Open Data Platform'
    for path in (ROOT / 'provider-fixes').rglob('*widgets.json'):
        data = json.loads(path.read_text())
        for widget in (data.values() if isinstance(data, dict) else data):
            if 'mcp_tool' in widget:
                assert widget['mcp_tool']['mcp_server'] == name, path


def test_static_widget_tool_ids_carry_the_router_prefix():
    # The MCP server names a tool by its full route, so /federal_reserve/ffiec/institutions
    # is federal_reserve_ffiec_institutions (checked against the v6 image's catalog).
    assets = ROOT / 'provider-fixes/openbb_federal_reserve/assets'
    for path in assets.rglob('*widgets.json'):
        for widget in json.loads(path.read_text()).values():
            assert widget['mcp_tool']['tool_id'].startswith('federal_reserve_'), path
