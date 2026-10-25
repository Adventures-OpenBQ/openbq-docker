# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Unused gateway Rita must not prevent the default or named gateway route."""
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
DOOR = yaml.safe_load((ROOT / 'docker-compose.v6.yml').read_text())['services']['openbq-rita-door']

def test_gateway_rita_is_opt_in():
    assert DOOR.get('profiles') == ['web']

def test_absent_unused_gateway_rita_env_does_not_break_compose():
    assert DOOR['env_file'] == [{'path': './rita-door.env', 'required': False}]

def test_explicit_door_start_still_rejects_missing_or_paid_endpoint():
    guard = DOOR['command'][-1]
    assert 'api.openai.com' in guard and 'exit 1' in guard and 'OPENAI_BASE_URL' in guard
