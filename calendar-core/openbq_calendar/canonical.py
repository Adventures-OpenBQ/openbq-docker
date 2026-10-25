# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
from hashlib import sha256
import json


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")


def bundle_digest(value):
    return sha256(canonical_bytes({k: v for k, v in value.items() if k not in {"digest", "generatedAt"}})).hexdigest()
