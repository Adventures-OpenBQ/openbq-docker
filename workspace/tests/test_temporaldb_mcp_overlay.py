"""Opt-in MCP integration does not inherit provider/runtime credentials."""
from pathlib import Path
import json
import os
import subprocess


def test_mcp_overlay_is_private_scoped_and_resource_bounded():
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, TEMPORALDB_MCP_ALLOWED_HOSTS='["mcp.example.test"]', TEMPORALDB_MCP_ALLOWED_ORIGINS='[]', TEMPORALDB_MCP_POLICY_HOST='/private/tmp/policy.json',
               TEMPORALDB_ARCHIVE_HOST='/private/tmp/archive', TEMPORALDB_EVIDENCE_HOST='/private/tmp/evidence', OPENBQ_V11_IMAGE='sha256:'+'b'*64,
               **{name: os.devnull for name in ('TEMPORALDB_API_ENV_FILE','TEMPORALDB_WORKER_ENV_FILE','OPENBQ_V11_ENV_FILE')})
    files = [arg for name in ('compose.temporaldb.yaml','compose.temporaldb-mcp.yaml') for arg in ('-f',str(root/'v11'/name))]
    result = subprocess.run(['docker','compose',*files,'--profile','temporaldb-v11','--profile','mcp','config','--format','json'],env=env,capture_output=True,text=True,check=True)
    services = json.loads(result.stdout)['services']
    service = services['temporaldb-mcp']
    api = services['temporaldb-api']
    assert service['image'] == api['image'] and service['image'].startswith('sha256:')
    assert service['pull_policy'] == 'never' and service['platform'] == api['platform']
    assert 'temporaldb-api' in service['depends_on']
    assert service['profiles'] == ['mcp']
    assert service['command'] == ['python', '-m', 'temporaldb.mcp.app']
    assert 'ports' not in service and 'env_file' not in service
    assert service['read_only'] and service['cap_drop'] == ['ALL']
    assert int(service['mem_limit']) == 268435456 and service['pids_limit'] == 64
    assert service['environment']['TEMPORALDB_MCP_API_ORIGIN'] == 'http://temporaldb-api:8080'
    assert all(k.startswith('TEMPORALDB_MCP_') for k in service['environment'])
    assert len(service['volumes']) == 1 and service['volumes'][0]['read_only']
    assert 'healthcheck' in service
