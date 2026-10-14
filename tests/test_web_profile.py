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
        assert SERVICES[name]['networks'] == ['openbq-internal'], name
    gateway = SERVICES['funnel-gateway']
    assert gateway['read_only'] is True and gateway['cap_drop'] == ['ALL']
    assert gateway['env_file'] == [{'path': './gateway.env', 'required': True}]
    assert 'credentials.env' not in json.dumps(gateway), 'the gateway must not load provider keys'


def test_the_tailnet_only_serve_config_carries_no_allow_funnel_at_all():
    serve = json.loads((ROOT / 'ts-config/serve.json').read_text())
    assert 'AllowFunnel' not in serve


def test_both_serve_configs_publish_the_same_ports_except_the_gateways():
    tailnet = json.loads((ROOT / 'ts-config/serve.json').read_text())
    funnel = json.loads((ROOT / 'ts-config/serve-funnel.json').read_text())
    gateway = '${TS_CERT_DOMAIN}:8443'
    assert tailnet['TCP'] == {k: v for k, v in funnel['TCP'].items() if k != '8443'}
    assert tailnet['Web'] == {k: v for k, v in funnel['Web'].items() if k != gateway}


def test_the_feed_pool_is_rss_feedhandler_8_0_1_pinned_by_digest():
    image = SERVICES['rss-ticker']['image']
    assert image.startswith('ghcr.io/artcashin/rss-feedhandler:8.0.1@sha256:'), image


def test_the_funnel_config_publishes_only_the_gateway_and_keeps_443_the_api():
    serve = json.loads((ROOT / 'ts-config/serve-funnel.json').read_text())
    web = serve['Web']
    assert {k: v for k, v in serve['AllowFunnel'].items() if v} == {'${TS_CERT_DOMAIN}:8443': True}
    assert web['${TS_CERT_DOMAIN}:8443']['Handlers']['/']['Proxy'] == 'http://funnel-gateway:8091'
    assert web['${TS_CERT_DOMAIN}:443']['Handlers']['/']['Proxy'] == 'http://openbq-api:6900'
    assert web['${TS_CERT_DOMAIN}:8088']['Handlers']['/']['Proxy'] == 'http://rss-ticker:8088'


def test_the_gateway_examples_hold_placeholders_only():
    env = dict(line.split('=', 1) for line in (ROOT / 'gateway.env.example').read_text().splitlines()
               if line and not line.startswith('#'))
    assert env == {'GATEWAY_TOKEN': '', 'OPENBB_API_USERNAME': '', 'OPENBB_API_PASSWORD': ''}
    settings = json.loads((ROOT / 'funnel-gateway/settings.example.json').read_text())
    assert 'YOUR-TAILNET' in settings['origin'] and 'example' in settings['previewOrigin']
