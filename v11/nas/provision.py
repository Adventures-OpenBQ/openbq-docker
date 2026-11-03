# SPDX-License-Identifier: Apache-2.0
"""Prepare a fresh private staging bundle; no remote mutation or startup."""

import argparse
import json
from pathlib import Path
import re
import secrets
from uuid import uuid4

POSTGRES = "postgres:16.11-alpine@sha256:4327b9fd295502f326f44153a1045a7170ddbfffed1c3829798328556cfd09e2"
RUSTFS = "rustfs/rustfs:1.0.1@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c"
MIB = 1024 * 1024


def _env(values):
    return "".join(key + "=" + value + "\n" for key, value in values.items())


def prepare_bundle(output, release_receipt, *, port=18088):
    image = release_receipt.get("image_id")
    source = release_receipt.get("source_commit")
    if (
        release_receipt.get("platform") != "linux/amd64"
        or not isinstance(image, str)
        or not re.fullmatch("sha256:[0-9a-f]{64}", image)
        or not isinstance(source, str)
        or not re.fullmatch("[0-9a-f]{40}", source)
    ):
        raise ValueError("immutable amd64 artifact and full source commit required")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("explicit unprivileged loopback port required")
    out = Path(output)
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    secret = {
        key: secrets.token_hex(32)
        for key in (
            "owner",
            "api",
            "worker",
            "catalog",
            "access",
            "s3",
            "cursor",
            "token",
        )
    }

    def dsn(user):
        return (
            "host=postgres dbname=temporaldb_v11 user=temporaldb_"
            + (user + "_login" if user in {"api", "worker"} else user)
            + " password="
            + secret[user]
        )

    catalog = {
        "hot": {
            "dsn": dsn("catalog"),
            "metadata_schema": "hot",
            "data_path": "s3://temporaldb-v11/hot/",
        }
    }
    common = {
        "TEMPORALDB_CAPTURE_BUCKET": "temporaldb-v11",
        "TEMPORALDB_CURSOR_KEY": secret["cursor"],
        "TEMPORALDB_ENVIRONMENT_DIGEST": "UNPROVISIONED",
        "TEMPORALDB_AUDIT_ARCHIVE": "/archive",
        "TEMPORALDB_AUDIT_ARCHIVE_SHARED": "1",
        "TEMPORALDB_EVIDENCE_ARCHIVE": "/evidence",
        "TEMPORALDB_EXTENSION_DIRECTORY": "/opt/temporaldb/extensions",
        "TEMPORALDB_RUNTIME_STAGING": "/run/temporaldb/runtime",
        "TEMPORALDB_GOLD_SCRATCH_DIRECTORY": "/run/temporaldb/gold",
        "TEMPORALDB_GOLD_SCRATCH_LIMIT_BYTES": str(192 * MIB),
        "TEMPORALDB_QUERY_CATALOGS": json.dumps(catalog, separators=(",", ":")),
        "TEMPORALDB_WRITE_CATALOG": "hot",
        "TEMPORALDB_IDENTITIES": "[]",
        "TEMPORALDB_S3_ENDPOINT": "http://s3:9000",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": secret["access"],
        "AWS_SECRET_ACCESS_KEY": secret["s3"],
    }
    scope = {
        secret["token"]: {
            "workspace_id": str(uuid4()),
            "principal_id": "staging-operator",
            "entitlement_id": "v11-staging",
            "entitlements": ["v11-staging"],
        }
    }
    api = common | {
        "TEMPORALDB_API_DSN": dsn("api"),
        "TEMPORALDB_SCOPE_POLICY": json.dumps(scope, separators=(",", ":")),
    }
    worker = common | {
        "TEMPORALDB_WORKER_DSN": dsn("worker"),
        "TEMPORALDB_ACQUISITION": "{}",
    }
    runtime = {
        "image": image,
        "platform": "linux/amd64",
        "pull_policy": "never",
        "read_only": True,
        "restart": "unless-stopped",
        "pids_limit": 256,
        "cpus": 1,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": [
            "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777",
            "/run/temporaldb/runtime:rw,exec,nosuid,nodev,size=1073741824,mode=1777",
            "/run/temporaldb/gold:rw,noexec,nosuid,nodev,size=268435456,uid=65532,gid=65532,mode=0700",
        ],
        "depends_on": {
            "postgres": {"condition": "service_healthy"},
            "s3": {"condition": "service_started"},
        },
    }
    compose = {
        "name": "openbq-v11-staging",
        "services": {
            "postgres": {
                "image": POSTGRES,
                "platform": "linux/amd64",
                "env_file": ["postgres.env"],
                "mem_limit": 512 * MIB,
                "cpus": 0.5,
                "pids_limit": 128,
                "restart": "unless-stopped",
                "volumes": ["postgres-data:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        "pg_isready -U temporaldb_owner -d temporaldb_v11",
                    ],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 24,
                },
            },
            "s3": {
                "image": RUSTFS,
                "platform": "linux/amd64",
                "env_file": ["s3.env"],
                "user": "0:0",
                "mem_limit": 512 * MIB,
                "cpus": 0.5,
                "pids_limit": 128,
                "restart": "unless-stopped",
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "volumes": ["s3-data:/data"],
            },
            "temporaldb-api": runtime
            | {
                "mem_limit": 1024 * MIB,
                "env_file": ["api.env"],
                "command": ["python", "-m", "temporaldb.api.app"],
                "volumes": ["archive:/archive:ro", "evidence:/evidence:rw"],
                "ports": ["127.0.0.1:" + str(port) + ":8080"],
            },
            "temporaldb-worker": runtime
            | {
                "mem_limit": 2048 * MIB,
                "env_file": ["worker.env"],
                "command": ["python", "-m", "temporaldb.worker.runner"],
                "volumes": ["archive:/archive:ro", "evidence:/evidence:ro"],
            },
        },
        "networks": {"default": {"internal": True}},
        "volumes": {
            name: {} for name in ("postgres-data", "s3-data", "archive", "evidence")
        },
    }
    files = {
        "compose.staging.yaml": json.dumps(compose, indent=2) + "\n",
        "api.env": _env(api),
        "worker.env": _env(worker),
        "admin.env": _env({"TEMPORALDB_MIGRATION_DSN": dsn("owner")}),
        "postgres.env": _env(
            {
                "POSTGRES_DB": "temporaldb_v11",
                "POSTGRES_USER": "temporaldb_owner",
                "POSTGRES_PASSWORD": secret["owner"],
            }
        ),
        "s3.env": _env(
            {
                "RUSTFS_ACCESS_KEY": secret["access"],
                "RUSTFS_SECRET_KEY": secret["s3"],
                "RUSTFS_VOLUMES": "/data",
                "RUSTFS_ADDRESS": "0.0.0.0:9000",
                "RUSTFS_CONSOLE_ENABLE": "false",
            }
        ),
        "release.json": json.dumps(
            {
                "schema_version": 1,
                "image_id": image,
                "source_commit": source,
                "platform": "linux/amd64",
                "status": "prepared_not_started",
                "provisioning_required": True,
            },
            indent=2,
        )
        + "\n",
    }
    for name, content in files.items():
        path = out / name
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            stream.write(content)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18088)
    args = parser.parse_args()
    prepare_bundle(
        args.output, json.loads(args.release_receipt.read_text()), port=args.port
    )
    print(json.dumps({"status": "prepared_not_started", "bundle": str(args.output)}))


if __name__ == "__main__":
    main()
