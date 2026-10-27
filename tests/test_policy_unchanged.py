# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""v12 adds /charts beside the canonical policy: policy.mjs stays release/v11's, byte for byte."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V11_POLICY_SHA256 = 'cbe50fed7a0d5a673e4a0343c8fe8d68d475e2728c4e49e876029022133b72c3'


def test_policy_mjs_is_v11s():
    assert hashlib.sha256((ROOT / 'funnel-gateway/policy.mjs').read_bytes()).hexdigest() == V11_POLICY_SHA256
