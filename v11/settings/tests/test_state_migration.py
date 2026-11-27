"""Read-only migration of authoritative SQLite state, including deleted records."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from openbq_settings_pg.migrate_json import inventory, Refused

WRITER = "11111111-1111-4111-8111-111111111111"
MAPPING = {"a" * 64: "aaaaaaaa-1111-4111-8111-111111111111"}


class SQLiteStateMigration(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.source = Path(self.root.name)
        self.directory = self.source / "state" / "00042"
        self.directory.mkdir(parents=True)
        self.database = self.directory / ".state.sqlite"

    def create(self, rows):
        with sqlite3.connect(self.database) as conn:
            conn.executescript("CREATE TABLE records(name TEXT PRIMARY KEY,body TEXT,fences TEXT NOT NULL);"
                               "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);"
                               "INSERT INTO metadata VALUES('imported','1');")
            conn.executemany("INSERT INTO records VALUES(?,?,?)", rows)

    def test_authoritative_database_supersedes_stale_json_and_preserves_tombstones(self):
        fingerprint = sha256(b"DELETE").hexdigest()
        self.create([("settings.json", ' {"current":true} ', "{}"),
                     ("layouts/a.json", None, json.dumps({WRITER: {"sequence": 9, "fingerprint": fingerprint}}))])
        (self.directory / "settings.json").write_text('{"stale":true}')
        (self.directory / "layouts%2Fa.json").write_text('{"deleted":true}')
        before = self.database.read_bytes()
        documents, manifest = inventory(self.source, MAPPING)
        self.assertEqual(documents, {("github", "00042", "settings.json"): b' {"current":true} '})
        self.assertEqual(manifest["fences"], [["github", "00042", "layouts/a.json", WRITER, 9, fingerprint]])
        self.assertEqual(self.database.read_bytes(), before)

    def test_invalid_fences_or_state_names_are_refused_without_source_changes(self):
        cases = [("settings.json", "{}", {WRITER: {"sequence": 0, "fingerprint": "a"*64}}),
                 ("settings.json", "{}", {WRITER: {"sequence": True, "fingerprint": "a"*64}}),
                 ("settings.json", "{}", {WRITER.upper(): {"sequence": 1, "fingerprint": "a"*64}}),
                 ("settings.json", "{}", {WRITER: {"sequence": 1, "fingerprint": "broken"}}),
                 ("../settings.json", "{}", {}), ("settings.json", "not-json", {})]
        # This writer contains no a-f characters: use a distinct invalid uppercase UUID.
        cases[2] = ("settings.json", "{}", {"AAAAAAAA-1111-4111-8111-111111111111": {"sequence": 1, "fingerprint": "a"*64}})
        for name, body, fences in cases:
            with self.subTest(name=name, fences=fences):
                self.create([(name, body, json.dumps(fences))])
                before = self.database.read_bytes()
                with self.assertRaises((Refused, ValueError)):
                    inventory(self.source, MAPPING)
                self.assertEqual(self.database.read_bytes(), before)
                self.database.unlink()

    def test_live_wal_or_symlink_database_is_refused(self):
        self.create([])
        (self.directory / ".state.sqlite-wal").write_bytes(b"unfinished")
        with self.assertRaises(Refused): inventory(self.source, MAPPING)
        (self.directory / ".state.sqlite-wal").unlink()
        original = self.source / "outside.sqlite"
        self.database.rename(original)
        self.database.symlink_to(original)
        with self.assertRaises(Refused): inventory(self.source, MAPPING)

    def test_uninitialized_or_unknown_sqlite_schema_is_refused(self):
        self.create([])
        with sqlite3.connect(self.database) as conn:
            conn.execute("DELETE FROM metadata")
        with self.assertRaises(Refused): inventory(self.source, MAPPING)
        with sqlite3.connect(self.database) as conn:
            conn.execute("INSERT INTO metadata VALUES('imported','1')")
            conn.execute("CREATE TABLE extra(body TEXT)")
        with self.assertRaises(Refused): inventory(self.source, MAPPING)


if __name__ == "__main__": unittest.main()
