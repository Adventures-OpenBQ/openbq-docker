# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v8 `web` profile: opt-in, no host port, and only the gateway's port may be funneled."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
SERVICES = COMPOSE['services']


def test_the_gateway_and_the_pool_start_only_with_the_web_profile():
    for name in ('funnel-gateway', 'rss-ticker'):
        assert SERVICES[name]['profiles'] == ['web'], name
    default = [name for name, service in SERVICES.items() if 'profiles' not in service]
    assert 'funnel-gateway' not in default and 'rss-ticker' not in default


def test_no_web_service_publishes_a_host_port_and_the_gateway_is_locked_down():
    for name in ('funnel-gateway', 'rss-ticker'):
        assert 'ports' not in SERVICES[name], name
    assert SERVICES['rss-ticker']['networks'] == ['openbq-internal']
    # The gateway also reaches the managed table service (v4) on its internal bridge.
    assert SERVICES['funnel-gateway']['networks'] == ['openbq-internal', 'table-private']
    gateway = SERVICES['funnel-gateway']
    assert gateway['read_only'] is True and gateway['cap_drop'] == ['ALL']
    assert gateway['env_file'] == [{'path': './gateway.env', 'required': True}]
    assert 'credentials.env' not in json.dumps(gateway), 'the gateway must not load provider keys'


GATEWAY = '${TS_CERT_DOMAIN}:10000'
PAIRS = [('serve.json', 'serve-funnel.json'), ('serve-v3.json', 'serve-v3-funnel.json')]


def _serve(name):
    return json.loads((ROOT / 'ts-config' / name).read_text())


def test_the_tailnet_only_serve_configs_carry_no_allow_funnel_at_all():
    for tailnet, _ in PAIRS:
        assert 'AllowFunnel' not in _serve(tailnet), tailnet


def test_each_funnel_config_is_its_tailnet_config_plus_only_the_gateway():
    for tailnet_name, funnel_name in PAIRS:
        tailnet, funnel = _serve(tailnet_name), _serve(funnel_name)
        assert tailnet['TCP'] == {k: v for k, v in funnel['TCP'].items() if k != '10000'}, funnel_name
        assert tailnet['Web'] == {k: v for k, v in funnel['Web'].items() if k != GATEWAY}, funnel_name


def test_the_funnel_configs_publish_only_the_gateway_on_10000_and_keep_443_the_api():
    for _, name in PAIRS:
        serve = _serve(name)
        web = serve['Web']
        assert serve['AllowFunnel'] == {GATEWAY: True}, name
        assert web[GATEWAY]['Handlers']['/']['Proxy'] == 'http://funnel-gateway:8091', name
        assert web['${TS_CERT_DOMAIN}:443']['Handlers']['/']['Proxy'] == 'http://openbq-api:6900', name
        assert web['${TS_CERT_DOMAIN}:8088']['Handlers']['/']['Proxy'] == 'http://rss-ticker:8088', name


def test_the_episode_3_configs_keep_the_reference_on_tailnet_8443():
    for name in ('serve-v3.json', 'serve-v3-funnel.json'):
        web = _serve(name)['Web']
        assert web['${TS_CERT_DOMAIN}:8443']['Handlers']['/']['Proxy'] == 'http://openbq-reference:17783', name


def test_the_episode_6_configs_are_the_episode_3_config_plus_rita_and_mcp_tailnet_only():
    # The v6 overlay swaps TS_SERVE_CONFIG to serve-v6*.json, so they keep serve-v3.json's ports (rss-ticker on 8088).
    v3 = _serve('serve-v3.json')['Web']
    for name in ('serve-v6.json', 'serve-v6-keys.json'):
        serve = _serve(name)
        assert {k: v for k, v in serve['Web'].items() if not k.endswith((':10443', ':11443'))} == v3, name
        assert not any(serve['AllowFunnel'].values()), name

def test_every_serve_config_publishes_the_pool_on_tailnet_8088_and_never_funnels_it():
    # A News card dials :8088 whichever Serve file is live, the key-maint ones included.
    names = sorted(p.name for p in (ROOT / 'ts-config').glob('serve*.json'))
    assert len(names) == 8, names  # serve-v6-services.json (v6 opt-in Service names) is the eighth
    for name in names:
        serve = _serve(name)
        assert serve['TCP']['8088'] == {'HTTPS': True}, name
        assert serve['Web']['${TS_CERT_DOMAIN}:8088']['Handlers']['/']['Proxy'] == 'http://rss-ticker:8088', name
        assert not serve.get('AllowFunnel', {}).get('${TS_CERT_DOMAIN}:8088'), name


def test_the_feed_pool_builds_openbq_rss_ticker_8_0_0_from_source():
    service = SERVICES['rss-ticker']
    assert service['image'] == 'openbq-rss-ticker:10.0.0', service['image']
    assert service['build'] == './rss-ticker', service['build']


def test_the_gateway_examples_hold_placeholders_only():
    env = dict(line.split('=', 1) for line in (ROOT / 'gateway.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    assert env == {'GATEWAY_TOKEN': '', 'OPENBB_API_USERNAME': '', 'OPENBB_API_PASSWORD': ''}
    settings = json.loads((ROOT / 'funnel-gateway/settings.example.json').read_text())
    assert 'YOUR-TAILNET' in settings['origin'] and 'example' in settings['previewOrigin']


def test_the_private_gateway_configuration_is_gitignored():
    assert 'gateway-config/' in (ROOT / '.gitignore').read_text().splitlines()


def test_the_services_config_is_the_keys_config_plus_rita_and_mcp():
    """serve-v6-services.json (opt-in, user ruling 2026-10-19): serve-v6-keys.json plus
    svc:openbq-rita and svc:openbq-mcp, served beside :10443 and :11443, never funneled."""
    keys, services = _serve('serve-v6-keys.json'), _serve('serve-v6-services.json')
    assert {k: v for k, v in services.items() if k != 'Services'} == {k: v for k, v in keys.items() if k != 'Services'}
    assert set(services['Services']) == set(keys['Services']) | {'svc:openbq-rita', 'svc:openbq-mcp'}
    for name in keys['Services']:
        assert services['Services'][name] == keys['Services'][name], name
    web = _serve('serve-v6.json')['Web']
    for svc, port in (('svc:openbq-rita', '10443'), ('svc:openbq-mcp', '11443')):
        entry = services['Services'][svc]
        assert entry['TCP'] == {'443': {'HTTPS': True}}, svc
        (host, handlers), = entry['Web'].items()
        assert host == f"{svc[4:]}.<your-tailnet>.ts.net:443", svc
        assert handlers == web['${TS_CERT_DOMAIN}:' + port], svc
    assert not any(services.get('AllowFunnel', {}).values())
