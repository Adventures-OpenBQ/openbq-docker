"""Explicit quiesced-copy import, checkpoint verification and new legacy generation export."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
from urllib.parse import quote, unquote
import uuid

from .config import connection_info
from .private_state import NAME, valid_json
from .store import checksum, migrate, REVISION, verified_schema, schema_migrations


class Refused(Exception):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused()
        result[key] = value
    return result


def checked_fences(fences):
    if not isinstance(fences, dict) or len(fences) > 256:
        raise Refused()
    for writer, fence in fences.items():
        if not isinstance(fence, dict) or set(fence) != {"sequence", "fingerprint"}:
            raise Refused()
        sequence = fence["sequence"]
        if (not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", writer)
                or type(sequence) is not int or not 1 <= sequence <= 9007199254740991
                or not isinstance(fence["fingerprint"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", fence["fingerprint"])):
            raise Refused()
    return fences


def sqlite_records(path):
    # Quiesced copies must include no live journal/WAL. Immutable mode opens the
    # source read-only and creates neither a journal nor a shared-memory file.
    if any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise Refused()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise Refused()
        if set(conn.execute("SELECT name,type FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")) != {("records", "table"), ("metadata", "table")}:
            raise Refused()
        for table, columns in (("records", ["name", "body", "fences"]), ("metadata", ["key", "value"])):
            if [row[1] for row in conn.execute("PRAGMA table_info(" + table + ")")] != columns:
                raise Refused()
        if conn.execute("SELECT key,value FROM metadata").fetchall() != [("imported", "1")]:
            raise Refused()
        rows = conn.execute("SELECT name,body,fences FROM records ORDER BY name").fetchall()
    if len(rows) > 2000:
        raise Refused()
    result = []
    for name, body, raw_fences in rows:
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(raw_fences, str):
            raise Refused()
        fences = checked_fences(json.loads(raw_fences, object_pairs_hook=unique_object))
        if body is not None:
            if not isinstance(body, str):
                raise Refused()
            body = body.encode("utf-8")
            valid_json(body)
            if len(body) > 262144:
                raise Refused()
        elif not fences:
            raise Refused()
        result.append((name, body, fences))
    return result


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
    documents = {}; source_files = {}; fences = []; authoritative = set()
    for database in sorted(source.glob("state/*/.state.sqlite")):
        if (database.is_symlink() or database.parent.is_symlink() or database.parent.parent.is_symlink()
                or not database.resolve().is_relative_to(source.resolve()) or not database.is_file()
                or not re.fullmatch(r"[0-9]{1,20}", database.parent.name)):
            raise Refused()
        principal = database.parent.name
        authoritative.add(principal)
        for name, raw, versions in sqlite_records(database):
            if raw is not None:
                documents[("github", principal, name)] = raw
            fences.extend(["github", principal, name, writer, fence["sequence"], fence["fingerprint"]]
                          for writer, fence in versions.items())
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
        if re.fullmatch(r"state/[0-9]{1,20}/\.state\.sqlite", relative):
            continue
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
            if browser[1] in authoritative:
                continue  # Old JSON is retained by the one-time SQLite import.
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
    if fences:
        manifest["fences"] = sorted(fences)
    return documents, manifest


def document_manifest(documents):
    return [[*key, len(raw), sha256(raw).hexdigest()] for key, raw in sorted(documents.items())]


def read_target(conn):
    return {(ns, principal, key): bytes(raw) for ns, principal, key, raw in conn.execute(
        "SELECT namespace,principal_id,document_key,body_bytes FROM settings.documents ORDER BY namespace,principal_id,document_key")}


def read_fences(conn):
    return [list(row) for row in conn.execute("""SELECT namespace,principal_id,document_key,
        writer,sequence,fingerprint FROM settings.state_fences
        ORDER BY namespace,principal_id,document_key,writer""")]


def import_copy(conn, documents, manifest, verify=False):
    from psycopg.types.json import Jsonb
    run_id = sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    conn.execute("SELECT pg_advisory_xact_lock(74182951001)")
    conn.execute("LOCK TABLE settings.principals, settings.documents, settings.state_fences IN SHARE ROW EXCLUSIVE MODE")
    existing = conn.execute("SELECT manifest,target_manifest FROM settings_admin.checkpoints WHERE run_id=%s", (run_id,)).fetchone()
    checkpoint_manifest = manifest
    # A verified 001 checkpoint remains immutable after an additive schema
    # upgrade. Recognize its exact old manifest only for an unchanged JSON
    # source/target without fences; never re-label or rewrite that checkpoint.
    if not existing and not manifest.get("fences"):
        old_manifest = {**manifest, "revision": "settings-001", "schema_checksum": schema_migrations()[0][1]}
        old_manifest.pop("fences", None)
        old_id = sha256(json.dumps(old_manifest, sort_keys=True).encode()).hexdigest()
        old = conn.execute("SELECT manifest,target_manifest FROM settings_admin.checkpoints WHERE run_id=%s", (old_id,)).fetchone()
        if old:
            existing, run_id, checkpoint_manifest = old, old_id, old_manifest
    actual = document_manifest(read_target(conn))
    actual_fences = read_fences(conn)
    fences = manifest.get("fences", [])
    principals = set(conn.execute("SELECT namespace,principal_id FROM settings.principals").fetchall())
    expected_principals = {(ns, principal) for ns, principal, _ in documents} | {(row[0], row[1]) for row in fences}
    if existing:
        if principals != expected_principals:
            raise Refused()
        if existing != (checkpoint_manifest, actual) or actual != manifest["documents"] or actual_fences != fences:
            raise Refused()
        return run_id
    if verify or actual or actual_fences or principals or conn.execute("SELECT count(*) FROM settings_admin.checkpoints").fetchone()[0]:
        raise Refused()
    for namespace, principal in expected_principals:
        conn.execute("INSERT INTO settings.principals VALUES (%s,%s) ON CONFLICT DO NOTHING", (namespace, principal))
    for (namespace, principal, key), raw in documents.items():
        conn.execute("INSERT INTO settings.documents(namespace,principal_id,document_key,body_bytes,revision) VALUES (%s,%s,%s,%s,1)", (namespace, principal, key, raw))
    for row in fences:
        conn.execute("INSERT INTO settings.state_fences(namespace,principal_id,document_key,writer,sequence,fingerprint) VALUES(%s,%s,%s,%s,%s,%s)", row)
    actual = document_manifest(read_target(conn))
    if actual != manifest["documents"] or read_fences(conn) != fences:
        raise Refused()
    conn.execute("INSERT INTO settings_admin.checkpoints(run_id,manifest,target_manifest) VALUES(%s,%s,%s)", (run_id, Jsonb(manifest), Jsonb(actual)))
    return run_id


def export_copy(conn, destination, identities):
    if destination.exists() or destination.is_symlink():
        raise Refused()
    # Documents and tombstones/fences must share one MVCC snapshot even when
    # the caller's connection uses PostgreSQL's default READ COMMITTED mode.
    documents = {}; fences = []
    for ns, principal, key, raw, writer, sequence, fingerprint in conn.execute("""
        SELECT namespace,principal_id,document_key,body_bytes,NULL::text,NULL::bigint,NULL::text FROM settings.documents
        UNION ALL SELECT namespace,principal_id,document_key,NULL::bytea,writer,sequence,fingerprint FROM settings.state_fences"""):
        if writer is None:
            documents[(ns, principal, key)] = bytes(raw)
        else:
            fences.append([ns, principal, key, writer, sequence, fingerprint])
    fences.sort()
    fenced_principals = {row[1] for row in fences}
    reverse = {principal: stem for stem, principal in identities.items()}
    temporary = Path(tempfile.mkdtemp(prefix=".settings-export-", dir=destination.parent))
    try:
        for (namespace, principal, key), raw in documents.items():
            if namespace == "key":
                if principal not in reverse or key not in ("settings", "dashboards", "apps"):
                    raise Refused()
                path = temporary / "keys" / (reverse[principal] + ("" if key == "settings" else "." + key) + ".json")
            elif namespace == "github" and re.fullmatch(r"[0-9]{1,20}", principal) and NAME.fullmatch(key):
                if principal in fenced_principals:
                    continue
                path = temporary / "state" / principal / quote(key, safe="-_.!~*'()")
            else:
                raise Refused()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("xb") as output:
                os.chmod(path, 0o600); output.write(raw); output.flush(); os.fsync(output.fileno())
        for principal in sorted(fenced_principals):
            if not re.fullmatch(r"[0-9]{1,20}", principal):
                raise Refused()
            directory = temporary / "state" / principal
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / ".state.sqlite"
            with sqlite3.connect(path) as database:
                os.chmod(path, 0o600)
                database.executescript("CREATE TABLE records(name TEXT PRIMARY KEY,body TEXT,fences TEXT NOT NULL);"
                                       "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);"
                                       "INSERT INTO metadata VALUES('imported','1');")
                versions = {}
                for ns, owner, key, writer, sequence, fingerprint in fences:
                    if ns != "github":
                        raise Refused()
                    if owner == principal:
                        versions.setdefault(key, {})[writer] = {"sequence": sequence, "fingerprint": fingerprint}
                names = set(versions) | {key for ns, owner, key in documents if ns == "github" and owner == principal}
                for key in sorted(names):
                    raw = documents.get(("github", principal, key))
                    body = raw.decode("utf-8") if raw is not None else None
                    database.execute("INSERT INTO records VALUES(?,?,?)", (key, body, json.dumps(versions.get(key, {}))))
        copied, copied_manifest = inventory(temporary, identities)
        if document_manifest(copied) != document_manifest(documents) or copied_manifest.get("fences", []) != fences:
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
            if not verified_schema(conn):
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
