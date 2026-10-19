#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Offline exact-pin Workspace transfer. Never imports application ORM models."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
from urllib.parse import quote
from uuid import UUID

HEAD = "9b1d0c5e7a42"
REVISIONS = ("0d4a342f4c26", HEAD)
MANIFEST = Path(__file__).with_name("schema_manifest.json")
if not MANIFEST.exists():
    MANIFEST = Path(__file__).with_name("workspace_schema_manifest.json")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(path, root, *, output=False):
    path, root = Path(path).absolute(), Path(root).absolute()
    for candidate in (root, *root.parents, path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("symlinks are unsupported")
    root = root.resolve(strict=True)
    path = path.resolve(strict=not output)
    if not root.is_dir() or root not in path.parents:
        raise ValueError("path must be inside the approved offline root")
    if output:
        if path.exists() or not path.parent.is_dir():
            raise ValueError("destination must be new")
    elif not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("source must be a regular unlinked file")
    return path


@contextmanager
def sqlite_read(path):
    # Inputs are offline copies (snapshot additionally requires --quiesced).
    # A standalone WAL-mode file without WAL pages can be opened immutably;
    # with an existing WAL, normal read-only SQLite must include those pages.
    if Path(str(path) + "-journal").exists():
        raise ValueError("pending SQLite rollback journal")
    suffix = "" if Path(str(path) + "-wal").exists() else "&immutable=1"
    db = sqlite3.connect("file:" + quote(str(path)) + "?mode=ro" + suffix, uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


@contextmanager
def sqlite_write(path):
    db=sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def sqlite_schema(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1").fetchone():
        raise ValueError('unrecognized SQLite view or trigger')
    tables = {}
    for name, sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
        table = identifier(name)
        entry = {"sql": sql,
                 "columns": db.execute("PRAGMA table_xinfo(" + table + ")").fetchall(),
                 "foreign_keys": db.execute("PRAGMA foreign_key_list(" + table + ")").fetchall(),
                 "indexes": []}
        for index in db.execute("PRAGMA index_list(" + table + ")"):
            entry["indexes"].append({"entry": index,
                "columns": db.execute("PRAGMA index_xinfo(" + identifier(index[1]) + ")").fetchall(),
                "sql": db.execute("SELECT sql FROM sqlite_master WHERE name=?", (index[1],)).fetchone()[0]})
        tables[name] = entry
    # JSON normalizes tuples identically to the reviewed portable manifest.
    return json.loads(canonical(tables))


def canonical_postgres_checks(table, checks):
    # PG16.11 pg_dump/restore reparses these three pinned CHECK expressions:
    # an array-to-text[] cast becomes the identical per-element text casts.
    # Match complete known expressions AND constraint/table identity only.
    names = {'entity_entitlement': 'check_share_widgets_values_entity_entitlements',
             'default_tier': 'check_share_widgets_values_tier_defaults',
             'entitlement': 'check_share_widgets_values_entitlements'}
    original = "share_widgets::text = ANY (ARRAY['public'::character varying, 'private'::character varying]::text[])"
    restored = "share_widgets::text = ANY (ARRAY['public'::character varying::text, 'private'::character varying::text])"
    return [dict(check, sqltext=original) if table in names and
            check.get('name') == names[table] and check.get('sqltext') == restored
            else check for check in checks]


def postgres_schema(connection):
    from sqlalchemy import inspect
    # The pin has no row security, policies, views, routines, foreign tables or user triggers.
    # Reflection of ordinary tables alone would silently accept these extensions.
    extras = connection.exec_driver_sql("""SELECT
      EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND c.relkind IN ('v','m','f')) OR
      EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
              WHERE n.nspname='public') OR
      EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
              JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND NOT t.tgisinternal) OR
      EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND (c.relrowsecurity OR c.relforcerowsecurity)) OR
      EXISTS (SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
              JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public')""").scalar_one()
    if extras:
        raise ValueError('unrecognized PostgreSQL schema objects')
    inspector = inspect(connection)
    tables = {}
    for name in inspector.get_table_names(schema="public"):
        columns = inspector.get_columns(name, schema="public")
        for column in columns:
            physical = column["type"]
            column["type_details"] = {key: getattr(physical,key) for key in
                ("precision", "scale", "timezone", "length", "collation", "name", "enums")
                if hasattr(physical,key)}
            column["type"] = str(physical)
        tables[name] = {"columns": columns,
                       "foreign_keys": inspector.get_foreign_keys(name, schema="public"),
                       "primary_key": inspector.get_pk_constraint(name, schema="public"),
                       "unique": inspector.get_unique_constraints(name, schema="public"),
                       "check": canonical_postgres_checks(name, inspector.get_check_constraints(name, schema="public")),
                       "indexes": inspector.get_indexes(name, schema="public")}
    enums = connection.exec_driver_sql("SELECT t.typname,e.enumlabel,e.enumsortorder FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public' ORDER BY t.typname,e.enumsortorder").all()
    sequences = connection.exec_driver_sql("""SELECT c.relname,format_type(s.seqtypid,NULL),
      s.seqstart,s.seqincrement,s.seqmax,s.seqmin,s.seqcache,s.seqcycle,
      parent.relname,a.attname,d.deptype
      FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace
      LEFT JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.objid=c.oid
        AND d.refclassid='pg_class'::regclass AND d.deptype IN ('a','i')
      LEFT JOIN pg_class parent ON parent.oid=d.refobjid
      LEFT JOIN pg_attribute a ON a.attrelid=parent.oid AND a.attnum=d.refobjsubid
      WHERE n.nspname='public' ORDER BY c.relname""").all()
    return json.loads(canonical({"tables": tables, "enums": [list(row) for row in enums],
                                 "sequences": [list(row) for row in sequences]}))


def load_manifest(path=MANIFEST):
    authority_text = MANIFEST.read_text()
    authority = json_logical(json_value(authority_text))
    if Path(path) != MANIFEST and json_logical(json_value(Path(path).read_text())) != authority:
        raise ValueError('manifest differs from the packaged reviewed authority')
    # Use the authority's canonical numeric types after strict duplicate/nonfinite
    # validation. A custom path is a replica, never a schema extension mechanism.
    manifest = json.loads(authority_text)
    if manifest["upstream"] != "be00e95019a55d57af146919ee46b7e1a4859226":
        raise ValueError("unsupported manifest pin")
    return manifest


def validate_sqlite(db, manifest):
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise ValueError("SQLite integrity failure")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("SQLite foreign key failure")
    rows = db.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(rows) != 1 or rows[0][0] not in REVISIONS:
        raise ValueError("unsupported revision")
    revision = rows[0][0]
    schema = sqlite_schema(db)
    if fingerprint(schema) != manifest["schemas"]["sqlite-" + revision]["fingerprint"]:
        raise ValueError("unsupported schema drift")
    return revision, schema


def validate_postgres(connection, manifest):
    if connection.exec_driver_sql("SELECT version_num FROM public.alembic_version").all() != [(HEAD,)]:
        raise ValueError("unsupported revision")
    schema = postgres_schema(connection)
    if fingerprint(schema) != manifest["schemas"]["postgresql-" + HEAD]["fingerprint"]:
        raise ValueError("unsupported PostgreSQL schema drift")
    return schema


def inventory(source, manifest):
    with sqlite_read(source) as db:
        revision, schema = validate_sqlite(db, manifest)
        return {"revision": revision, "table_count": len(schema), "schema_fingerprint": fingerprint(schema)}


def snapshot(source, output, manifest):
    # A backup connection incorporates committed WAL pages. Quiescence is an
    # explicit operator precondition; this process cannot prove other writers stopped.
    fd, name = tempfile.mkstemp(prefix=".workspace-snapshot-", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with sqlite_read(source) as src:
            validate_sqlite(src, manifest)
            with sqlite_write(temporary) as dst:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
        result = inventory(temporary, manifest)
        temporary.chmod(0o400)
        # Hard link publishes a fully checked file without replacing an existing path.
        os.link(temporary, output)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    for action in ('inventory','snapshot','import','verify','export-sqlite'):
        command=commands.add_parser(action)
        command.add_argument('--root',required=True)
        command.add_argument('--manifest',default=str(MANIFEST))
        if action!='export-sqlite':command.add_argument('--source',required=True)
        if action in ('snapshot','export-sqlite'):
            command.add_argument('--output',required=True)
            command.add_argument('--quiesced',action='store_true',required=True)
        if action in ('import','verify'):command.add_argument('--run-id',required=True)
        if action in ('import','export-sqlite'):
            command.add_argument('--mapping',required=True)
            command.add_argument('--mapping-output',required=True)
    args=parser.parse_args()
    manifest_path=Path(args.manifest)
    if manifest_path != MANIFEST:
        manifest_path=safe_path(manifest_path,args.root)
    if manifest_path.is_symlink():raise ValueError('manifest symlink refused')
    manifest=load_manifest(manifest_path)
    source=safe_path(args.source,args.root) if hasattr(args,'source') else None
    if hasattr(args,'output'):output=safe_path(args.output,args.root,output=True)
    if hasattr(args,'mapping'):
        mapping_path=safe_path(args.mapping,args.root)
        if mapping_path.stat().st_mode & 0o077:raise ValueError('mapping input must be private')
        mapping=json.loads(mapping_path.read_text())
        mapping_output=safe_path(args.mapping_output,args.root,output=not Path(args.mapping_output).exists())
        if mapping_output==mapping_path or mapping_output==source:raise ValueError('mapping output overlaps input')
        if args.action=='export-sqlite' and mapping_output==output:
            raise ValueError('mapping and SQLite outputs overlap')
    if args.action=='inventory':result=inventory(source,manifest)
    elif args.action=='snapshot':result=snapshot(source,output,manifest)
    elif args.action=='import':result=import_database(source,Path(args.root),manifest,args.run_id,mapping,mapping_output)
    elif args.action=='verify':result=verify_database(source,Path(args.root),manifest,args.run_id)
    else:result=export_sqlite(output,manifest,mapping,mapping_output)
    print(json.dumps(result,sort_keys=True))


# Shared by the offline importer and selected runtime. These queries never bind
# application models, hash passwords, decrypt values, or infer an administrator.
def identity_digest(environment):
    names = ('JWT_SECRET', 'OPENBB_AUTH_TOKEN', 'OPENBB_AES_KEY', 'LOCAL_STORAGE_SECRET_KEY')
    values = {name: environment.get(name, '') for name in names}
    if not all(values.values()):
        raise ValueError('incomplete identity material')
    import jwt
    jwt.decode(values['OPENBB_AUTH_TOKEN'],values['JWT_SECRET'],algorithms=['HS256'])
    return fingerprint(values)


def permission_mapping(connection, dialect, mapping):
    from uuid import UUID
    entity, inviter = UUID(mapping['entity_uuid']), UUID(mapping['inviting_uuid'])
    pg = dialect == 'postgresql'
    param = '%s' if pg else '?'
    def query(sql, values=()):
        return (connection.exec_driver_sql(sql, values).all() if pg else
                connection.execute(sql, values).fetchall())
    physical = lambda value: str(value) if pg else value.bytes
    def uid(value):
        return str(UUID(bytes=value)) if isinstance(value, bytes) else str(UUID(str(value)))
    if len(query('SELECT uuid FROM entity WHERE uuid=' + param, (physical(entity),))) != 1:
        raise ValueError('missing explicit entity')
    rows = query('SELECT uuid,name FROM permissions_entity_map WHERE entity_uuid=' + param,
                 (physical(entity),))
    selected = {}
    for label in ('Admin', 'User'):
        matches = [uid(row[0]) for row in rows if row[1] == label]
        if len(matches) != 1:
            raise ValueError('missing or ambiguous explicit permission relationship')
        selected[label] = matches[0]
    users = query('SELECT permissions_uuid,email FROM "user" WHERE uuid=' + param,
                  (physical(inviter),))
    if len(users) != 1 or users[0][0] is None or uid(users[0][0]) != selected['Admin']:
        raise ValueError('inviter does not belong to explicit administrator permission')
    trial = query('SELECT p.uuid FROM permissions_entity_map p JOIN entity e ON e.uuid=p.entity_uuid '
                  'WHERE p.uuid=' + param + " AND p.name='Trial'",
                  (physical(UUID('11111111-1111-1111-1111-111111111111')),))
    if len(trial) != 1:
        raise ValueError('missing required trial mapping')
    return {'on_prem_admin_uuid': selected['Admin'], 'permissions_uuid': selected['User'],
            'inviting_uuid': str(inviter), 'inviting_email': users[0][1]}


def json_value(value):
    from decimal import Decimal
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('duplicate JSON keys are not representable')
            result[key] = item
        return result
    def invalid(_):
        raise ValueError('nonfinite JSON number')
    parsed = json.loads(value, parse_float=Decimal, parse_int=Decimal,
                        parse_constant=invalid, object_pairs_hook=pairs)
    def check(item):
        if isinstance(item, str):
            if '\0' in item:
                raise ValueError('JSON NUL is not representable')
            item.encode('utf-8')  # rejects unpaired surrogates
        elif isinstance(item, Decimal):
            _, digits, exponent = item.as_tuple()
            if not item.is_finite() or max(len(digits)+exponent,0)>131072 or max(-exponent,0)>16383:
                raise ValueError('JSON number outside PostgreSQL numeric limits')
        elif isinstance(item, list):
            for child in item:check(child)
        elif isinstance(item, dict):
            for key, child in item.items():check(key);check(child)
    try:
        check(parsed)
    except UnicodeError:
        raise ValueError('JSON surrogate is not representable') from None
    return parsed


def json_logical(value):
    from decimal import Decimal
    if isinstance(value, Decimal):
        # normalize() uses a context precision and can round large values.
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        while digits and digits[-1] == 0:
            digits.pop();exponent += 1
        return ['number', sign if digits else 0, digits, exponent if digits else 0]
    if isinstance(value, dict):
        return ['object', [[key,json_logical(value[key])] for key in sorted(value)]]
    if isinstance(value, list):
        return ['array', [json_logical(child) for child in value]]
    return [type(value).__name__, value]


def datetime_value(value, aware=False):
    from datetime import datetime, timezone
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError('unsupported timestamp value')
    if aware:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if value.tzinfo is not None:
        raise ValueError('offset timestamp in timezone-naive column')
    return value


def to_postgres(value, column):
    from uuid import UUID
    import math
    if value is None:
        if not column['nullable']:
            raise ValueError('NULL in required column')
        return None
    policy = column['policy']
    if policy == 'uuid-bytes':
        if not isinstance(value, bytes) or len(value) != 16:
            raise ValueError('unsupported physical UUID encoding')
        return str(UUID(bytes=value))
    if policy == 'bytes':
        if not isinstance(value, bytes):raise ValueError('nonbinary blob')
        return value
    if policy == 'json':
        if not isinstance(value, str):raise ValueError('unsupported physical JSON encoding')
        json_value(value)
        return value  # exactly one physical layer; INSERT casts text to jsonb
    if policy in ('datetime','utc-datetime'):
        return datetime_value(value, policy == 'utc-datetime')
    if policy == 'boolean':
        if type(value) is not int or value not in (0,1):raise ValueError('noncanonical boolean')
        return bool(value)
    if policy == 'integer':
        bits={'SMALLINT':16,'INTEGER':32,'BIGINT':64}[column['postgresql_type']]
        if type(value) is not int or not -(2**(bits-1))<=value<2**(bits-1):raise ValueError('integer out of range')
        return value
    if policy == 'float':
        if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('invalid floating value')
        converted=float(value)
        if converted != value:raise ValueError('floating conversion loses precision')
        return converted
    if not isinstance(value,str) or '\0' in value:raise ValueError('invalid physical text')
    value.encode('utf-8')
    details=column['type_details']
    if details.get('length') is not None and len(value)>details['length']:raise ValueError('text exceeds declared width')
    if details.get('enums') and value not in details['enums']:raise ValueError('unknown enum label')
    return value


def from_postgres(value, column):
    from uuid import UUID
    if value is None:return None
    policy=column['policy']
    if policy=='uuid-bytes':return UUID(str(value)).bytes
    if policy=='bytes':return bytes(value)
    if policy=='boolean':return int(value)
    if policy in ('datetime','utc-datetime'):
        value=datetime_value(value,policy=='utc-datetime')
        return value.replace(tzinfo=None).isoformat(sep=' ',timespec='microseconds')
    if policy=='json':
        json_value(value)
    return value


def value_digest(value, column, dialect):
    import base64
    if value is None:return ['sql-null']
    value=to_postgres(value,column) if dialect=='sqlite' else value
    policy=column['policy']
    if policy=='json':return json_logical(json_value(value))
    if policy=='bytes':return ['bytes',base64.b64encode(value).decode('ascii')]
    if policy=='uuid-bytes':return ['uuid',str(value)]
    if policy in ('datetime','utc-datetime'):
        return ['timestamp',datetime_value(value,policy=='utc-datetime').isoformat(timespec='microseconds')]
    if policy=='float':return ['float',float(value).hex()]
    return [policy,value]


def table_rows(connection, dialect, name, columns):
    expressions=[identifier(c['name']) + ('::text' if dialect=='postgresql' and c['policy']=='json' else '') for c in columns]
    sql='SELECT '+','.join(expressions)+' FROM '+('public.' if dialect=='postgresql' else '')+identifier(name)
    cursor=connection.exec_driver_sql(sql) if dialect=='postgresql' else connection.execute(sql)
    return [tuple(row) for row in cursor]


def data_evidence(connection, dialect, manifest):
    result={}
    for name, table in manifest['mapping']['tables'].items():
        columns=table['columns']
        rows=table_rows(connection,dialect,name,columns)
        encoded=sorted(canonical([value_digest(value,column,dialect) for value,column in zip(row,columns)]) for row in rows)
        digest=hashlib.sha256()
        for row in encoded:
            digest.update(len(row).to_bytes(8,'big'));digest.update(row)
        result[name]={'count':len(rows),'digest':digest.hexdigest()}
    return result


def seed_signature(connection, manifest):
    result={}
    for name in manifest['mapping']['seed_tables']:
        columns=[c for c in manifest['mapping']['tables'][name]['columns']
                 if c['policy'] not in ('uuid-bytes','datetime','utc-datetime')]
        rows=table_rows(connection,'postgresql',name,columns)
        values=sorted(canonical([value_digest(v,c,'postgresql') for v,c in zip(row,columns)]).decode() for row in rows)
        result[name]={'count':len(rows),'signature':fingerprint(values)}
    return result


def pg_engine(url=None):
    if not (os.environ.get('SSL_CA') or os.environ.get('SSL_CERT')) and os.environ.get('WORKSPACE_POSTGRES_ALLOW_PLAINTEXT')!='1':
        raise ValueError('PostgreSQL TLS material is required; set WORKSPACE_POSTGRES_ALLOW_PLAINTEXT=1 to connect without TLS')
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool
    # DSNs are private environment inputs. Disallow URI query overrides of the
    # fixed timeout/search_path/TLS contract and never render the URL in output.
    url=make_url(os.environ['WORKSPACE_TARGET_DSN']) if url is None else url
    if url.drivername not in ('postgresql','postgresql+psycopg2') or url.query:
        raise ValueError('unsupported target driver or DSN query options')
    cert,key=os.environ.get('SSL_CERT'),os.environ.get('SSL_KEY')
    if bool(cert)!=bool(key):raise ValueError('incomplete TLS certificate pair')
    ca=os.environ.get('SSL_CA')
    args={'connect_timeout':10,'options':'-c statement_timeout=30000 -c lock_timeout=5000 -c search_path=public',
          'sslmode':'verify-full' if ca or cert else 'disable','application_name':'workspace-transfer'}
    for name,value in (('sslrootcert',ca),('sslcert',cert),('sslkey',key)):
        if value:args[name]=value
    return create_engine(url.set(drivername='postgresql+psycopg2'),poolclass=NullPool,
                         connect_args=args,hide_parameters=True)


def locked_target(engine):
    import contextlib
    import time
    @contextlib.contextmanager
    def locked():
        with engine.connect() as connection:
            acquired=False
            try:
                deadline=time.monotonic()+30
                while not acquired:
                    acquired=connection.exec_driver_sql('SELECT pg_try_advisory_lock(1791763200,5)').scalar_one()
                    connection.commit()
                    if not acquired:
                        if time.monotonic()>=deadline:raise TimeoutError('maintenance lock timeout')
                        time.sleep(0.1)
                role=os.environ.get('WORKSPACE_MIGRATION_ROLE')
                if role:
                    connection.exec_driver_sql('SET ROLE '+identifier(role));connection.commit()
                yield connection
            finally:
                connection.rollback()
                if acquired:
                    connection.exec_driver_sql('SELECT pg_advisory_unlock(1791763200,5)');connection.commit()
    return locked()


def target_identity(connection, engine):
    oid=connection.exec_driver_sql('SELECT oid FROM pg_database WHERE datname=current_database()').scalar_one()
    return fingerprint([engine.url.host,engine.url.port,engine.url.database,oid])


def migrate_sqlite_file(path, manifest, *, existing=False):
    import subprocess
    backend=Path(__file__).resolve().parent.parent
    if not (backend/'alembic.ini').is_file():
        raise ValueError('SQLite construction requires the pinned packaged runtime')
    env=dict(os.environ,DATABASE_TYPE='sqlite',DB_PATH=str(path))
    result=subprocess.run([sys.executable,'-m','alembic','upgrade',HEAD],cwd=backend,env=env,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError('pinned SQLite migration failed')
    with sqlite_read(path) as connection:
        if validate_sqlite(connection,manifest)[0]!=HEAD:raise ValueError('incomplete SQLite target')


def normalized_source(source, manifest, root):
    import contextlib
    import shutil
    @contextlib.contextmanager
    def normalized():
        if Path(str(source)+'-wal').exists() or Path(str(source)+'-journal').exists():
            raise ValueError('import requires a standalone quiesced snapshot')
        with sqlite_read(source) as connection:
            revision,_=validate_sqlite(connection,manifest)
        if revision==HEAD:
            yield source
        else:
            with tempfile.TemporaryDirectory(prefix='.workspace-normalized-',dir=root) as directory:
                path=Path(directory)/'normalized.db'
                shutil.copyfile(source,path);path.chmod(0o600)
                migrate_sqlite_file(path,manifest,existing=True)
                # Close/checkpoint the normalized copy; the original stays untouched.
                with sqlite_write(path) as db:db.execute('PRAGMA journal_mode=DELETE')
                yield path
    return normalized()


def insert_rows(connection, dialect, name, columns, rows):
    if not rows:return
    names=','.join(identifier(c['name']) for c in columns)
    slots=','.join('%s::jsonb' if c['policy']=='json' else '%s' for c in columns) if dialect=='postgresql' else ','.join('?' for _ in columns)
    sql='INSERT INTO '+('public.' if dialect=='postgresql' else '')+identifier(name)+'('+names+') VALUES ('+slots+')'
    if dialect=='postgresql':connection.exec_driver_sql(sql,rows)
    else:connection.executemany(sql,rows)


def reconcile_tier_sequence(target, manifest):
    # setval is not transactional. RESTART replaces the sequence's transactional
    # state, so a late failure or killed importer also restores the prior counter.
    sequences = manifest['schemas']['postgresql-' + HEAD]['schema']['sequences']
    if len(sequences) != 1 or sequences[0][0] != 'tier_id_seq' or sequences[0][8:] != ['tier','id','a']:
        raise ValueError('unsupported sequence profile')
    sequence = sequences[0]
    minimum = sequence[5]
    maximum = target.exec_driver_sql('SELECT max(id) FROM public.tier').scalar_one()
    consumed = maximum is not None and maximum >= minimum
    restart = maximum if consumed else minimum
    target.exec_driver_sql('ALTER SEQUENCE public.' + identifier(sequence[0]) + ' RESTART WITH ' + str(restart))
    if consumed:
        # Consuming the existing maximum preserves exhaustion at max-int instead
        # of inventing an out-of-range restart or colliding with an imported row.
        target.exec_driver_sql('SELECT nextval(%s)', ('public.' + sequence[0],))


def replace_data(source, source_dialect, target, target_dialect, manifest):
    order=manifest['mapping']['insert_order']
    for name in reversed(order):
        sql='DELETE FROM '+('public.' if target_dialect=='postgresql' else '')+identifier(name)
        target.exec_driver_sql(sql) if target_dialect=='postgresql' else target.execute(sql)
    cycle=manifest['mapping']['cycle'];parents=[]
    for name in order:
        columns=manifest['mapping']['tables'][name]['columns']
        rows=table_rows(source,source_dialect,name,columns)
        convert=to_postgres if target_dialect=='postgresql' else from_postgres
        converted=[tuple(convert(value,column) for value,column in zip(row,columns)) for row in rows]
        if name==cycle['table']:
            position=next(i for i,c in enumerate(columns) if c['name']==cycle['column'])
            key=next(i for i,c in enumerate(columns) if c['name']==cycle['key'])
            adjusted=[]
            for row in converted:
                parents.append((row[position],row[key]));row=list(row);row[position]=None;adjusted.append(tuple(row))
            converted=adjusted
        # Bounded batches remain inside the single complete transaction.
        for start in range(0,len(converted),250):insert_rows(target,target_dialect,name,columns,converted[start:start+250])
    placeholder='%s' if target_dialect=='postgresql' else '?'
    sql='UPDATE '+identifier(cycle['table'])+' SET '+identifier(cycle['column'])+'='+placeholder+' WHERE '+identifier(cycle['key'])+'='+placeholder
    for pair in parents:
        target.exec_driver_sql(sql,pair) if target_dialect=='postgresql' else target.execute(sql,pair)
    if target_dialect=='postgresql':
        reconcile_tier_sequence(target, manifest)


def publish_mapping(path, mapping):
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077 or json.loads(path.read_text())!=mapping:
            raise ValueError('mapping output differs')
        return
    fd,name=tempfile.mkstemp(prefix='.workspace-map-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump(mapping,output,sort_keys=True);output.flush();os.fsync(output.fileno())
        os.link(name,path)
    finally:Path(name).unlink(missing_ok=True)


def import_database(source, root, manifest, run_id, mapping, mapping_output):
    if not run_id or len(run_id)>128 or not all(c.isalnum() or c in '-_' for c in run_id):
        raise ValueError('invalid opaque run identifier')
    original_hash=file_hash(source)
    engine=pg_engine()
    try:
        with normalized_source(source,manifest,root) as normalized:
            normalized_hash=file_hash(normalized)
            with sqlite_read(normalized) as source_db:
                validate_sqlite(source_db,manifest)
                expected=data_evidence(source_db,'sqlite',manifest)  # all raw values preflighted
                permission_mapping(source_db,'sqlite',mapping)
                ready={**{key:str(UUID(mapping[key])) for key in ('entity_uuid','inviting_uuid')},'identity_digest':identity_digest(os.environ)}
                protected_evidence={'tables':expected,'readiness':ready}
                if mapping_output.exists() and json.loads(mapping_output.read_text())!=ready:
                    raise ValueError('mapping output collision')
                with locked_target(engine) as target:
                    with target.begin():
                        validate_postgres(target,manifest)
                        identity=target_identity(target,engine)
                        checkpoint=target.exec_driver_sql('SELECT source_hash,normalized_hash,manifest_hash,target_identity,evidence FROM workspace_admin.migration_runs WHERE run_id=%s',(run_id,)).one_or_none()
                        wanted=(original_hash,normalized_hash,fingerprint(manifest),identity)
                        if checkpoint:
                            if tuple(checkpoint[:4])!=wanted or checkpoint[4]!=protected_evidence or data_evidence(target,'postgresql',manifest)!=expected:
                                raise ValueError('completed import diverged')
                            actual_ready=target.exec_driver_sql('SELECT identity_digest,entity_uuid,inviting_uuid FROM workspace_admin.readiness WHERE singleton=true').one()
                            if tuple(map(str,actual_ready))!=(ready['identity_digest'],ready['entity_uuid'],ready['inviting_uuid']):
                                raise ValueError('completed readiness diverged')
                        else:
                            if target.exec_driver_sql('SELECT count(*) FROM workspace_admin.migration_runs').scalar_one() or target.exec_driver_sql('SELECT count(*) FROM workspace_admin.readiness').scalar_one():
                                raise ValueError('target already initialized')
                            for name in manifest['mapping']['insert_order']:
                                if name not in manifest['mapping']['seed_tables'] and target.exec_driver_sql('SELECT EXISTS(SELECT 1 FROM public.'+identifier(name)+')').scalar_one():
                                    raise ValueError('unmanaged populated target')
                            if seed_signature(target,manifest)!=manifest['seed_signature']:
                                raise ValueError('target is not the known fresh seed state')
                            replace_data(source_db,'sqlite',target,'postgresql',manifest)
                            if data_evidence(target,'postgresql',manifest)!=expected:
                                raise ValueError('complete raw verification failed')
                            permission_mapping(target,'postgresql',ready)
                            target.exec_driver_sql('INSERT INTO workspace_admin.readiness VALUES(true,%s,%s,%s)',
                                                   (ready['identity_digest'],ready['entity_uuid'],ready['inviting_uuid']))
                            target.exec_driver_sql('INSERT INTO workspace_admin.migration_runs(run_id,source_hash,normalized_hash,manifest_hash,target_identity,evidence) VALUES(%s,%s,%s,%s,%s,%s::jsonb)',
                                                   (run_id,*wanted,json.dumps(protected_evidence)))
                        if file_hash(source)!=original_hash:raise ValueError('source changed during operation')
                # If killed after commit, the matching checkpoint recovers this
                # missing companion on retry; no external done-file authority.
                publish_mapping(mapping_output,ready)
                return {'status':'verified','tables':len(expected),'rows':sum(x['count'] for x in expected.values())}
    finally:engine.dispose()


def verify_database(source, root, manifest, run_id):
    engine=pg_engine()
    try:
        with normalized_source(source,manifest,root) as normalized,sqlite_read(normalized) as src:
            expected=data_evidence(src,'sqlite',manifest)
            with locked_target(engine) as target:
                target=target.execution_options(isolation_level='REPEATABLE READ')
                with target.begin():
                    target.exec_driver_sql('SET TRANSACTION READ ONLY')
                    validate_postgres(target,manifest)
                    row=target.exec_driver_sql('SELECT source_hash,normalized_hash,manifest_hash,target_identity,evidence FROM workspace_admin.migration_runs WHERE run_id=%s',(run_id,)).one()
                    wanted=(file_hash(source),file_hash(normalized),fingerprint(manifest),target_identity(target,engine))
                    if tuple(row[:4])!=wanted or row[4]['tables']!=expected or data_evidence(target,'postgresql',manifest)!=expected:
                        raise ValueError('source/checkpoint/target divergence')
                    ready=row[4]['readiness']
                    actual_ready=target.exec_driver_sql('SELECT identity_digest,entity_uuid,inviting_uuid FROM workspace_admin.readiness WHERE singleton=true').one()
                    if tuple(map(str,actual_ready))!=(ready['identity_digest'],ready['entity_uuid'],ready['inviting_uuid']):
                        raise ValueError('checkpoint/readiness divergence')
            return {'status':'verified','tables':len(expected),'rows':sum(x['count'] for x in expected.values())}
    finally:engine.dispose()


def export_sqlite(output, manifest, mapping, mapping_output):
    engine=pg_engine()
    try:
        with tempfile.TemporaryDirectory(prefix='.workspace-export-',dir=output.parent) as directory:
            path=Path(directory)/'restored.db'
            migrate_sqlite_file(path,manifest)
            with locked_target(engine) as source:
                source=source.execution_options(isolation_level='REPEATABLE READ')
                with source.begin():
                    source.exec_driver_sql('SET TRANSACTION READ ONLY')
                    validate_postgres(source,manifest)
                    permission_mapping(source,'postgresql',mapping)
                    ready={**{key:str(UUID(mapping[key])) for key in ('entity_uuid','inviting_uuid')},'identity_digest':identity_digest(os.environ)}
                    recorded=source.exec_driver_sql('SELECT identity_digest,entity_uuid,inviting_uuid FROM workspace_admin.readiness WHERE singleton=true').one()
                    if tuple(map(str,recorded))!=(ready['identity_digest'],ready['entity_uuid'],ready['inviting_uuid']):raise ValueError('readiness/identity mismatch')
                    expected=data_evidence(source,'postgresql',manifest)
                    with sqlite_write(path) as target:
                        target.execute('PRAGMA foreign_keys=ON')
                        target.execute('BEGIN IMMEDIATE')
                        replace_data(source,'postgresql',target,'sqlite',manifest)
                        validate_sqlite(target,manifest)
                        if data_evidence(target,'sqlite',manifest)!=expected:raise ValueError('inverse raw verification failed')
                    with sqlite_write(path) as target:target.execute('PRAGMA journal_mode=DELETE')
            path.chmod(0o400)
            publish_mapping(mapping_output,ready)
            os.link(path,output)
            return {'status':'verified','tables':len(expected),'rows':sum(x['count'] for x in expected.values())}
    finally:engine.dispose()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Workspace offline operation refused (" + type(exc).__name__ + ").", file=sys.stderr)
        raise SystemExit(1) from None
