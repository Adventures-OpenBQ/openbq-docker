-- psql -X -v ON_ERROR_STOP=1 -v settings_database=openbq_settings -f provision.sql
-- Admin connection and both passwords supplied through a private environment file.
\getenv runtime_password OPENBQ_SETTINGS_RUNTIME_PASSWORD
\getenv migration_password OPENBQ_SETTINGS_MIGRATION_PASSWORD
CREATE ROLE openbq_settings_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE openbq_settings_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'migration_password';
CREATE ROLE openbq_settings_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'runtime_password';
GRANT openbq_settings_owner TO openbq_settings_migrator;
CREATE DATABASE :"settings_database" OWNER openbq_settings_owner;
REVOKE ALL ON DATABASE :"settings_database" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"settings_database" TO openbq_settings_migrator, openbq_settings_runtime;
\connect :settings_database
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
