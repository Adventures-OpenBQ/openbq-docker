-- settings-002; additive migration, run only as openbq_settings_owner.
CREATE TABLE settings.state_fences (
 namespace text NOT NULL DEFAULT 'github' CHECK(namespace = 'github'),
 principal_id text NOT NULL,
 document_key text NOT NULL,
 writer text NOT NULL CHECK(writer ~ '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$'),
 sequence bigint NOT NULL CHECK(sequence BETWEEN 1 AND 9007199254740991),
 fingerprint text NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
 PRIMARY KEY(namespace, principal_id, document_key, writer),
 FOREIGN KEY(namespace, principal_id) REFERENCES settings.principals(namespace, principal_id)
);
REVOKE ALL ON settings.state_fences FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON settings.state_fences TO openbq_settings_runtime;
