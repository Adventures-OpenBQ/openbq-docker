# SPDX-License-Identifier: Apache-2.0
"""Initialize only a fresh, isolated staging bundle inside its candidate image."""

import argparse
import json
import os
from pathlib import Path
import re
import time

_BOOTSTRAP_PHASE = "configuration"


def _env(path):
    result = {}
    for line in path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch("[A-Z][A-Z0-9_]*", key) or key in result:
            raise ValueError("invalid private staging configuration")
        result[key] = value
    return result


def read_configuration(directory):
    from psycopg.conninfo import conninfo_to_dict

    root = Path(directory)
    release = json.loads((root / "release.json").read_text())
    compose = json.loads((root / "compose.staging.yaml").read_text())
    api, worker, admin = [
        _env(root / name) for name in ("api.env", "worker.env", "admin.env")
    ]
    postgres, s3 = [_env(root / name) for name in ("postgres.env", "s3.env")]
    if (
        release.get("platform") != "linux/amd64"
        or release.get("status") != "prepared_not_started"
        or compose.get("name") != "openbq-v11-staging"
        or not compose.get("networks", {}).get("default", {}).get("internal")
    ):
        raise ValueError("fresh isolated amd64 staging configuration required")
    if not re.fullmatch(
        "sha256:[0-9a-f]{64}", release.get("image_id", "")
    ) or not re.fullmatch("[0-9a-f]{40}", release.get("source_commit", "")):
        raise ValueError("immutable source and image required")
    expected = {"postgres", "s3", "temporaldb-api", "temporaldb-worker"}
    if (
        set(compose.get("services", {})) != expected
        or set(compose.get("volumes", {}))
        != {"postgres-data", "s3-data", "archive", "evidence"}
        or any(compose["volumes"].values())
    ):
        raise ValueError("only fresh project-owned services and volumes allowed")
    for name, service in compose["services"].items():
        if (
            service.get("networks")
            or service.get("container_name")
            or service.get("mem_limit", 0) <= 0
        ):
            raise ValueError("bounded internal services required")
        if any(
            not isinstance(p, str) or not p.startswith("127.0.0.1:")
            for p in service.get("ports", [])
        ):
            raise ValueError("loopback-only publication required")
        if any(
            not isinstance(v, str) or v.split(":")[0] not in compose["volumes"]
            for v in service.get("volumes", [])
        ):
            raise ValueError("external or bind-mounted data store refused")
        if name.startswith("temporaldb-") and (
            service.get("image") != release["image_id"]
            or service.get("pull_policy") != "never"
        ):
            raise ValueError("runtime image differs from release receipt")
    if (
        worker.get("TEMPORALDB_ACQUISITION") != "{}"
        or worker.get("TEMPORALDB_IDENTITIES") != "[]"
        or "TEMPORALDB_API_DSN" in worker
        or "TEMPORALDB_WORKER_DSN" in api
    ):
        raise ValueError(
            "bootstrap must not enable acquisition or share control logins"
        )
    catalogs = json.loads(worker["TEMPORALDB_QUERY_CATALOGS"])
    if (
        set(catalogs) != {"hot"}
        or catalogs["hot"].get("metadata_schema") != "hot"
        or catalogs["hot"].get("data_path") != "s3://temporaldb-v11/hot/"
    ):
        raise ValueError("only the new staging catalog is allowed")
    fixed = {
        "TEMPORALDB_S3_ENDPOINT": "http://s3:9000",
        "TEMPORALDB_CAPTURE_BUCKET": "temporaldb-v11",
        "TEMPORALDB_AUDIT_ARCHIVE": "/archive",
        "TEMPORALDB_EVIDENCE_ARCHIVE": "/evidence",
        "TEMPORALDB_AUDIT_ARCHIVE_SHARED": "1",
        "TEMPORALDB_RUNTIME_STAGING": "/run/temporaldb/runtime",
        "TEMPORALDB_EXTENSION_DIRECTORY": "/opt/temporaldb/extensions",
        "TEMPORALDB_ENVIRONMENT_DIGEST": "UNPROVISIONED",
    }
    for values in (api, worker):
        if (
            any(values.get(key) != value for key, value in fixed.items())
            or values.get("AWS_ACCESS_KEY_ID") != s3.get("RUSTFS_ACCESS_KEY")
            or values.get("AWS_SECRET_ACCESS_KEY") != s3.get("RUSTFS_SECRET_KEY")
        ):
            raise ValueError("staging storage or archive identity mismatch")
    if api["TEMPORALDB_QUERY_CATALOGS"] != worker["TEMPORALDB_QUERY_CATALOGS"]:
        raise ValueError("runtime catalog configuration mismatch")
    policy = json.loads(api["TEMPORALDB_SCOPE_POLICY"])
    if len(policy) != 1 or any(
        "permissions" in value or "provider_accounts" in value
        for value in policy.values()
    ):
        raise ValueError("bootstrap cannot provision acquisition grants")
    connections = {
        "owner": admin["TEMPORALDB_MIGRATION_DSN"],
        "api_login": api["TEMPORALDB_API_DSN"],
        "worker_login": worker["TEMPORALDB_WORKER_DSN"],
        "catalog": catalogs["hot"]["dsn"],
    }
    for user, value in connections.items():
        fields = conninfo_to_dict(value)
        if (
            set(fields) - {"host", "port", "dbname", "user", "password"}
            or fields.get("host") != "postgres"
            or fields.get("dbname") != "temporaldb_v11"
            or fields.get("user") != "temporaldb_" + user
            or fields.get("port", "5432") != "5432"
            or not re.fullmatch("[0-9a-f]{64}", fields.get("password", ""))
        ):
            raise ValueError("non-staging database connection refused")
    if (
        postgres.get("POSTGRES_USER") != "temporaldb_owner"
        or postgres.get("POSTGRES_DB") != "temporaldb_v11"
        or postgres.get("POSTGRES_PASSWORD")
        != conninfo_to_dict(connections["owner"])["password"]
    ):
        raise ValueError("owner configuration mismatch")
    return {
        "release": release,
        "api": api,
        "worker": worker,
        "admin": admin,
        "catalogs": catalogs,
        "connections": connections,
    }


def bootstrap(directory):
    global _BOOTSTRAP_PHASE
    import boto3
    from botocore.config import Config
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    from temporaldb.control.db import migrate, Database
    from temporaldb.control.scope import ScopePolicy
    from temporaldb.lake.catalog import CatalogSpec, LakeCatalog, literal
    from temporaldb.lake.schema import AssertionLake
    from temporaldb.query.artifacts import ArtifactStore
    from temporaldb.runtime import IdentityMap, projection_versions

    cfg = read_configuration(directory)
    _BOOTSTRAP_PHASE = "archive_mounts"
    for root in ("/archive", "/evidence"):
        if os.statvfs(root).f_flag & os.ST_RDONLY:
            raise ValueError(
                "bootstrap requires writable fresh archive and evidence mounts"
            )
    _BOOTSTRAP_PHASE = "fresh_database"
    env = cfg["worker"]
    owner = cfg["connections"]["owner"]
    ScopePolicy.from_mapping(json.loads(cfg["api"]["TEMPORALDB_SCOPE_POLICY"]))
    with psycopg.connect(owner) as conn:
        if (
            conn.execute("SELECT to_regclass('control.jobs')").fetchone()[0]
            and conn.execute("SELECT count(*) FROM control.jobs").fetchone()[0]
        ):
            raise ValueError(
                "fresh staging database required; existing jobs are never reset"
            )
    _BOOTSTRAP_PHASE = "migrations"
    migrate(owner)
    with psycopg.connect(owner) as conn:
        for kind in ("api", "worker", "catalog"):
            user = "temporaldb_" + kind + ("_login" if kind != "catalog" else "")
            password = conninfo_to_dict(
                cfg["connections"][kind + "_login" if kind != "catalog" else kind]
            )["password"]
            if not conn.execute(
                "SELECT FROM pg_roles WHERE rolname=%s", (user,)
            ).fetchone():
                statement = sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(user), sql.Literal(password)
                )
                if kind != "catalog":
                    statement += sql.SQL(" IN ROLE {}").format(
                        sql.Identifier("temporaldb_" + kind)
                    )
                conn.execute(statement)
        conn.execute("CREATE SCHEMA IF NOT EXISTS hot AUTHORIZATION temporaldb_catalog")
    _BOOTSTRAP_PHASE = "role_permissions"
    for kind in ("api", "worker"):
        with Database(cfg["connections"][kind + "_login"], role="temporaldb_" + kind):
            pass
    _BOOTSTRAP_PHASE = "object_store"
    client = boto3.client(
        "s3",
        endpoint_url=env["TEMPORALDB_S3_ENDPOINT"],
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env["AWS_DEFAULT_REGION"],
        config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1}),
    )
    try:
        for attempt in range(60):
            try:
                try:
                    client.head_bucket(Bucket=env["TEMPORALDB_CAPTURE_BUCKET"])
                except client.exceptions.ClientError as error:
                    if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                        raise
                    client.create_bucket(Bucket=env["TEMPORALDB_CAPTURE_BUCKET"])
                break
            except Exception:
                if attempt == 59:
                    raise
                time.sleep(1)
    finally:
        client.close()
    _BOOTSTRAP_PHASE = "catalogs"
    specs = {name: CatalogSpec(**value) for name, value in cfg["catalogs"].items()}

    def configure(conn):
        conn.execute(
            "CREATE SECRET staging_s3 (TYPE S3, KEY_ID "
            + literal(env["AWS_ACCESS_KEY_ID"])
            + ", SECRET "
            + literal(env["AWS_SECRET_ACCESS_KEY"])
            + ", REGION 'us-east-1', ENDPOINT 's3:9000', URL_STYLE 'path', USE_SSL false)"
        )

    catalog = LakeCatalog(
        specs,
        extension_directory=Path(env["TEMPORALDB_EXTENSION_DIRECTORY"]),
        configure=configure,
    )
    try:
        for name in specs:
            AssertionLake(catalog, name).initialize()
            catalog.assert_manual_expiry(name)
    finally:
        catalog.close()
    for name in ("/archive/blobs", "/evidence/blobs"):
        Path(name).mkdir(parents=True, exist_ok=True)
    _BOOTSTRAP_PHASE = "runtime_archive"
    archive = ArtifactStore("/archive", staging="/run/temporaldb/runtime")
    digest = archive.archive_current(
        env["TEMPORALDB_EXTENSION_DIRECTORY"], projection_versions(IdentityMap([]))
    )
    _BOOTSTRAP_PHASE = "archive_ownership"
    for root in (Path("/archive"), Path("/evidence")):
        for path in [root, *root.rglob("*")]:
            os.chown(path, 65532, 65532, follow_symlinks=False)
    return {
        "schema_version": 1,
        "status": "initialized_not_started",
        "image_id": cfg["release"]["image_id"],
        "source_commit": cfg["release"]["source_commit"],
        "environment_digest": digest,
        "catalogs": ["hot"],
        "scope_count": 1,
        "provider_acquisition_enabled": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, default=Path("/config"))
    args = parser.parse_args()
    try:
        result = bootstrap(args.configuration)
    except Exception as error:
        import traceback

        frame = traceback.extract_tb(error.__traceback__)[-1]
        location = Path(frame.filename).name + ":" + str(frame.lineno)
        raise SystemExit(
            "staging bootstrap failed during "
            + _BOOTSTRAP_PHASE
            + ": "
            + type(error).__name__
            + " errno="
            + str(getattr(error, "errno", None))
            + " at "
            + location
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
