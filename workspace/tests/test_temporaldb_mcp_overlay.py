"""Opt-in MCP integration does not inherit provider/runtime credentials."""
from pathlib import Path
import json
import os
import subprocess


def test_mcp_overlay_is_private_scoped_and_resource_bounded():
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TEMPORALDB_IMAGE='sha256:'+'a'*64, TEMPORALDB_MCP_ALLOWED_HOSTS='["mcp.example.test"]', TEMPORALDB_MCP_ALLOWED_ORIGINS='[]', TEMPORALDB_MCP_POLICY_HOST='/private/tmp/policy.json')
    result = subprocess.run(['docker','compose','-f',str(root/'v11/compose.temporaldb-mcp.yaml'),'--profile','mcp','config','--format','json'],env=env,capture_output=True,text=True,check=True)
    service = json.loads(result.stdout)['services']['temporaldb-mcp']
    assert service['profiles'] == ['mcp']
    assert service['command'] == ['python', '-m', 'temporaldb.mcp.app']
    assert 'ports' not in service and 'env_file' not in service
    assert service['read_only'] and service['cap_drop'] == ['ALL']
    assert int(service['mem_limit']) == 268435456 and service['pids_limit'] == 64
    assert service['environment']['TEMPORALDB_MCP_API_ORIGIN'] == 'http://temporaldb-api:8080'
    assert all(k.startswith('TEMPORALDB_MCP_') for k in service['environment'])
    assert len(service['volumes']) == 1 and service['volumes'][0]['read_only']
    assert 'healthcheck' in service
