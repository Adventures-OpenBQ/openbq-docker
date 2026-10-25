# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The v4 `web` profile: opt-in, no host port, and only the gateway's port may be funneled."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / 'docker-compose.yml').read_text())
SERVICES = COMPOSE['services']


def test_the_gateway_starts_only_with_the_web_profile_and_rss_ticker_stays_at_v8():
    assert SERVICES['funnel-gateway']['profiles'] == ['web']
    assert 'rss-ticker' not in SERVICES


def test_the_gateway_publishes_no_host_port_and_is_locked_down():
    gateway = SERVICES['funnel-gateway']
    assert 'ports' not in gateway
    assert 'openbq-internal' in gateway['networks']
    assert gateway['read_only'] is True and gateway['cap_drop'] == ['ALL']
    assert gateway['env_file'] == [{'path': './gateway.env', 'required': True}]
    assert 'credentials.env' not in json.dumps(gateway), 'the gateway must not load provider keys'


GATEWAY = '${TS_CERT_DOMAIN}:10000'
PAIRS = [('serve.json', 'serve-funnel.json'), ('serve-v3.json', 'serve-v3-funnel.json')]


def _serve(name):
    return json.loads((ROOT / 'ts-config' / name).read_text())


def test_the_tailnet_only_serve_configs_funnel_nothing():
    for tailnet, _ in PAIRS:
        assert not any(_serve(tailnet).get('AllowFunnel', {}).values()), tailnet


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


def test_the_episode_3_configs_keep_the_reference_on_tailnet_8443():
    for name in ('serve-v3.json', 'serve-v3-funnel.json'):
        web = _serve(name)['Web']
        assert web['${TS_CERT_DOMAIN}:8443']['Handlers']['/']['Proxy'] == 'http://openbq-reference:17783', name


def test_the_gateway_examples_hold_placeholders_only():
    env = dict(line.split('=', 1) for line in (ROOT / 'gateway.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    assert env == {'GATEWAY_TOKEN': '', 'OPENBB_API_USERNAME': '', 'OPENBB_API_PASSWORD': ''}
    settings = json.loads((ROOT / 'funnel-gateway/settings.example.json').read_text())
    assert 'YOUR-TAILNET' in settings['origin']


def test_the_private_gateway_configuration_is_gitignored():
    assert 'gateway-config/' in (ROOT / '.gitignore').read_text().splitlines()
