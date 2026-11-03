-- settings-001; owned by openbq_settings_owner, never applied by runtime.
CREATE SCHEMA settings AUTHORIZATION openbq_settings_owner;
CREATE SCHEMA settings_admin AUTHORIZATION openbq_settings_owner;
CREATE TABLE settings.principals (
 namespace text NOT NULL CHECK(namespace IN ('key','github')),
 principal_id text NOT NULL,
 PRIMARY KEY(namespace, principal_id)
);
CREATE TABLE settings.documents (
 namespace text NOT NULL,
 principal_id text NOT NULL,
 document_key text NOT NULL,
 body_bytes bytea NOT NULL,
 revision bigint NOT NULL CHECK(revision > 0),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(namespace, principal_id, document_key),
 FOREIGN KEY(namespace, principal_id) REFERENCES settings.principals(namespace, principal_id)
);
CREATE TABLE settings_admin.schema_migrations (revision text PRIMARY KEY, checksum text NOT NULL);
CREATE TABLE settings_admin.checkpoints (
 run_id text PRIMARY KEY, manifest jsonb NOT NULL, target_manifest jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON SCHEMA settings, settings_admin FROM PUBLIC;
GRANT USAGE ON SCHEMA settings, settings_admin TO openbq_settings_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON settings.principals, settings.documents TO openbq_settings_runtime;
GRANT SELECT ON settings_admin.schema_migrations TO openbq_settings_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE openbq_settings_owner IN SCHEMA settings REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE openbq_settings_owner IN SCHEMA settings_admin REVOKE ALL ON TABLES FROM PUBLIC;
