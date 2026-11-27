"""Bounded process-owned pool and serializable per-principal document mutations."""
from contextlib import contextmanager
from hashlib import sha256
import logging
import os
from pathlib import Path

from .config import SettingsUnavailable
from .state_version import StateVersion

REVISION = "settings-002"
SCHEMA = Path(__file__).with_name("schema.sql")
ORDERING_SCHEMA = Path(__file__).with_name("schema-state-ordering.sql")


def checksum():
    return sha256(ORDERING_SCHEMA.read_bytes()).hexdigest()


def schema_migrations():
    return [("settings-001", sha256(SCHEMA.read_bytes()).hexdigest()), (REVISION, checksum())]


def verified_schema(conn):
    return conn.execute("SELECT revision,checksum FROM settings_admin.schema_migrations ORDER BY revision").fetchall() == schema_migrations()


def migrate(dsn):
    import psycopg
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE openbq_settings_owner")
        conn.execute("SELECT pg_advisory_xact_lock(74182951001)")
        expected = schema_migrations()
        if conn.execute("SELECT to_regclass('settings_admin.schema_migrations')").fetchone()[0]:
            current = conn.execute("SELECT revision,checksum FROM settings_admin.schema_migrations ORDER BY revision").fetchall()
            if not current or len(current) > len(expected) or current != expected[:len(current)]:
                raise SettingsUnavailable()
        else:
            conn.execute(SCHEMA.read_text())
            conn.execute("INSERT INTO settings_admin.schema_migrations VALUES (%s,%s)", expected[0])
            current = expected[:1]
        if len(current) == 1:
            conn.execute(ORDERING_SCHEMA.read_text())
            conn.execute("INSERT INTO settings_admin.schema_migrations VALUES (%s,%s)", expected[1])


class Store:
    def __init__(self, config):
        from psycopg_pool import ConnectionPool
        # Pool connection retry logs can contain libpq connection text. This boundary
        # owns the dedicated pool logger; expose only our fixed failure messages.
        logging.getLogger("psycopg.pool").disabled = True
        self.pid = os.getpid()
        self.config = config
        self.pool = ConnectionPool(config.dsn, min_size=0, max_size=2, max_waiting=8,
                                   timeout=10, reconnect_timeout=2, open=False,
                                   check=ConnectionPool.check_connection)
        self.pool.open()

    def close(self):
        self.pool.close(timeout=10)

    @contextmanager
    def connection(self):
        if self.pid != os.getpid():
            raise SettingsUnavailable()
        try:
            with self.pool.connection() as conn:
                yield conn
        except SettingsUnavailable:
            raise
        except Exception:
            raise SettingsUnavailable() from None

    def verify(self):
        with self.connection() as conn:
            role = conn.execute("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            if role[0] != "openbq_settings_runtime" or any(role[1:]):
                raise SettingsUnavailable()
            if conn.execute("SELECT pg_has_role(current_user,'openbq_settings_owner','MEMBER')").fetchone()[0]:
                raise SettingsUnavailable()
            if not verified_schema(conn):
                raise SettingsUnavailable()
            if conn.execute("SELECT has_database_privilege(current_database(),'CREATE') OR has_schema_privilege('settings','CREATE') OR has_schema_privilege('settings_admin','CREATE') OR has_table_privilege('settings_admin.checkpoints','INSERT,UPDATE,DELETE')").fetchone()[0]:
                raise SettingsUnavailable()
            for table in ("principals", "documents", "state_fences"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    if not conn.execute("SELECT has_table_privilege(%s,%s)", ("settings." + table, privilege)).fetchone()[0]:
                        raise SettingsUnavailable()

    @contextmanager
    def transaction(self, namespace, principal):
        with self.connection() as conn:
            with conn.transaction():
                conn.execute("INSERT INTO settings.principals VALUES (%s,%s) ON CONFLICT DO NOTHING", (namespace, principal))
                conn.execute("SELECT principal_id FROM settings.principals WHERE namespace=%s AND principal_id=%s FOR UPDATE", (namespace, principal)).fetchone()
                yield Documents(conn, namespace, principal)

    def files(self, principal):
        with self.connection() as conn:
            return {key: bytes(raw).decode("utf-8", errors="replace") for key, raw in conn.execute(
                "SELECT document_key,body_bytes FROM settings.documents WHERE namespace='github' AND principal_id=%s ORDER BY document_key", (principal,))}

    def state(self, principal, name, body, version=None):
        if version is not None and not isinstance(version, StateVersion):
            raise SettingsUnavailable()
        with self.transaction("github", principal) as docs:
            fingerprint = sha256(b"DELETE" if body is None else b"PUT\0" + body).hexdigest()
            if version:
                prior = docs.conn.execute("""SELECT sequence,fingerprint FROM settings.state_fences
                    WHERE namespace=%s AND principal_id=%s AND document_key=%s AND writer=%s""",
                    (*docs.identity, name, version.writer)).fetchone()
                if prior and version.sequence <= prior[0]:
                    return 204 if (version.sequence, fingerprint) == prior else 409
                writers = docs.conn.execute("""SELECT count(*) FROM settings.state_fences
                    WHERE namespace=%s AND principal_id=%s AND document_key=%s""",
                    (*docs.identity, name)).fetchone()[0]
                if not prior and writers >= 256:
                    return 413
            elif docs.conn.execute("""SELECT 1 FROM settings.state_fences
                    WHERE namespace=%s AND principal_id=%s AND document_key=%s LIMIT 1""",
                    (*docs.identity, name)).fetchone():
                return 409
            if body is not None:
                count, size = docs.conn.execute("SELECT count(*),coalesce(sum(octet_length(body_bytes)),0) FROM settings.documents WHERE namespace=%s AND principal_id=%s AND document_key<>%s", (*docs.identity, name)).fetchone()
                if len(body) > 262144 or size + len(body) > 2097152 or count >= 200:
                    return 413
            # A deleted versioned file remains represented by its fences. Bound both
            # visible documents and those tombstones without charging body quota twice.
            names = docs.conn.execute("""SELECT document_key FROM settings.documents
                WHERE namespace=%s AND principal_id=%s UNION SELECT document_key
                FROM settings.state_fences WHERE namespace=%s AND principal_id=%s""",
                (*docs.identity, *docs.identity)).fetchall()
            if (body is not None or version) and name not in {row[0] for row in names} and len(names) >= 2000:
                return 413
            if version:
                docs.conn.execute("""INSERT INTO settings.state_fences
                    (namespace,principal_id,document_key,writer,sequence,fingerprint)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(namespace,principal_id,document_key,writer)
                    DO UPDATE SET sequence=excluded.sequence,fingerprint=excluded.fingerprint""",
                    (*docs.identity, name, version.writer, version.sequence, fingerprint))
            if body is None:
                docs.delete(name)
            else:
                docs.write(name, body)
            return 204


class Documents:
    def __init__(self, conn, namespace, principal):
        self.conn = conn
        self.identity = (namespace, principal)

    def read(self, key):
        row = self.conn.execute("SELECT body_bytes FROM settings.documents WHERE namespace=%s AND principal_id=%s AND document_key=%s", (*self.identity, key)).fetchone()
        return bytes(row[0]) if row else b"{}"

    def write(self, key, body):
        row = self.conn.execute("""INSERT INTO settings.documents(namespace,principal_id,document_key,body_bytes,revision)
            VALUES (%s,%s,%s,%s,1) ON CONFLICT(namespace,principal_id,document_key)
            DO UPDATE SET body_bytes=excluded.body_bytes, revision=settings.documents.revision+1,updated_at=clock_timestamp()
            WHERE settings.documents.revision<9223372036854775807 RETURNING revision""", (*self.identity, key, body)).fetchone()
        if row is None:
            raise SettingsUnavailable()

    def delete(self, key):
        self.conn.execute("DELETE FROM settings.documents WHERE namespace=%s AND principal_id=%s AND document_key=%s", (*self.identity, key))
