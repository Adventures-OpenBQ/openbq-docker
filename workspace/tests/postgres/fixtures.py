# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Disposable, generated-only Docker fixture infrastructure; no operator stores."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
DOCKER = os.environ.get("DOCKER", "docker")
SOURCE_IMAGE = "openbq-workspace-local:2.0.0"


def docker(*args, timeout=120, check=True, **kwargs):
    result = subprocess.run([DOCKER, *args], capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and result.returncode:
        raise RuntimeError("disposable Docker operation failed (details retained privately)")
    return result


def prepare():
    path = Path(tempfile.mkdtemp(prefix="openbq-task52-"))
    path.chmod(0o700)
    ident = path.name.lower()
    password = secrets.token_hex(24)
    jwt_key = secrets.token_hex(48)
    enc = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
    payload = enc(b'{"alg":"HS256","typ":"JWT"}') + "." + enc(b'{"sub":"openbb"}')
    jwt = payload + "." + enc(hmac.new(jwt_key.encode(), payload.encode(), hashlib.sha256).digest())
    config = dict(DATABASE_TYPE="postgresql", DB_HOST="database", DB_PORT="5432", DB_NAME="postgres",
                  READ_DB_USER="postgres", WRITE_DB_USER="postgres", READ_DB_PASSWORD=password,
                  **{'WRITE_DB_PASSWORD':password, 'POSTGRES_PASSWORD':password},
                  OPENBB_AES_KEY=secrets.token_hex(8), JWT_SECRET=jwt_key, OPENBB_AUTH_TOKEN=jwt,
                  LOCAL_STORAGE_SECRET_KEY=secrets.token_urlsafe(32),
                  DB_POOL_SIZE="2", DB_MAX_OVERFLOW="0", DB_POOL_TIMEOUT="30", WORKERS="1",
                  REDIS_HOST="redis", REDIS_PASS="", SELFURL="http://localhost:3000/api",
                  FRONTENDURL="http://localhost:3000", PROURL="http://localhost:3000", MODE="lite",
                  WORKSPACE_POSTGRES_ALLOW_PLAINTEXT="1")
    env = path / "fixture.env"
    env.write_text("".join(f"{key}={value}\n" for key, value in config.items()))
    env.chmod(0o600)
    docker("network", "create", "--label", "openbq.task=5.2", ident)
    docker("run", "-d", "--name", ident + "-pg", "--label", "openbq.task=5.2", "--network", ident,
           "--network-alias", "database", "--env-file", str(env), "--tmpfs", "/var/lib/postgresql/data",
           "postgres:16.11-alpine")
    for _ in range(60):
        if docker("exec", ident + "-pg", "pg_isready", "-U", "postgres", check=False).returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("fixture PostgreSQL readiness timeout")
    (path / "identity.json").write_text(json.dumps({"network": ident, "postgres": ident + "-pg"}))
    return path


def source_run(path, *command, timeout=120, environment=None, env_file=None):
    """Source-only characterization, never substituted for the final compiled-image gate."""
    overrides = [part for key, value in (environment or {}).items() for part in ("-e", key + "=" + value)]
    return docker("run", "--rm", "--platform", "linux/amd64", "--network", path.name,
                  "--env-file", str(env_file or path / "fixture.env"), *overrides, "--entrypoint", "python", "-e", "PYTHONPATH=/source",
                  "-v", str(ROOT / "workspace/build-context/backend") + ":/source:ro",
                  "-v", str(path) + ":/fixture", "-w", "/source", SOURCE_IMAGE, *command,
                  timeout=timeout, check=False)


if __name__ == "__main__":
    print(prepare())


def populate_full_sqlite(path, manifest_path, ciphertext):
    """Generated complete physical fixture; no ORM transfer or operator input."""
    import gzip
    import sqlite3
    import uuid
    manifest=json.loads(Path(manifest_path).read_text())
    tables=manifest['mapping']['tables']
    db=sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    q=lambda name:'"'+name.replace('"','""')+'"'
    def rows(table):
        cursor=db.execute('SELECT * FROM '+q(table))
        names=[c[0] for c in cursor.description]
        return [dict(zip(names,row)) for row in cursor]
    def insert(table,row):
        db.execute('INSERT INTO '+q(table)+'('+','.join(map(q,row))+') VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    admin=next(row for row in rows('user') if row['email']=='fixture@example.com')
    admin_perm=next(row for row in rows('permissions_entity_map') if row['uuid']==admin['permissions_uuid'])
    entity=next(row for row in rows('entity') if row['uuid']==admin_perm['entity_uuid'])
    second_entity={**entity,'uuid':uuid.uuid4().bytes,'name':'Second generated entity'}
    insert('entity',second_entity)
    second_admin=None
    for permission in rows('permissions_entity_map'):
        if permission['entity_uuid']==entity['uuid']:
            clone={**permission,'uuid':uuid.uuid4().bytes,'entity_uuid':second_entity['uuid']}
            insert('permissions_entity_map',clone)
            if clone['name']=='Admin':second_admin=clone['uuid']
    second={**admin,'uuid':uuid.uuid4().bytes,'email':'second@example.com','clean_email':'second@example.com',
            'username':None,'permissions_uuid':second_admin,'auth_token':None,'is_superuser':0,
            'referral_code':secrets.token_hex(4)}
    insert('user',second)
    db.execute('UPDATE user SET pro_display_settings=? WHERE uuid=?',
               (json.dumps(json.dumps({'theme':'dark','fixtureExtension':{'large':12345678901234567890,'nested':['x',None]}})),admin['uuid']))
    db.execute('UPDATE user SET pro_zero_to_hero=? WHERE uuid=?',('null',second['uuid']))
    for table in manifest['mapping']['insert_order']:
        if rows(table):continue
        spec=tables[table];row={}
        for column in spec['columns']:
            name=column['name'];policy=column['policy'];details=column['type_details']
            foreign=next((fk for fk in spec['foreign_keys'] if fk['constrained_columns']==[name]),None)
            if foreign:
                parent=foreign['referred_table']
                if parent==table:value=None
                elif parent=='user':value=admin['uuid']
                elif parent=='entity':value=entity['uuid']
                else:value=rows(parent)[0][foreign['referred_columns'][0]]
            elif policy=='uuid-bytes':value=uuid.uuid4().bytes
            elif policy in ('datetime','utc-datetime'):
                value=None if column['nullable'] and name not in ('created_date','updated_date') else '2030-01-02 03:04:05.123456'
            elif policy=='boolean':value=0
            elif policy=='integer':value=1
            elif policy=='float':value=1.25
            elif policy=='bytes':
                content={'name':'Generated fixture','extension':{'bytes':'preserved'}}
                if table=='user_app':content={'name':'Generated app','widgets':[],'fixtureExtension':{'x':1}}
                if table=='user_skills':content='generated skill'
                value=gzip.compress((content if isinstance(content,str) else json.dumps(content)).encode(),mtime=123)
            elif policy=='json':value='{}'
            elif details.get('enums'):value=details['enums'][0]
            else:
                value=table+'_'+name
                if name=='share_widgets':value='private'
                elif name=='system_id':value='docks'
                elif name=='endpointHeaders':value=ciphertext
                elif name in ('headers','copilots') and table=='custom_copilot':value='{}' # valid legacy plaintext encrypted field
                elif 'email' in name:value='synthetic@example.com'
                elif 'url' in name.lower():value='https://fixture.invalid/resource'
                if details.get('length'):value=value[:details['length']]
            row[name]=value
        if table=='stored_file':row['is_confirmed']=1 if 'is_confirmed' in row else row.get('is_confirmed')
        row={k:v for k,v in row.items() if any(c['name']==k for c in spec['columns'])}
        insert(table,row)
    # A valid nullable two-app FK cycle and distinct bytes for equal gzip content.
    app=rows('vendor_app')[0]
    clone={**app,'uuid':uuid.uuid4().bytes,'name':'Generated cycle','parent_app_uuid':app['uuid']}
    insert('vendor_app',clone)
    db.execute('UPDATE vendor_app SET parent_app_uuid=? WHERE uuid=?',(clone['uuid'],app['uuid']))
    item=rows('dashboard_item')[0]
    clone={**item,'uuid':uuid.uuid4().bytes,'content':gzip.compress(gzip.decompress(item['content']),mtime=456)}
    insert('dashboard_item',clone)
    assert clone['content']!=item['content']
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    counts={name:db.execute('SELECT count(*) FROM '+q(name)).fetchone()[0] for name in tables}
    assert all(counts.values()),'every actual table must be populated'
    db.commit();db.execute('PRAGMA journal_mode=DELETE');db.close()
    return {'counts':counts,'mapping':{'entity_uuid':str(uuid.UUID(bytes=entity['uuid'])),'inviting_uuid':str(uuid.UUID(bytes=admin['uuid']))}}


def prepare_roles(path, database='openbq_workspace_import'):
    from urllib.parse import quote
    config=dict(line.split('=',1) for line in (path/'fixture.env').read_text().splitlines())
    rolepass={role:secrets.token_hex(12)+'@:/%?#psycopg2-pymysql%40百分比' for role in ('migrator','read','write')}
    provision=dict(PGHOST='database',PGUSER='postgres',PGPASSWORD=config.pop('POSTGRES_PASSWORD'),PGDATABASE='postgres')
    provision.update({'WORKSPACE_'+role.upper()+'_PASSWORD':password for role,password in rolepass.items()})
    def write(name,values):
        (path/name).write_text(''.join(k+'='+v+'\n' for k,v in values.items()));(path/name).chmod(0o600)
    write('provision.env',provision)
    config.update(DB_NAME=database,READ_DB_USER='openbq_workspace_read',WRITE_DB_USER='openbq_workspace_write',READ_DB_PASSWORD=rolepass['read'],WRITE_DB_PASSWORD=rolepass['write'],REDIS_HOST='127.0.0.1')
    write('runtime.env',config)
    config.update(READ_DB_USER='openbq_workspace_migrator',WRITE_DB_USER='openbq_workspace_migrator',READ_DB_PASSWORD=rolepass['migrator'],WRITE_DB_PASSWORD=rolepass['migrator'],WORKSPACE_MIGRATION_ROLE='openbq_workspace_owner')
    config['WORKSPACE_TARGET_DSN']='postgresql+psycopg2://openbq_workspace_migrator:'+quote(rolepass['migrator'],safe='')+'@database:5432/'+database
    write('maintenance.env',config)
    return docker('run','--rm','--network',path.name,'--env-file',str(path/'provision.env'),
                  '-v',str(ROOT/'workspace/postgres/provision.sql')+':/provision.sql:ro',
                  'postgres:16.11-alpine','psql','-v','workspace_db='+database,'-f','/provision.sql',check=False)


def configure_tls(path):
    """Enable TLS only on the task-owned disposable server, retaining its data."""
    tls=path/'tls';tls.mkdir(mode=0o700,exist_ok=True)
    def openssl(*args):
        result=subprocess.run(['/usr/bin/openssl',*args],cwd=tls,capture_output=True,text=True)
        if result.returncode:raise RuntimeError('synthetic certificate generation failed')
    (tls/'ca.cnf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=v3_ca\n[dn]\n[v3_ca]\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\nbasicConstraints=critical,CA:true\nkeyUsage=critical,keyCertSign,cRLSign\n')
    for prefix in ('ca','untrusted'):
        openssl('req','-x509','-newkey','rsa:2048','-nodes','-keyout',prefix+'.key',
                '-out',prefix+'.crt','-days','2','-subj','/CN=Workspace synthetic '+prefix,'-config','ca.cnf')
    openssl('req','-newkey','rsa:2048','-nodes','-keyout','server.key','-out','server.csr','-subj','/CN=database')
    (tls/'extensions.cnf').write_text('subjectAltName=DNS:database\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nbasicConstraints=critical,CA:false\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
    openssl('x509','-req','-in','server.csr','-CA','ca.crt','-CAkey','ca.key','-CAcreateserial',
            '-out','server.crt','-days','2','-extfile','extensions.cnf')
    for file in tls.glob('*.key'):file.chmod(0o600)
    name=path.name+'-pg'
    for file in ('server.key','server.crt'):docker('cp',str(tls/file),name+':/tmp/'+file)
    docker('exec',name,'chown','postgres:postgres','/tmp/server.key','/tmp/server.crt')
    docker('exec',name,'chmod','600','/tmp/server.key')
    sql="ALTER SYSTEM SET ssl='on';\nALTER SYSTEM SET ssl_cert_file='/tmp/server.crt';\nALTER SYSTEM SET ssl_key_file='/tmp/server.key';\nSELECT pg_reload_conf();\n"
    docker('exec','-i',name,'psql','-U','postgres','-v','ON_ERROR_STOP=1',input=sql)
    for _ in range(20):
        result=docker('exec',name,'psql','-U','postgres','-Atc','SHOW ssl')
        if result.stdout.strip()=='on':return
        time.sleep(.2)
    raise RuntimeError('fixture TLS configuration did not load')


def image_run(path, *command, env_file=None, environment=None, timeout=180):
    image=os.environ['WORKSPACE_TEST_IMAGE']
    overrides=[part for key,value in (environment or {}).items() for part in ('-e',key+'='+value)]
    return docker('run','--rm','--platform','linux/amd64','--network',path.name,
                  '--env-file',str(env_file or path/'runtime.env'),*overrides,
                  '--entrypoint','python','-e','PYTHONPATH=/opt/code',
                  '-v',str(ROOT/'workspace/tests/postgres')+':/tests:ro',
                  '-v',str(path)+':/fixture',image,*command,timeout=timeout,check=False)


def create_database(path, name):
    if not name.replace('_','').isalnum():raise ValueError('invalid fixture database name')
    sql=(ROOT/'workspace/postgres/provision.sql').read_text()
    sql='\\set ON_ERROR_STOP on\n'+sql[sql.index('CREATE DATABASE'):]
    return docker('exec','-i',path.name+'-pg','psql','-U','postgres','-v','workspace_db='+name,
                  input=sql,check=False)


def qualify_content(path):
    """Fill synthetic blobs with the pinned domain shapes; never repair operator input."""
    import gzip
    import sqlite3
    chat={'createdAt':1893553445123,'label':'Generated preserved chat','messages':[],
          'fixtureExtension':{'unknown':'preserved'}}
    message={'role':'human','copilotId':'openbb-copilot','timestamp':1893553445123,
             'content':'Generated searchable message','fixtureExtension':{'unknown':True}}
    values={
        'copilot_chat':{'content':chat,'artifacts':[]},
        'copilot_chat_old':{'content':chat},
        'copilot_chats':{'chats':[]},
        'copilot_messages':{'content':message},
        'mcp_servers':{'servers':[{'id':'synthetic-server','name':'Generated','url':'https://fixture.invalid/mcp','enabled':False}]},
        'trading_view':{'charts_state':{'charts':[],'fixtureExtension':{'x':1}},'settings':{'fixtureExtension':'preserved'}},
        'vendor_app':{'apps_json_cache':[],'widgets_json_cache':{'widgets':[]}},
    }
    with sqlite3.connect(path) as db:
        for table,columns in values.items():
            for column,value in columns.items():
                db.execute('UPDATE "'+table+'" SET "'+column+'"=?',(gzip.compress(json.dumps(value).encode(),mtime=123),))
        db.execute("UPDATE custom_copilot SET copilots='[]'")
        db.execute("UPDATE widget_metadata SET widget_type='chart'")
        db.execute("UPDATE developer_onboarding SET primary_usage='personal',programming_experience='basic',data_types='[\"equities\"]'")
        db.execute("UPDATE user_skills SET slug='generated-skill'")
        db.execute("UPDATE file_widget SET extension='csv'")
        db.execute("UPDATE stored_file SET extension='csv'")
        db.execute("UPDATE login SET ip_address='192.0.2.52'")  # RFC5737 documentation address
        from uuid import UUID
        stored=UUID(bytes=db.execute('SELECT uuid FROM stored_file LIMIT 1').fetchone()[0])
        db.execute('UPDATE stored_file_share SET stored_file_uuids=?',(str(stored),))
        entity=db.execute("SELECT entity_uuid FROM permissions_entity_map WHERE uuid=(SELECT permissions_uuid FROM user WHERE email='second@example.com')").fetchone()[0]
        if not db.execute('SELECT 1 FROM entity_entitlement WHERE entity_uuid=?',(entity,)).fetchone():
            from uuid import uuid4
            cursor=db.execute('SELECT * FROM entity_entitlement LIMIT 1')
            row=dict(zip((c[0] for c in cursor.description),cursor.fetchone()))
            row.update(uuid=uuid4().bytes,entity_uuid=entity)
            db.execute('INSERT INTO entity_entitlement ('+','.join('"'+c+'"' for c in row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    return values


def api_request(base, path, server_token, *, token=None, body=None, method=None):
    import urllib.request
    import urllib.error
    headers={'X-OpenBB-Authorization':'Bearer '+server_token,'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    if token:headers['Authorization']='Bearer '+token
    request=urllib.request.Request(base+'/api'+path,headers=headers,
        data=json.dumps(body).encode() if body is not None else None,method=method)
    try:
        with urllib.request.urlopen(request,timeout=40) as response:
            status=response.status;data=response.read()
    except urllib.error.HTTPError as error:status=error.code;data=error.read()
    try:return status,json.loads(data)
    except json.JSONDecodeError:
        for line in data.decode('utf-8').splitlines():
            if line.startswith('data: '):return status,json.loads(line[6:])
        return status,None


def api_base(path, name):
    state=json.loads(docker('inspect',name).stdout)[0]
    if not state['State']['Running']:raise RuntimeError('fixture listener process exited')
    return 'http://127.0.0.1:'+state['NetworkSettings']['Ports']['3000/tcp'][0]['HostPort']


def populate_auth_cases(path, companion):
    """Pinned sessions/PATs: PAT has revocation, no expiry field at this pin."""
    import sqlite3
    from uuid import uuid4,UUID
    with sqlite3.connect(path) as db:
        db.row_factory=sqlite3.Row
        user=dict(db.execute("SELECT * FROM user WHERE email='fixture@example.com'").fetchone())
        def insert(table,row):
            db.execute('INSERT INTO "'+table+'" ('+','.join('"'+c+'"' for c in row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        coworker={**user,'uuid':uuid4().bytes,'email':'coworker@example.com','clean_email':'coworker@example.com',
                  'username':None,'auth_token':None,'is_superuser':0,'referral_code':secrets.token_hex(4)}
        coworker['permissions_uuid']=db.execute("SELECT uuid FROM permissions_entity_map WHERE name='User' AND entity_uuid=(SELECT entity_uuid FROM permissions_entity_map WHERE uuid=?)",(user['permissions_uuid'],)).fetchone()[0]
        insert('user',coworker)
        old=dict(db.execute('SELECT * FROM session LIMIT 1').fetchone());valid=uuid4();expired=uuid4()
        db.execute('UPDATE session SET user_uuid=?,pro=1,source=?,expiration_date=?,api_token=NULL,uuid=? WHERE uuid=?',
                   (user['uuid'],'excel','2035-01-02 03:04:05.123456',valid.bytes,old['uuid']))
        insert('session',{**old,'uuid':expired.bytes,'user_uuid':user['uuid'],'api_token':None,'pro':1,'source':'excel','expiration_date':'2000-01-02 03:04:05.123456'})
        pat=dict(db.execute('SELECT * FROM personal_access_token LIMIT 1').fetchone())
        tokens={}
        for label in ('valid','revoked'):
            token='obb_mcp_'+secrets.token_urlsafe(32);tokens[label]=token
            values={**pat,'uuid':uuid4().bytes,'user_uuid':user['uuid'],'name':'Synthetic '+label,
                    'token_type':'workspace_mcp','token_hash':hashlib.sha256(token.encode()).hexdigest(),
                    'token_prefix':token[:20],'revoked_at':None if label=='valid' else '2026-01-02 03:04:05.123456','last_used_at':None}
            if label=='valid':
                db.execute('DELETE FROM personal_access_token WHERE uuid=?',(pat['uuid'],))
            insert('personal_access_token',values)
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    value={'session_valid':str(valid),'session_expired':str(expired),'session_revoked':str(uuid4()),
           'pat_valid':tokens['valid'],'pat_revoked':tokens['revoked']}
    companion.write_text(json.dumps(value));companion.chmod(0o600)


def make_legacy_source(current, baseline, output, manifest):
    """Create a complete 0d4 fixture through its actual baseline schema, no stamp."""
    import shutil
    import sqlite3
    shutil.copyfile(baseline,output);output.chmod(0o600)
    db=sqlite3.connect(output)
    try:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('ATTACH DATABASE ? AS fixture_source',(str(current),))
        order=[t for t in manifest['mapping']['insert_order'] if t!='system_dashboard']
        with db:
            db.execute('PRAGMA defer_foreign_keys=ON')
            for table in reversed(order):db.execute('DELETE FROM "'+table+'"')
            for table in order:
                columns=','.join('"'+c['name']+'"' for c in manifest['mapping']['tables'][table]['columns'])
                db.execute('INSERT INTO main."'+table+'" ('+columns+') SELECT '+columns+' FROM fixture_source."'+table+'"')
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        db.execute('DETACH DATABASE fixture_source')
        db.execute('PRAGMA journal_mode=DELETE')
    finally:db.close()
    output.chmod(0o400)


def special_role_and_isolation(path):
    """Fixture-only Unicode URL credentials and fresh other-app ACL boundaries."""
    role='fixture:psycopg2@百分比%40?/#'
    env=dict(line.split('=',1) for line in (path/'runtime.env').read_text().splitlines())
    # The password is read privately by psql, never passed through SQL literals or argv.
    sql='''\n\\set ON_ERROR_STOP on
\\getenv role_password READ_DB_PASSWORD
CREATE ROLE "fixture:psycopg2@百分比%40?/#" LOGIN PASSWORD :'role_password';
GRANT openbq_workspace_read TO "fixture:psycopg2@百分比%40?/#";
CREATE DATABASE openbq_settings_isolation;
REVOKE ALL ON DATABASE openbq_settings_isolation FROM PUBLIC;
CREATE DATABASE temporal_catalog_isolation;
REVOKE ALL ON DATABASE temporal_catalog_isolation FROM PUBLIC;
'''
    result=docker('run','--rm','--network',path.name,'--env-file',str(path/'runtime.env'),
                  '--env-file',str(path/'provision.env'),'-i','postgres:16.11-alpine','psql',input=sql,check=False)
    if result.returncode:raise RuntimeError('special role fixture provisioning failed')
    env['READ_DB_USER']=role
    env['WORKSPACE_BAD_TLS_HOST']=path.name+'-pg'
    output=path/'unicode-runtime.env';output.write_text(''.join(k+'='+v+'\n' for k,v in env.items()));output.chmod(0o600)
    return output


def prepare_complete():
    """Generate a NEW complete fixture from the pinned image, never reuse user stores."""
    import shutil
    import sqlite3
    from uuid import UUID
    path=prepare().resolve()
    image=os.environ['WORKSPACE_TEST_IMAGE']
    values=dict(line.split('=',1) for line in (path/'fixture.env').read_text().splitlines())
    values.update(DATABASE_TYPE='sqlite',DB_PATH='/data/openbb.db',OPENBB_ADMIN_EMAIL='fixture@example.com',
        **{'OPENBB_ADMIN_PASSWORD':secrets.token_urlsafe(24)+'Aa1!'},REDIS_HOST='127.0.0.1')
    lifecycle=path/'lifecycle.env';lifecycle.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));lifecycle.chmod(0o600)
    # Both fingerprints originate in the real Alembic histories, never DDL copies/stamps.
    for revision in ('0d4a342f4c26','9b1d0c5e7a42'):
        result=image_run(path,'-m','alembic','upgrade',revision,env_file=lifecycle,
            environment={'DB_PATH':'/fixture/schema-'+revision+'.db'})
        (path/('schema-'+revision+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('actual SQLite fixture history failed')
    baseline=path/'sqlite-generated';baseline.mkdir(mode=0o700)
    name=path.name+'-generated'
    docker('run','-d','--name',name,'--label','openbq.task=5.2','--platform','linux/amd64',
        '--network',path.name,'--env-file',str(lifecycle),'-p','127.0.0.1::3000','-v',str(baseline)+':/data',image)
    try:
        base=api_base(path,name)
        for _ in range(120):
            try:
                status,_=api_request(base,'/health',values['OPENBB_AUTH_TOKEN'])
                if status==200:break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('fresh synthetic SQLite bootstrap did not become ready')
        docker('exec',name,'redis-cli','SET','task52:companion','generated-preserved-value')
        docker('exec',name,'redis-cli','SAVE')
    finally:
        docker('stop','-t','40',name)
        logs=docker('logs',name,check=False)
        (path/'synthetic-legacy-bootstrap.log').write_text(logs.stdout+logs.stderr)
        (path/'synthetic-legacy-bootstrap.log').chmod(0o600)
    source=path/'full-source-v6.db'
    original=sqlite3.connect(baseline/'openbb.db');copied=sqlite3.connect(source)
    try:
        original.backup(copied)  # committed shutdown WAL pages remain authoritative
        copied.execute('PRAGMA journal_mode=DELETE')
    finally:copied.close();original.close()
    result=image_run(path,'-c',"from api.aes import AESCipher\nfrom api.schemas import ApiSourceEndpointHeaders\nfrom utilities.config import settings\nfrom pathlib import Path\nimport json\nheaders=[ApiSourceEndpointHeaders(key='X-Synthetic',value='preserved').model_dump()]\nPath('/fixture/ciphertext.txt').write_bytes(AESCipher(settings.OPENBB_AES_KEY).encrypt(json.dumps(headers)))",env_file=lifecycle)
    (path/'synthetic-encryption.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('actual synthetic encryption failed')
    manifest_path=ROOT/'workspace/postgres/schema_manifest.json'
    accounting=populate_full_sqlite(source,manifest_path,(path/'ciphertext.txt').read_text())
    qualify_content(source);populate_auth_cases(source,path/'auth-cases-v5.json')
    mapping=accounting['mapping']
    (path/'mapping-input.json').write_text(json.dumps(mapping));(path/'mapping-input.json').chmod(0o600)
    manifest=json.loads(manifest_path.read_text())
    make_legacy_source(source,path/'schema-0d4a342f4c26.db',path/'full-source-v6-0d4.db',manifest)
    with sqlite3.connect(source) as db:
        counts={table:db.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0] for table in manifest['mapping']['tables']}
    if not all(counts.values()):raise RuntimeError('complete fixture must populate every table')
    (path/'full-accounting.json').write_text(json.dumps({'counts':counts,'empty_reasons':{},'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}));(path/'full-accounting.json').chmod(0o600)
    source.chmod(0o400)
    compatible=path/'sqlite-baseline-v6';shutil.copytree(baseline,compatible)
    for file in ('openbb.db','openbb.db-wal','openbb.db-shm'):(compatible/file).unlink(missing_ok=True)
    shutil.copyfile(source,compatible/'openbb.db');(compatible/'openbb.db').chmod(0o600)
    identity={key:values[key] for key in ('JWT_SECRET','OPENBB_AUTH_TOKEN','OPENBB_AES_KEY','LOCAL_STORAGE_SECRET_KEY')}
    mapping['identity_digest']=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    (compatible/'permission-map.json').write_text(json.dumps(mapping));(compatible/'permission-map.json').chmod(0o600)
    with sqlite3.connect(source) as db:
        names=[row[0] for row in db.execute('SELECT s3_file_name FROM stored_file')]
    for name in names:
        file=compatible/'storage'/name
        if not file.resolve().is_relative_to((compatible/'storage').resolve()):raise RuntimeError('unsafe synthetic storage path')
        file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'synthetic,value\nretained,52\n')
    (compatible/'companion-inventory.json').write_text(json.dumps(names));(compatible/'companion-inventory.json').chmod(0o600)

    # Validate the complete generated source through pinned converters and actual
    # return models before the first PostgreSQL import. Only this writable COPY
    # receives authorized baseline API session/audit writes.
    model_probe="""from api.models.model_helpers import Base
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from pathlib import Path
import tempfile,shutil,json
errors=[];checked=0
with tempfile.TemporaryDirectory(prefix='.domain-check-',dir='/fixture') as folder:
 copy=Path(folder)/'source.db';shutil.copyfile('/fixture/full-source-v6.db',copy);copy.chmod(0o600)
 engine=create_engine('sqlite:///'+str(copy))
 try:
  with Session(engine) as session:
   for mapper in sorted(Base.registry.mappers,key=lambda m:m.class_.__name__):
    try:session.execute(select(mapper.class_)).scalars().all();checked+=1
    except Exception as error:
     errors.append({'model':mapper.class_.__name__,'error':type(error).__name__})
     session.rollback()
 finally:engine.dispose()
print(json.dumps({'checked':checked,'errors':errors}))
raise SystemExit(bool(errors))
"""
    result=image_run(path,'-c',model_probe,env_file=lifecycle)
    (path/'source-model-validation.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('generated source failed pinned model conversion')
    baseline_values={**values,'WORKSPACE_DB_ACTION':'serve',
        'WORKSPACE_PERMISSION_MAP_FILE':'/data/permission-map.json','FOLDER_STORAGE_PATH':'/data/storage'}
    baseline_env=path/'source-baseline.env'
    baseline_env.write_text(''.join(k+'='+v+'\n' for k,v in baseline_values.items()));baseline_env.chmod(0o600)
    baseline_name=path.name+'-source-baseline'
    docker('run','--rm','--platform','linux/amd64','--entrypoint','chown',
        '-v',str(compatible)+':/data',image,'-R','appuser:appuser','/data')
    docker('run','-d','--name',baseline_name,'--label','openbq.task=5.2','--platform','linux/amd64',
        '--network',path.name,'--env-file',str(baseline_env),'-p','127.0.0.1::3000',
        '-v',str(compatible)+':/data',image)
    try:
        base=api_base(path,baseline_name)
        for _ in range(90):
            try:
                if api_request(base,'/health',values['OPENBB_AUTH_TOKEN'])[0]==200:break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('complete source baseline readiness failed')
        import sys
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'workspace/tests/postgres'),
            '-p','test_lifecycle.py','-k','AppAPITests','-v'],capture_output=True,text=True,
            env={**os.environ,'WORKSPACE_FIXTURE':str(path),'WORKSPACE_APP_NAMES':baseline_name,
                 'WORKSPACE_API_LABEL':'source-baseline','WORKSPACE_AFTER_WRITES':'0'})
        (path/'source-baseline-api.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('complete source baseline API failed')
        if docker('exec',baseline_name,'redis-cli','GET','task52:companion').stdout.strip()!='generated-preserved-value':
            raise RuntimeError('source Redis companion was not retained')
    finally:docker('stop','-t','40',baseline_name,check=False)
    result=prepare_roles(path)
    if result.returncode:raise RuntimeError('fixture role provisioning failed')
    result=image_run(path,'-m','scripts.workspace_pg','migrate',env_file=path/'maintenance.env')
    (path/'initial-pg-migration.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('initial full PG history failed')
    configure_tls(path);special_role_and_isolation(path)
    result=image_run(path,'-m','scripts.workspace_migration','import','--root','/fixture',
        '--source','/fixture/full-source-v6.db','--run-id','probe-fixture',
        '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/probe-map.json',
        env_file=path/'maintenance.env')
    (path/'probe-import.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('complete probe database import failed')
    (path/'fixture-ready.json').write_text(json.dumps({'image':image,'tables':len(counts),'rows':sum(counts.values()),'version':2}))
    return path
