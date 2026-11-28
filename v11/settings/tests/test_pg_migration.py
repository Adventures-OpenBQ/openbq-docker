"""Additive schema and state migration on explicitly disposable PostgreSQL DBs."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from openbq_settings_pg.config import Config, SettingsUnavailable
from openbq_settings_pg.migrate_json import inventory, import_copy, export_copy, Refused, read_fences
from openbq_settings_pg.store import Store, migrate, SCHEMA, schema_migrations
from openbq_settings_pg.state_version import StateVersion

WRITER = "11111111-1111-4111-8111-111111111111"
MAPPING = {"a" * 64: "aaaaaaaa-1111-4111-8111-111111111111"}


@unittest.skipUnless(os.environ.get("OPENBQ_TEST_SETTINGS_ADMIN_DSN"), "requires an isolated PostgreSQL fixture")
class PostgreSQLMigration(unittest.TestCase):
    def setUp(self):
        self.name = "main_state_test_" + uuid.uuid4().hex[:12]
        self.admin = os.environ["OPENBQ_TEST_SETTINGS_ADMIN_DSN"]
        with psycopg.connect(self.admin, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER openbq_settings_owner").format(sql.Identifier(self.name)))
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(self.name)))
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO openbq_settings_migrator,openbq_settings_runtime").format(sql.Identifier(self.name)))
        self.addCleanup(self.drop)
        self.owner = make_conninfo(os.environ["OPENBQ_TEST_SETTINGS_MIGRATION_DSN"], dbname=self.name)
        self.runtime = make_conninfo(os.environ["OPENBQ_TEST_SETTINGS_DSN"], dbname=self.name)
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.source = Path(self.root.name) / "source"
        self.directory = self.source / "state" / "00042"
        self.directory.mkdir(parents=True)

    def drop(self):
        with psycopg.connect(self.admin, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(self.name)))

    def store(self):
        store = Store(Config(self.runtime, MAPPING["a"*64], True, "synthetic_state_fixture_token_123456"))
        self.addCleanup(store.close)
        store.verify()
        return store

    def test_upgrade_preserves_original_schema_checksums_documents_and_runtime_privileges(self):
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            conn.execute(SCHEMA.read_text())
            conn.execute("INSERT INTO settings_admin.schema_migrations VALUES (%s,%s)", schema_migrations()[0])
            conn.execute("INSERT INTO settings.principals VALUES ('github','00042')")
            conn.execute("INSERT INTO settings.documents(namespace,principal_id,document_key,body_bytes,revision) VALUES ('github','00042','settings.json',%s,7)", (b' {"original":true} ',))
        migrate(self.owner)
        migrate(self.owner)
        store = self.store()
        self.assertEqual(store.files("00042"), {"settings.json": ' {"original":true} '})
        self.assertEqual(store.state("00042", "settings.json", b'{}', StateVersion(WRITER, 2)), 204)
        with psycopg.connect(self.runtime) as conn:
            self.assertEqual(conn.execute("SELECT revision,checksum FROM settings_admin.schema_migrations ORDER BY revision").fetchall(), schema_migrations())
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE TABLE settings.forbidden(x int)")

    def test_unknown_or_changed_migration_refuses_upgrade_without_extra_schema(self):
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            conn.execute(SCHEMA.read_text())
            conn.execute("INSERT INTO settings_admin.schema_migrations VALUES ('settings-001','wrong')")
        with self.assertRaises(SettingsUnavailable): migrate(self.owner)
        with psycopg.connect(self.owner) as conn:
            self.assertIsNone(conn.execute("SELECT to_regclass('settings.state_fences')").fetchone()[0])

    def test_original_checkpoint_survives_additive_upgrade_without_being_rewritten(self):
        migrate(self.owner)
        (self.directory / "settings.json").write_bytes(b' {"saved":true} ')
        documents, manifest = inventory(self.source, MAPPING)
        old_manifest = {**manifest, "revision": "settings-001", "schema_checksum": schema_migrations()[0][1]}
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            old_id = import_copy(conn, documents, old_manifest)
            before = conn.execute("SELECT * FROM settings_admin.checkpoints").fetchall()
            self.assertEqual(import_copy(conn, documents, manifest, verify=True), old_id)
            self.assertEqual(conn.execute("SELECT * FROM settings_admin.checkpoints").fetchall(), before)

    def test_import_export_retry_checkpoint_and_deleted_only_identity_keep_fences(self):
        migrate(self.owner)
        fingerprint = sha256(b"DELETE").hexdigest()
        with sqlite3.connect(self.directory / ".state.sqlite") as conn:
            conn.executescript("CREATE TABLE records(name TEXT PRIMARY KEY,body TEXT,fences TEXT NOT NULL);CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);INSERT INTO metadata VALUES('imported','1');")
            conn.execute("INSERT INTO records VALUES('layouts/a.json',NULL,?)", (json.dumps({WRITER: {"sequence": 4, "fingerprint": fingerprint}}),))
        documents, manifest = inventory(self.source, MAPPING)
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            run = import_copy(conn, documents, manifest)
            self.assertEqual(import_copy(conn, documents, manifest, verify=True), run)
            destination = Path(self.root.name) / "export"
            self.assertEqual(export_copy(conn, destination, MAPPING), 0)
            copied, copied_manifest = inventory(destination, MAPPING)
            self.assertEqual(copied, documents)
            self.assertEqual(copied_manifest["fences"], manifest["fences"])
            # Exercise the actual legacy gateway implementation against the
            # exported database, rather than trusting a Python-only round trip.
            module = Path(__file__).resolve().parents[3] / "funnel-gateway/state-local.mjs"
            script = """import {pathToFileURL} from 'node:url';
const {readState,commitState}=await import(pathToFileURL(process.argv[1]));
const directory=process.argv[2],writer=process.argv[3];
console.log(JSON.stringify([readState(directory),
commitState(directory,'layouts/a.json','{}',{writer,sequence:3}),
commitState(directory,'layouts/a.json',null,{writer,sequence:4}),
commitState(directory,'layouts/a.json','{}',null)]));"""
            answer = subprocess.run(["node", "--input-type=module", "-e", script, str(module),
                                     str(destination / "state/00042"), WRITER], check=True,
                                    capture_output=True, text=True)
            self.assertEqual(json.loads(answer.stdout), [{}, 409, 204, 409])
        store = self.store()
        self.assertEqual(store.state("00042", "layouts/a.json", b'{}', StateVersion(WRITER, 3)), 409)
        self.assertEqual(store.state("00042", "layouts/a.json", None, StateVersion(WRITER, 4)), 204)
        self.assertEqual(store.state("00042", "layouts/a.json", b'{}'), 409)
        self.assertEqual(store.state("00042", "layouts/a.json", b'{}', StateVersion(WRITER, 5)), 204)
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            with self.assertRaises(Refused): import_copy(conn, documents, manifest, verify=True)

    def test_export_keeps_raw_unversioned_bytes_and_refuses_lossy_fenced_text(self):
        migrate(self.owner)
        store = self.store()
        raw = b' "\xff" '
        self.assertEqual(store.state("00042", "settings.json", raw), 204)
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            destination = Path(self.root.name) / "raw-export"
            export_copy(conn, destination, MAPPING)
            self.assertEqual(inventory(destination, MAPPING)[0][("github", "00042", "settings.json")], raw)
        self.assertEqual(store.state("00042", "settings.json", raw, StateVersion(WRITER, 1)), 204)
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            destination = Path(self.root.name) / "refused-export"
            with self.assertRaises(UnicodeError): export_copy(conn, destination, MAPPING)
            self.assertFalse(destination.exists())

    def test_writer_and_tombstone_limits_do_not_advance_refused_fences(self):
        migrate(self.owner)
        fingerprint = sha256(b"DELETE").hexdigest()
        writers = [str(uuid.uuid4()) for _ in range(256)]
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            conn.execute("INSERT INTO settings.principals VALUES ('github','00042')")
            with conn.cursor().copy("COPY settings.state_fences(namespace,principal_id,document_key,writer,sequence,fingerprint) FROM STDIN") as copy:
                for writer in writers:
                    copy.write_row(("github", "00042", "settings.json", writer, 1, fingerprint))
                for index in range(1999):
                    copy.write_row(("github", "00042", f"dashboards/d{index}.json", WRITER, 1, fingerprint))
        store = self.store()
        self.assertEqual(store.state("00042", "settings.json", b'{}', StateVersion(WRITER, 2)), 413)
        self.assertEqual(store.state("00042", "layouts/new.json", None, StateVersion(WRITER, 2)), 413)
        self.assertEqual(store.state("00042", "settings.json", b'{}', StateVersion(writers[0], 2)), 204)
        self.assertEqual(store.state("00042", "layouts/new.json", b'{}'), 413)
        self.assertEqual(store.state("00042", "dashboards/d0.json", None, StateVersion(WRITER, 1)), 204)

    def test_manifest_fence_order_is_portable_across_database_text_collations(self):
        migrate(self.owner)
        with psycopg.connect(self.owner) as conn:
            conn.execute("SET ROLE openbq_settings_owner")
            collation = conn.execute("SELECT collname FROM pg_collation WHERE collprovider='i' ORDER BY collname LIMIT 1").fetchone()
            if collation is None:
                self.skipTest("fixture PostgreSQL has no ICU collation")
            conn.execute(sql.SQL("ALTER TABLE settings.state_fences ALTER COLUMN document_key TYPE text COLLATE {}").format(sql.Identifier(collation[0])))
            conn.execute("INSERT INTO settings.principals VALUES ('github','00042')")
            fingerprint = sha256(b"DELETE").hexdigest()
            for key in ["layouts/A.json", "layouts/a.json", "layouts/a_b.json", "layouts/a-b.json"]:
                conn.execute("INSERT INTO settings.state_fences VALUES ('github','00042',%s,%s,1,%s)", (key, WRITER, fingerprint))
            database_order = [list(row) for row in conn.execute("SELECT namespace,principal_id,document_key,writer,sequence,fingerprint FROM settings.state_fences ORDER BY namespace,principal_id,document_key,writer")]
            self.assertNotEqual(database_order, sorted(database_order), "fixture must exercise non-codepoint ordering")
            self.assertEqual(read_fences(conn), sorted(database_order))


if __name__ == "__main__": unittest.main()
