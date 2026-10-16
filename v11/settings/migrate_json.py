"""Explicit quiesced-copy import, checkpoint verification and new legacy generation export."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import quote, unquote
import uuid

from .config import connection_info, SettingsUnavailable
from .private_state import NAME, valid_json
from .store import checksum, migrate, REVISION


class Refused(Exception):
    pass


def mapping(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refused()
            result[key] = value
        return result
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict) or not value or any(
        not re.fullmatch(r"[0-9a-f]{64}", stem) or str(uuid.UUID(principal)) != principal
        for stem, principal in value.items()
    ) or len(set(value.values())) != len(value):
        raise Refused()
    return value


def records_shape(key, raw):
    # Match the legacy reader's UTF-8 text contract, including BOM refusal.
    # Inventory and export verification must never bless unreadable key bytes.
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise Refused()
    if key == "settings":
        return
    for name, record in value.items():
        if name != "docks" and str(uuid.UUID(name)) != name:
            raise Refused()
        if name == "docks" and key != "dashboards":
            raise Refused()
        if not isinstance(record, dict) or not isinstance(record.get("content"), dict) or not all(
            isinstance(record.get(k), str) for k in ("created_date", "updated_date")
        ):
            raise Refused()
        if name == "docks" and (record.get("hidden") is not True or type(record.get("revision")) is not int or record["revision"] < 0):
            raise Refused()


def inventory(source, identities, exclude_temp=False):
    if source.is_symlink() or not source.is_dir():
        raise Refused()
    documents = {}; source_files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise Refused()
        relative = path.relative_to(source).as_posix()
        if path.is_dir():
            if relative not in ("keys", "state") and not re.fullmatch(r"state/[0-9]{1,20}", relative):
                raise Refused()
            continue
        if not path.is_file():
            raise Refused()
        raw = path.read_bytes()
        source_files[relative] = [len(raw), sha256(raw).hexdigest()]
        key_match = re.fullmatch(r"keys/([0-9a-f]{64})(\.(dashboards|apps))?\.json", relative)
        browser = re.fullmatch(r"state/([0-9]{1,20})/([^/]+)", relative)
        if key_match:
            stem, _, family = key_match.groups()
            if stem not in identities:
                raise Refused()
            key = family or "settings"
            records_shape(key, raw)
            target = ("key", identities[stem], key)
        elif browser and NAME.fullmatch(unquote(browser[2])):
            name = unquote(browser[2], errors="strict")
            if quote(name, safe="-_.!~*'()") != browser[2]:
                raise Refused()
            valid_json(raw)
            if len(raw) > 262144:
                raise Refused()
            target = ("github", browser[1], name)
        elif exclude_temp and (re.fullmatch(r"state/[0-9]{1,20}/\.tmp-[0-9a-f]{16}", relative) or
                               re.fullmatch(r"keys/[0-9a-f]{64}(?:\.(?:dashboards|apps))?\.json\.[0-9]+\.tmp", relative)):
            continue
        else:
            raise Refused()
        if target in documents:
            raise Refused()
        documents[target] = raw
    totals = {}
    for (namespace, principal, _), raw in documents.items():
        if namespace == "github":
            size, count = totals.get(principal, (0, 0))
            totals[principal] = (size + len(raw), count + 1)
    if any(size > 2097152 or count > 200 for size, count in totals.values()):
        raise Refused()
    manifest = {"revision": REVISION, "schema_checksum": checksum(), "mapping": identities,
                "source": source_files, "documents": document_manifest(documents)}
    return documents, manifest


def document_manifest(documents):
    return [[*key, len(raw), sha256(raw).hexdigest()] for key, raw in sorted(documents.items())]


def read_target(conn):
    return {(ns, principal, key): bytes(raw) for ns, principal, key, raw in conn.execute(
        "SELECT namespace,principal_id,document_key,body_bytes FROM settings.documents ORDER BY namespace,principal_id,document_key")}


def import_copy(conn, documents, manifest, verify=False):
    from psycopg.types.json import Jsonb
    run_id = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    conn.execute("SELECT pg_advisory_xact_lock(74182951001)")
    conn.execute("LOCK TABLE settings.principals, settings.documents IN SHARE ROW EXCLUSIVE MODE")
    existing = conn.execute("SELECT manifest,target_manifest FROM settings_admin.checkpoints WHERE run_id=%s", (run_id,)).fetchone()
    actual = document_manifest(read_target(conn))
    principals = set(conn.execute("SELECT namespace,principal_id FROM settings.principals").fetchall())
    expected_principals = {(ns, principal) for ns, principal, _ in documents}
    if existing:
        if principals != expected_principals:
            raise Refused()
        if existing != (manifest, actual) or actual != manifest["documents"]:
            raise Refused()
        return run_id
    if verify or actual or principals or conn.execute("SELECT count(*) FROM settings_admin.checkpoints").fetchone()[0]:
        raise Refused()
    for (namespace, principal, key), raw in documents.items():
        conn.execute("INSERT INTO settings.principals VALUES (%s,%s) ON CONFLICT DO NOTHING", (namespace, principal))
        conn.execute("INSERT INTO settings.documents(namespace,principal_id,document_key,body_bytes,revision) VALUES (%s,%s,%s,%s,1)", (namespace, principal, key, raw))
    actual = document_manifest(read_target(conn))
    if actual != manifest["documents"]:
        raise Refused()
    conn.execute("INSERT INTO settings_admin.checkpoints(run_id,manifest,target_manifest) VALUES(%s,%s,%s)", (run_id, Jsonb(manifest), Jsonb(actual)))
    return run_id


def export_copy(conn, destination, identities):
    if destination.exists() or destination.is_symlink():
        raise Refused()
    documents = read_target(conn)
    reverse = {principal: stem for stem, principal in identities.items()}
    temporary = Path(tempfile.mkdtemp(prefix=".settings-export-", dir=destination.parent))
    try:
        for (namespace, principal, key), raw in documents.items():
            if namespace == "key":
                if principal not in reverse or key not in ("settings", "dashboards", "apps"):
                    raise Refused()
                path = temporary / "keys" / (reverse[principal] + ("" if key == "settings" else "." + key) + ".json")
            elif namespace == "github" and re.fullmatch(r"[0-9]{1,20}", principal) and NAME.fullmatch(key):
                path = temporary / "state" / principal / quote(key, safe="-_.!~*'()")
            else:
                raise Refused()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("xb") as output:
                os.chmod(path, 0o600); output.write(raw); output.flush(); os.fsync(output.fileno())
        copied, _ = inventory(temporary, identities)
        if document_manifest(copied) != document_manifest(documents):
            raise Refused()
        # Destination is a newly chosen generation; never replace an old store.
        if destination.exists():
            raise Refused()
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return len(documents)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("migrate", "inventory", "import", "verify", "export-legacy"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--quiesced-copy", action="store_true")
    parser.add_argument("--exclude-temp", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "migrate":
            migrate(connection_info(os.environ["OPENBQ_SETTINGS_MIGRATION_DSN"]))
            print(json.dumps({"revision": REVISION, "checksum": checksum()})); return 0
        if not args.quiesced_copy:
            raise Refused()
        identities = mapping(args.mapping)
        if args.command != "export-legacy":
            documents, manifest = inventory(args.source, identities, args.exclude_temp)
            if args.command == "inventory":
                print(json.dumps({"documents": len(documents), "bytes": sum(map(len, documents.values())),
                                  "fingerprint": sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()})); return 0
        import psycopg
        with psycopg.connect(connection_info(os.environ["OPENBQ_SETTINGS_MIGRATION_DSN"])) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            if conn.execute("SELECT revision,checksum FROM settings_admin.schema_migrations").fetchall() != [(REVISION, checksum())]:
                raise Refused()
            if args.command == "export-legacy":
                # All rows are read by one statement, a single MVCC snapshot.
                count = export_copy(conn, args.destination, identities)
                print(json.dumps({"exported": count})); return 0
            run_id = import_copy(conn, documents, manifest, args.command == "verify")
        print(json.dumps({"run_id": run_id, "documents": len(documents)})); return 0
    except Exception:
        print("Settings migration refused", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
