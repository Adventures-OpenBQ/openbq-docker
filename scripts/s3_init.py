# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""One-shot: create the Delta Lake bucket on the stack's S3 store (RustFS).

Delta Lake does not create its own bucket, so a fresh store would 404 on the
first write. The donor did this with `mc mb --ignore-existing` in a
`minio-init` container (bdobb-dev/openbb-docker, the donor line, 78c7af9). This line
uses no MinIO software at all (user ruling 2026-10-12: RustFS instead of
MinIO), so the bucket is made over the plain S3 API with pyarrow, which the
openbq-lake image already carries for delta-rs -- no extra client, no extra
image.

It reads the same DELTA_S3_* contract every reader and writer of the store
uses (rustfs.env), retries until the store answers, and is idempotent: an
existing bucket is success. The bucket stays private; no policy is attached.

    python s3_init.py            # create DELTA_S3_BUCKET, exit 0
"""
from __future__ import annotations

import logging
import os
import sys
import time

log = logging.getLogger("s3-init")

_REQUIRED = ("DELTA_S3_ENDPOINT", "DELTA_S3_BUCKET", "DELTA_S3_ACCESS", "DELTA_S3_SECRET")


def settings(env=None) -> dict:
    """The S3 connection from DELTA_S3_*, as openbb-deltalake builds it."""
    e = os.environ if env is None else env
    missing = [k for k in _REQUIRED if not str(e.get(k, "")).strip()]
    if missing:
        raise ValueError("missing " + ", ".join(missing) + " (copy rustfs.env.example to rustfs.env)")
    secure = str(e.get("DELTA_S3_SECURE") or "true").strip().lower()
    if secure not in ("true", "false"):
        raise ValueError(f"DELTA_S3_SECURE must be 'true' or 'false', got {secure!r}")
    port = str(e.get("DELTA_S3_PORT") or "9000").strip()
    if not port.isdigit():
        raise ValueError(f"DELTA_S3_PORT must be a number, got {port!r}")
    scheme = "https" if secure == "true" else "http"
    return {
        "endpoint": f"{scheme}://{str(e['DELTA_S3_ENDPOINT']).strip()}:{port}",
        "scheme": scheme,
        "bucket": str(e["DELTA_S3_BUCKET"]).strip(),
        "access": str(e["DELTA_S3_ACCESS"]).strip(),
        "secret": str(e["DELTA_S3_SECRET"]).strip(),
    }


def ensure_bucket(cfg: dict) -> bool:
    """Create the bucket if absent. Returns True when it was created now."""
    from pyarrow import fs as pafs

    s3 = pafs.S3FileSystem(
        access_key=cfg["access"],
        secret_key=cfg["secret"],
        endpoint_override=cfg["endpoint"],
        scheme=cfg["scheme"],
        region="us-east-1",
        # Path-style, as openbb-deltalake's storage options ask for
        # (aws_virtual_hosted_style_request=false): `rustfs` is a compose
        # service name, never a <bucket>.<host> DNS name.
        force_virtual_addressing=False,
        allow_bucket_creation=True,
    )
    info = s3.get_file_info(cfg["bucket"])
    if info.type == pafs.FileType.Directory:
        return False
    s3.create_dir(cfg["bucket"])
    return True


def main(argv=None, attempts: int = 60, delay: float = 2.0) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        cfg = settings()
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    last = None
    for _ in range(attempts):
        try:
            created = ensure_bucket(cfg)
            log.info("bucket %s %s", cfg["bucket"], "created" if created else "already exists")
            return 0
        except Exception as exc:  # noqa: BLE001 - the store may still be starting
            last = exc
            time.sleep(delay)
    log.error("the S3 store at %s did not become reachable: %s", cfg["endpoint"], last)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
