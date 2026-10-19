# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Exact-schema offline CLI safeguards, using real generated full schemas."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "workspace/postgres/migrate_workspace.py"


class PostgreSQLCheckRenderingTests(unittest.TestCase):
    def test_only_reviewed_dump_restore_equivalent_checks_are_normalized(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('workspace_check_probe',CLI)
        raw=importlib.util.module_from_spec(spec);spec.loader.exec_module(raw)
        original="share_widgets::text = ANY (ARRAY['public'::character varying, 'private'::character varying]::text[])"
        restored="share_widgets::text = ANY (ARRAY['public'::character varying::text, 'private'::character varying::text])"
        names={'entity_entitlement':'check_share_widgets_values_entity_entitlements',
               'default_tier':'check_share_widgets_values_tier_defaults',
               'entitlement':'check_share_widgets_values_entitlements'}
        for table,name in names.items():
            for expression in (original,restored):
                check={'comment':None,'name':name,'sqltext':expression}
                self.assertEqual(raw.canonical_postgres_checks(table,[check]),[dict(check,sqltext=original)])
            for expression in (restored.replace("'private'","'other'"),restored.replace('= ANY','<> ALL'),restored+' OR true'):
                check={'comment':None,'name':name,'sqltext':expression}
                self.assertEqual(raw.canonical_postgres_checks(table,[check]),[check])
            for altered_table,altered_name in (('other',name),(table,name+'_other')):
                check={'comment':None,'name':altered_name,'sqltext':restored}
                self.assertEqual(raw.canonical_postgres_checks(altered_table,[check]),[check])


class PlaintextRefusalTests(unittest.TestCase):
    def test_missing_ca_refuses_plaintext_target_without_opt_out(self):
        import importlib.util
        from unittest import mock
        spec=importlib.util.spec_from_file_location('workspace_tls_probe',CLI)
        raw=importlib.util.module_from_spec(spec);spec.loader.exec_module(raw)
        environment={'WORKSPACE_TARGET_DSN':'postgresql://fixture@database/fixture'}
        with mock.patch.dict(os.environ,environment,clear=True):
            with self.assertRaisesRegex(ValueError,'WORKSPACE_POSTGRES_ALLOW_PLAINTEXT'):
                raw.pg_engine()


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = Path(os.environ["WORKSPACE_FIXTURE"])
        self.temp = tempfile.TemporaryDirectory(prefix="workspace-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.db"
        shutil.copyfile(self.fixture / "schema-9b1d0c5e7a42.db", self.source)

    def run_cli(self, action, *args):
        return subprocess.run([sys.executable, str(CLI), action, "--root", str(self.root),
            "--source", str(self.source), *map(str,args)], capture_output=True, text=True)

    def test_inventory_accepts_both_full_supported_schemas_without_mutation(self):
        for revision, count in (("0d4a342f4c26",53),("9b1d0c5e7a42",54)):
            shutil.copyfile(self.fixture / ("schema-" + revision + ".db"), self.source)
            before = self.source.read_bytes()
            result = self.run_cli("inventory")
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["revision"], revision)
            self.assertEqual(data["table_count"], count)
            self.assertEqual(before, self.source.read_bytes())

    def test_revision_alone_does_not_accept_schema_drift(self):
        for sql in ('ALTER TABLE user ADD COLUMN unrecognized TEXT',
                    'CREATE TABLE extra(uuid TEXT)',
                    'CREATE VIEW unrecognized_view AS SELECT uuid FROM user',
                    'CREATE TRIGGER unrecognized_trigger AFTER UPDATE ON user BEGIN SELECT 1; END',
                    'CREATE INDEX unrecognized_index ON user(email)',
                    "UPDATE alembic_version SET version_num='unknown'"):
            shutil.copyfile(self.fixture / "schema-9b1d0c5e7a42.db", self.source)
            with sqlite3.connect(self.source) as db:
                db.execute(sql)
            db.close()
            before = self.source.read_bytes()
            result = self.run_cli("snapshot", "--quiesced", "--output", self.root / "snapshot.db")
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / "snapshot.db").exists())
            self.assertEqual(before, self.source.read_bytes())

    def test_parent_traversal_and_manifest_symlink_are_refused(self):
        outside=self.root.parent/(self.root.name+'-outside.db')
        shutil.copyfile(self.source,outside)
        self.addCleanup(outside.unlink)
        result=self.run_cli('inventory','--source',self.root/'..'/outside.name)
        self.assertNotEqual(result.returncode,0,'parent traversal escaped approved root')
        link=self.root/'manifest.json'
        link.symlink_to(CLI.with_name('schema_manifest.json'))
        self.assertNotEqual(self.run_cli('inventory','--manifest',link).returncode,0)

    def test_custom_manifest_cannot_bless_an_unknown_schema(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('workspace_manifest_probe',CLI)
        raw=importlib.util.module_from_spec(spec);spec.loader.exec_module(raw)
        manifest=json.loads(CLI.with_name('schema_manifest.json').read_text())
        db=sqlite3.connect(self.source)
        try:
            db.execute('ALTER TABLE user ADD COLUMN unreviewed TEXT');db.commit()
            schema=raw.sqlite_schema(db)
        finally:db.close()
        manifest['schemas']['sqlite-'+raw.HEAD]={'schema':schema,'fingerprint':raw.fingerprint(schema)}
        forged=self.root/'manifest.json';forged.write_text(json.dumps(manifest))
        result=self.run_cli('inventory','--manifest',forged)
        self.assertNotEqual(result.returncode,0,'caller manifest must not expand the reviewed schema allowlist')

    def test_exact_manifest_replica_accepts_but_duplicate_keys_refuse(self):
        manifest=json.loads(CLI.with_name('schema_manifest.json').read_text())
        replica=self.root/'manifest.json';replica.write_text(json.dumps(manifest,indent=1))
        self.assertEqual(self.run_cli('inventory','--manifest',replica).returncode,0)
        replica.write_text('{"upstream":'+json.dumps(manifest['upstream'])+','+replica.read_text()[1:])
        self.assertNotEqual(self.run_cli('inventory','--manifest',replica).returncode,0)

    def test_snapshot_includes_committed_wal_and_never_overwrites_source(self):
        writer = sqlite3.connect(self.source)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO log(uuid,request) VALUES (?,?)', (uuid.uuid4().bytes,"synthetic WAL record"))
        writer.commit()  # Quiesced here, connection kept open to retain the WAL.
        output = self.root / "snapshot.db"
        result = self.run_cli("snapshot", "--quiesced", "--output", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(output) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM log').fetchone()[0], 1)
        preserved = output.read_bytes()
        self.assertNotEqual(self.run_cli("snapshot", "--quiesced", "--output", output).returncode, 0)
        self.assertEqual(output.read_bytes(), preserved)

    def test_snapshot_requires_quiescence_and_refuses_overlap_or_symlinks(self):
        output = self.root / "snapshot.db"
        self.assertNotEqual(self.run_cli("snapshot", "--output", output).returncode, 0)
        self.assertFalse(output.exists())
        before = self.source.read_bytes()
        self.assertNotEqual(self.run_cli("snapshot", "--quiesced", "--output", self.source).returncode, 0)
        output.symlink_to(self.source)
        self.assertNotEqual(self.run_cli("snapshot", "--quiesced", "--output", output).returncode, 0)
        self.assertEqual(before, self.source.read_bytes())


class RawConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec=importlib.util.spec_from_file_location('workspace_raw',CLI)
        cls.raw=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.raw)
        cls.manifest=cls.raw.load_manifest()

    def column(self, table, name):
        return next(c for c in self.manifest['mapping']['tables'][table]['columns'] if c['name']==name)

    def test_physical_cipher_hash_blob_uuid_and_microseconds(self):
        import gzip
        values=[('user','password','already-persisted-hash'),
                ('api_source','endpointHeaders','opaque-persisted-ciphertext'),
                ('dashboard_item','content',gzip.compress(b'{"x":1}',mtime=123)),
                ('user','uuid',uuid.uuid4().bytes),
                ('copilot_messages','created_date','2026-01-02 03:04:05.123456')]
        for table,name,value in values:
            column=self.column(table,name)
            restored=self.raw.from_postgres(self.raw.to_postgres(value,column),column)
            self.assertEqual(value,restored)

    def test_json_scalar_shape_sql_null_and_exact_numbers(self):
        column=self.column('user','pro_display_settings')
        for value in (None,'null','"{\\"extension\\":1}"','{"extension":123456789012345678901234567890.123456789}','{"x":null}'):
            if value is not None:
                # An explicitly encoded JSON object stored as a JSON string.
                value=json.dumps('{"extension":1}') if value.startswith('"') else value
            converted=self.raw.to_postgres(value,column)
            self.assertEqual(self.raw.value_digest(value,column,'sqlite'),self.raw.value_digest(converted,column,'postgresql'))
        self.assertNotEqual(self.raw.value_digest(None,column,'sqlite'),self.raw.value_digest('null',column,'sqlite'))
        self.assertNotEqual(self.raw.value_digest(json.dumps('{"x":1}'),column,'sqlite'),self.raw.value_digest('{"x":1}',column,'sqlite'))

    def test_unrepresentable_values_are_refused(self):
        column=self.column('user','pro_display_settings')
        for value in ('{"x":1,"x":2}','NaN','"\\u0000"','"\\ud800"','1e999999'):
            with self.subTest(kind=value[:2]),self.assertRaises(ValueError):self.raw.to_postgres(value,column)
        with self.assertRaises(ValueError):self.raw.to_postgres(2,self.column('user','is_superuser'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
