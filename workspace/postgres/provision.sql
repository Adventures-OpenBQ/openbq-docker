-- Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
-- Explicit operator job on a NEW dedicated database. Never run on application boot.
\set ON_ERROR_STOP on
\getenv workspace_migrator_password WORKSPACE_MIGRATOR_PASSWORD
\getenv workspace_read_password WORKSPACE_READ_PASSWORD
\getenv workspace_write_password WORKSPACE_WRITE_PASSWORD
\if :{?workspace_db}
\else
  \set workspace_db openbq_workspace
\endif
-- Validate before catalog mutations or psql \connect interpretation. The
-- second predicate also excludes a trailing newline independent of anchoring.
SELECT (:'workspace_db' COLLATE "C" ~ '^[a-z][a-z0-9_]{0,62}$'
        AND :'workspace_db' COLLATE "C" !~ '[^a-z0-9_]') AS workspace_name_valid \gset
\if :workspace_name_valid
\else
  \echo Invalid Workspace database identifier
  -- ON_ERROR_STOP gives a nonzero exit on PostgreSQL16 psql (\quit has no code).
  SELECT 1 / 0;
\endif
CREATE ROLE openbq_workspace_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE openbq_workspace_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'workspace_migrator_password';
CREATE ROLE openbq_workspace_read LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'workspace_read_password';
CREATE ROLE openbq_workspace_write LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'workspace_write_password';
GRANT openbq_workspace_owner TO openbq_workspace_migrator;
CREATE DATABASE :"workspace_db" OWNER openbq_workspace_owner;
REVOKE ALL ON DATABASE :"workspace_db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"workspace_db" TO openbq_workspace_migrator, openbq_workspace_read, openbq_workspace_write;
\connect :workspace_db
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO openbq_workspace_owner;
GRANT USAGE ON SCHEMA public TO openbq_workspace_read, openbq_workspace_write;
ALTER ROLE openbq_workspace_read IN DATABASE :"workspace_db" SET search_path=public;
ALTER ROLE openbq_workspace_write IN DATABASE :"workspace_db" SET search_path=public;
SET ROLE openbq_workspace_owner;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO openbq_workspace_read;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO openbq_workspace_write;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO openbq_workspace_write;
CREATE SCHEMA workspace_admin AUTHORIZATION openbq_workspace_owner;
REVOKE ALL ON SCHEMA workspace_admin FROM PUBLIC;
CREATE TABLE workspace_admin.readiness (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    identity_digest TEXT NOT NULL,
    entity_uuid UUID NOT NULL,
    inviting_uuid UUID NOT NULL
);
CREATE TABLE workspace_admin.migration_runs (
    run_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    normalized_hash TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    target_identity TEXT NOT NULL,
    evidence JSONB NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
GRANT USAGE ON SCHEMA workspace_admin TO openbq_workspace_read,openbq_workspace_write;
GRANT SELECT ON workspace_admin.readiness TO openbq_workspace_read,openbq_workspace_write;
RESET ROLE;
