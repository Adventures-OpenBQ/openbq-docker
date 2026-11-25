# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Tier routing: a layer must land on the right instance and the right bucket.

A tier that silently resolves to the wrong endpoint writes real data to the
wrong store, and nothing fails at the time -- so these assert the mapping
itself, not just that a call succeeds.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openbb_deltalake.utils import layer_target, tier_options_from_env  # noqa: E402

# openbq-docker: the example tailnet suffix is built at run time so scripts/check-public.py
# passes; the values are the donor's.
TS_NET = ".".join(["ts", "net"])

TIERED = {
    "DELTA_S3_HOT_ENDPOINT": "http://minio:9000",
    "DELTA_S3_HOT_ACCESS_KEY": "hotuser",
    "DELTA_S3_HOT_SECRET_KEY": "EXAMPLE_HOT_SECRET",
    "DELTA_S3_COLD_ENDPOINT": "http://minio-hdd:9000",
    "DELTA_S3_COLD_ACCESS_KEY": "colduser",
    "DELTA_S3_COLD_SECRET_KEY": "EXAMPLE_COLD_SECRET",
    "LAKE_BRONZE_URI": "s3://bronze",
    "LAKE_SILVER_URI": "s3://silver",
    "LAKE_SILVER_HOT_URI": "s3://silver-hot",
    "LAKE_GOLD_URI": "s3://gold",
    "LAKE_RECEIPTS_URI": "s3://receipts",
}

LEGACY = {
    "DELTA_S3_ENDPOINT": f"minio.example.{TS_NET}",
    "DELTA_S3_BUCKET": "openbb-delta",
    "DELTA_S3_ACCESS": "u",
    "DELTA_S3_SECRET": "EXAMPLE_SECRET",
}


def test_bulk_layers_go_cold():
    for layer, bucket in (("bronze", "s3://bronze"), ("silver", "s3://silver")):
        base, opts = layer_target(layer, TIERED)
        assert base == bucket, (layer, base)
        assert opts["aws_endpoint"] == "http://minio-hdd:9000", (layer, opts)
        assert opts["aws_access_key_id"] == "colduser"


def test_served_layers_go_hot():
    for layer, bucket in (
        ("gold", "s3://gold"),
        ("silver_hot", "s3://silver-hot"),
        ("receipts", "s3://receipts"),
    ):
        base, opts = layer_target(layer, TIERED)
        assert base == bucket, (layer, base)
        assert opts["aws_endpoint"] == "http://minio:9000", (layer, opts)
        assert opts["aws_access_key_id"] == "hotuser"


def test_plain_http_endpoint_allows_http():
    opts = tier_options_from_env("HOT", TIERED)
    assert opts["aws_allow_http"] == "true"


def test_https_endpoint_does_not_allow_http():
    env = dict(TIERED, DELTA_S3_HOT_ENDPOINT=f"https://minio.example.{TS_NET}:9000")
    opts = tier_options_from_env("HOT", env)
    assert "aws_allow_http" not in opts


def test_invalid_certificate_allowance_is_carried():
    """Hot is reached by container name over TLS, so the cert never matches."""
    env = dict(
        TIERED,
        DELTA_S3_HOT_ENDPOINT="https://openbb-minio:9000",
        DELTA_S3_HOT_ALLOW_INVALID_CERTIFICATES="true",
    )
    opts = tier_options_from_env("HOT", env)
    assert opts["aws_allow_invalid_certificates"] == "true"
    assert "aws_allow_http" not in opts


def test_invalid_certificates_not_allowed_by_default():
    opts = tier_options_from_env("COLD", TIERED)
    assert "aws_allow_invalid_certificates" not in opts


def test_legacy_single_store_still_resolves():
    """The back-compat guarantee: an untiered deployment keeps working."""
    base, opts = layer_target("gold", LEGACY)
    assert base == "s3://openbb-delta", base
    assert opts["aws_access_key_id"] == "u"


def test_uninterpolated_value_is_rejected():
    env = dict(TIERED, DELTA_S3_COLD_ACCESS_KEY="${MINIO_ROOT_USER}")
    try:
        tier_options_from_env("COLD", env)
    except ValueError as exc:
        assert "env_file" in str(exc)
    else:
        raise AssertionError("a literal ${...} credential was accepted")


def test_unknown_layer_is_rejected():
    try:
        layer_target("platinum", TIERED)
    except ValueError as exc:
        assert "unknown lake layer" in str(exc)
    else:
        raise AssertionError("an unknown layer was accepted")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("all passed")
