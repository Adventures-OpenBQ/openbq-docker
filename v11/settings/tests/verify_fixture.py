#!/usr/bin/env python3
"""Task-owned real PostgreSQL + installed ODP + two independent Node22 gateways."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import uuid

H = Path(__file__).resolve().parents[3]
DOCKER = os.environ.get("DOCKER", "/Applications/Docker.app/Contents/Resources/bin/docker")
IMAGE = os.environ.get("SETTINGS_IMAGE", "openbq-task51:fixture")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    directory = args.artifacts.resolve(); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = 'openbq-task51-' + uuid.uuid4().hex[:8]
    resources = []; checks = []
    def docker(*args, input=None, check=True):
        result = subprocess.run([DOCKER, *map(str, args)], input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            (directory/'last-error.txt').write_bytes(result.stdout + result.stderr)
            raise AssertionError('fixture Docker command failed: ' + args[0])
        return result
    def record(name):
        checks.append(name); print('PASS ' + name, flush=True)
        (directory/'checks.json').write_text(json.dumps(checks, indent=2))
    def save(name, content):
        path = directory/name; path.write_text(content); path.chmod(0o600); return path
    def run(name, *args):
        full = prefix+'-'+name
        docker('run','-d','--name',full,*args); resources.append(full); return full
    def port(name, internal):
        return int(docker('port',name,str(internal)).stdout.decode().strip().rsplit(':',1)[1])
    def request(base, path, method='GET', body=None, headers=None, timeout=20):
        raw = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        req = urllib.request.Request(base+path, data=raw, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
    def wait(base, headers):
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            try:
                if request(base,'/pro/user',headers=headers,timeout=2)[0] == 200: return
            except Exception: pass
            time.sleep(1)
        raise AssertionError('API startup failed')
    def wait_gateway(base, headers):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                if request(base,'/state/00042',headers=headers,timeout=2)[0]==200:return
            except Exception:pass
            time.sleep(0.2)
        raise AssertionError('gateway did not become ready')
    token='fixture_gateway_token_task51_1234567890'
    password="fixture-Sentinel@:/%?#'\\-secret"
    principal='aaaaaaaa-1111-4111-8111-111111111111'
    basic={'Authorization':'Basic '+base64.b64encode(('fixture:'+password).encode()).decode(), 'Content-Type':'application/json'}
    bearer={'Authorization':'Bearer '+token, 'Content-Type':'application/json'}
    fixture_host='.'.join(('openbq','fixture','ts','net'))+':10000'
    gateway_headers={**bearer,'Host':fixture_host}
    # libpq quoted parameter input, not password interpolation in a URI.
    escape=lambda text: text.replace('\\','\\\\').replace("'", "\\'")
    def dsn(user, db='openbq_settings'):
        return f"host={prefix}-pg port=5432 dbname={db} user={user} password='{escape(password)}' connect_timeout=3 sslmode=disable"
    admin=save('pg.env','POSTGRES_PASSWORD='+password+'\nOPENBQ_SETTINGS_RUNTIME_PASSWORD='+password+'\nOPENBQ_SETTINGS_MIGRATION_PASSWORD='+password+'\n')
    runtime=save('runtime.env','\n'.join([
        'OPENBQ_SETTINGS_BACKEND=postgresql','OPENBQ_SETTINGS_GATEWAY_STATE=1',
        'OPENBQ_SETTINGS_DSN='+dsn('openbq_settings_runtime'),'OPENBQ_SETTINGS_PRINCIPAL_ID='+principal,
        'GATEWAY_TOKEN='+token,'OPENBB_API_AUTH=true','OPENBB_API_USERNAME=fixture','OPENBB_API_PASSWORD='+password])+'\n')
    migration=save('migration.env','OPENBQ_SETTINGS_MIGRATION_DSN='+dsn('openbq_settings_migrator')+'\n')
    def migrate(*args, expect=0):
        result=docker('run','--rm','--network',prefix,'--env-file',migration,'-v',str(directory)+':/fixture',
            '--entrypoint','python',IMAGE,'-m','openbq_settings_pg.migrate_json',*args,check=False)
        if result.returncode!=expect: (directory/'migration-error.txt').write_bytes(result.stdout+result.stderr)
        assert result.returncode==expect, 'migration command failed: '+args[0]+' exit='+str(result.returncode)+' expected='+str(expect)
        return result
    def sql(command, db='openbq_settings'):
        return docker('exec','-i',prefix+'-pg','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d',db,input=command.encode()).stdout.decode().strip()
    tls=directory/'tls'; tls.mkdir(mode=0o700)
    def openssl(*args):
        subprocess.run(['/usr/bin/openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Task51 fixture CA','-keyout',tls/'ca.key','-out',tls/'ca.crt')
    openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Wrong fixture CA','-keyout',tls/'wrong.key','-out',tls/'wrong.crt')
    openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN='+prefix+'-pg','-keyout',tls/'server.key','-out',tls/'server.csr')
    (tls/'extensions').write_text('subjectAltName=DNS:'+prefix+'-pg\n')
    openssl('x509','-req','-in',tls/'server.csr','-CA',tls/'ca.crt','-CAkey',tls/'ca.key','-CAcreateserial','-days','1','-extfile',tls/'extensions','-out',tls/'server.crt')
    # Only the CA file is mounted into runtime containers; never migration/admin env files.
    cert_mount=str(tls/'ca.crt')+':/tls/ca.crt:ro'
    runtime.write_text(runtime.read_text().replace('sslmode=disable','sslmode=verify-full sslrootcert=/tls/ca.crt'))
    migration.write_text(migration.read_text().replace('sslmode=disable','sslmode=verify-full sslrootcert=/fixture/tls/ca.crt'))
    try:
        docker('network','create',prefix)
        pg=run('pg','--network',prefix,'--env-file',admin,'-v',str(tls)+':/certs:ro',
            '--entrypoint','sh','postgres:16.11-alpine','-c',
            'cp /certs/server.key /tmp/server.key; cp /certs/server.crt /tmp/server.crt; chown postgres:postgres /tmp/server.key /tmp/server.crt; chmod 600 /tmp/server.key; exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key')
        for _ in range(60):
            if docker('exec',pg,'pg_isready','-h','127.0.0.1','-U','postgres',check=False).returncode == 0: break
            time.sleep(1)
        docker('exec','-i',pg,'psql','-X','-v','ON_ERROR_STOP=1','-v','settings_database=openbq_settings','-U','postgres',input=(H/'v11/settings/provision.sql').read_bytes())
        migrate('migrate'); migrate('migrate'); record('schema migration and repeat checksum')
        for name,value in [('OPENBQ_SETTINGS_BACKEND',''),('OPENBQ_SETTINGS_PRINCIPAL_ID',''),('GATEWAY_TOKEN',''),('WEB_CONCURRENCY','2')]:
            result=docker('run','--rm','--network',prefix,'--env-file',runtime,'-e',name+'='+value,IMAGE,check=False)
            assert result.returncode==1 and b'Settings unavailable' in result.stderr
            assert password.encode() not in result.stdout+result.stderr and token.encode() not in result.stdout+result.stderr
        record('actual launcher rejects invalid selector/principal/token/inherited workers before readiness')
        sql('CREATE DATABASE task51_bad_schema OWNER openbq_settings_owner; REVOKE ALL ON DATABASE task51_bad_schema FROM PUBLIC; GRANT CONNECT ON DATABASE task51_bad_schema TO openbq_settings_runtime;',db='postgres')
        bad_env=save('bad-schema.env',runtime.read_text().replace('dbname=openbq_settings ','dbname=task51_bad_schema '))
        invalid_start=run('invalid-start','--network',prefix,'--env-file',bad_env,'-v',cert_mount,IMAGE)
        invalid_workers=run('invalid-workers','--network',prefix,'--env-file',runtime,'-v',cert_mount,
          IMAGE,'python','-m','openbq_settings_pg.launch','--workers','2')
        source=directory/'source'; (source/'keys').mkdir(parents=True); (source/'state'/'00042').mkdir(parents=True)
        stem='a'*64
        mapping=save('mapping.json',json.dumps({stem:principal}))
        fixture={'extension':{'opaque':'untouched'},'theme':'dark'}
        (source/'keys'/(stem+'.json')).write_text(json.dumps(fixture))
        (source/'state'/'00042'/'settings.json').write_bytes(b' {"opaque":1,"opaque":2,"n":1e2} ')
        stamp='2026-10-15T00:00:00Z'
        (source/'keys'/(stem+'.dashboards.json')).write_text(json.dumps({'docks':{'content':{'opaque':'preserved'},'hidden':True,'revision':2,'created_date':stamp,'updated_date':stamp}}))
        (source/'keys'/(stem+'.apps.json')).write_text(json.dumps({'bbbbbbbb-1111-4111-8111-111111111111':{'content':{'extension':'preserved'},'created_date':stamp,'updated_date':stamp}}))
        before=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(source.rglob('*')) if p.is_file())).hexdigest()
        sql("INSERT INTO settings.principals VALUES ('github','unrelated')")
        migrate('import','--source','/fixture/source','--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
        assert sql('SELECT count(*) FROM settings.documents')=='0'
        sql("DELETE FROM settings.principals WHERE principal_id='unrelated'")
        record('unrelated empty principal target refused without writes')
        # Crash after all INSERT/checkpoint statements but before commit.
        interrupted = docker('run','--rm','--network',prefix,'--env-file',migration,'-v',str(directory)+':/fixture',
          '--entrypoint','python',IMAGE,'-c',
          "import os,psycopg; from pathlib import Path; from openbq_settings_pg.config import connection_info; from openbq_settings_pg.migrate_json import inventory,mapping,import_copy; c=psycopg.connect(connection_info(os.environ['OPENBQ_SETTINGS_MIGRATION_DSN'])); c.execute('SET ROLE openbq_settings_owner'); d,m=inventory(Path('/fixture/source'),mapping(Path('/fixture/mapping.json'))); import_copy(c,d,m); os._exit(17)",check=False)
        assert interrupted.returncode==17
        assert sql('SELECT count(*) FROM settings.documents')=='0'
        assert sql('SELECT count(*) FROM settings_admin.checkpoints')=='0'
        record('interrupted precommit import rolls back all documents and checkpoint')
        for command in ('inventory','import','verify','import'):
            migrate(command,'--source','/fixture/source','--mapping','/fixture/mapping.json','--quiesced-copy')
        record('mapped raw import checkpoint verify identical retry')
        # Recognized-family refusal checks operate on disposable copies only.
        import shutil
        bad=directory/'bad-source';shutil.copytree(source,bad)
        for mutation in ('unknown','malformed','unmapped','symlink','overquota','duplicate'):
            bad=directory/('bad-'+mutation);shutil.copytree(source,bad)
            if mutation=='unknown':(bad/'unrecognized.json').write_text('{}')
            if mutation=='malformed':(bad/'keys'/(stem+'.json')).write_text('{')
            if mutation=='unmapped':(bad/'keys'/('b'*64+'.json')).write_text('{}')
            if mutation=='symlink':(bad/'keys'/'escape.json').symlink_to('/etc/passwd')
            if mutation=='overquota':(bad/'state'/'00042'/'settings.json').write_text('"'+'x'*262145+'"')
            if mutation=='duplicate':(bad/'state'/'00042'/'settings%2Ejson').write_text('{}')
            print('CHECK inventory refusal '+mutation,flush=True)
            migrate('inventory','--source','/fixture/bad-'+mutation,'--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
        bad=directory/'bad-source';shutil.rmtree(bad);shutil.copytree(source,bad)
        (bad/'keys'/(stem+'.json')).write_text('{"changed":true}')
        migrate('import','--source','/fixture/bad-source','--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
        record('malformed/unmapped/unknown/symlink/overquota/encoded collision and divergent checkpoint refused')
        apis=[]; gateways=[]
        save('gateway.json',json.dumps({'settings':{'origin':'https://'+fixture_host,'apiUpstream':'v11','stateStorage':'postgresql','requestsPerMinute':600},
                                      'secrets':{'token':token,'apiUsername':'fixture','apiPassword':password}}))
        for suffix in ('a','b'):
            explicit_worker=['python','-m','openbq_settings_pg.launch','--host','0.0.0.0','--port','6900','--workers','1'] if suffix=='a' else []
            api=run('api-'+suffix,'--network',prefix,'--env-file',runtime,'-v',cert_mount,'-p','127.0.0.1::6900',IMAGE,*explicit_worker)
            apis.append('http://127.0.0.1:'+str(port(api,6900)))
            wait(apis[-1],basic)
            ip=docker('inspect','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',api).stdout.decode().strip()
            gw=run('gateway-'+suffix,'--network',prefix,'--add-host','openbq-v11:'+ip,'-p','127.0.0.1::8080',
                   '-v',str(H/'funnel-gateway')+':/gateway:ro','-v',str(H/'v11/settings/fixtures')+':/runner:ro',
                   '-v',str(directory)+':/fixture:ro','node:22','node','/runner/gateway.mjs')
            gateways.append('http://127.0.0.1:'+str(port(gw,8080)))
        for gateway in gateways:wait_gateway(gateway,gateway_headers)
        private='/_openbq/settings/v1/state/'
        for api in apis:
            assert request(api,'/pro/user',headers=bearer)[0]==401
            assert request(api,private+'00042',headers=basic)[0]==401
            assert request(api,private+'00042',headers=bearer)[0]==200
            assert request(api,'/api/v1/eodhd/equity/price/historical?symbol=TEST&start_date=2021-11-05&end_date=2021-11-06',headers=bearer)[0] in (401,403)
            assert json.loads(request(api,'/pro/user',headers=basic)[1])['pro_display_settings']==fixture
        record('installed ODP Basic and private Bearer boundaries; imported identity')
        assert docker('wait',invalid_workers).stdout.strip()==b'1'
        assert b'Settings requires one worker per container' in docker('logs',invalid_workers).stderr
        record('actual CLI workers 1 starts wrapped lifespan; workers 2 refuses startup')
        syntax=docker('run','--rm','--network',prefix,'-v',str(H/'v11/settings/fixtures')+':/runner:ro',
          '-v',str(directory)+':/fixture:ro','node:22','node','/runner/json-syntax.mjs',prefix+'-api-a')
        assert b'PASS actual Node22/private API JSON syntax parity' in syntax.stdout
        record(syntax.stdout.decode().strip().removeprefix('PASS '))
        assert docker('wait',invalid_start).stdout.strip()==b'3'
        failed_logs=docker('logs',invalid_start).stdout+docker('logs',invalid_start).stderr
        assert b'Application startup failed' in failed_logs and b'Application startup complete' not in failed_logs
        assert password.encode() not in failed_logs and token.encode() not in failed_logs
        record('actual ODP lifespan refuses missing settings schema before application readiness')
        sql('SET ROLE openbq_settings_owner; '+(H/'v11/settings/schema.sql').read_text()+
            "INSERT INTO settings_admin.schema_migrations VALUES ('unknown','wrong');",db='task51_bad_schema')
        for revision in ('unknown','settings-001'):
            sql("UPDATE settings_admin.schema_migrations SET revision='"+revision+"'",db='task51_bad_schema')
            result=docker('run','--rm','--network',prefix,'--env-file',bad_env,'-v',cert_mount,'--entrypoint','python',IMAGE,'-c',
              'from openbq_settings_pg.config import Config; from openbq_settings_pg.store import Store; s=Store(Config.read()); s.verify()',check=False)
            assert result.returncode==1 and b'Settings unavailable' in result.stderr
        record('real startup verifier refuses unknown schema revision and mismatched checksum')
        import http.client
        target=urllib.parse.urlsplit(apis[0]);connection=http.client.HTTPConnection(target.hostname,target.port)
        connection.putrequest('GET',private+'42');connection.putheader('Authorization',bearer['Authorization']);connection.putheader('Authorization',bearer['Authorization']);connection.endheaders()
        response=connection.getresponse();assert response.status==401;response.read();connection.close()
        assert request(apis[0],private+'42','OPTIONS',headers=bearer)[0]==405
        record('duplicate private Authorization and private OPTIONS refused')
        assert request(gateways[0],'/state/00042',headers=gateway_headers)[0]==200
        assert json.loads(request(gateways[1],'/state/42',headers=gateway_headers)[1])=={'files':{}}
        assert request(gateways[0],'/api/_openbq/settings/v1/state/00042',headers=gateway_headers)[0]==404
        record('two independent gateways fixed private upstream and leading-zero identity isolation')
        def write_dashboard(i):
            ident=str(uuid.UUID(int=i+100))
            return request(apis[i%2],'/pro/dash/sync','POST',{'items':{ident:{'name':str(i),'extension':'retained'}}},basic)[0]
        with ThreadPoolExecutor(max_workers=8) as pool: assert set(pool.map(write_dashboard,range(16)))=={200}
        owned=json.loads(request(apis[1],'/pro/dash/sync/owned',headers=basic)[1])['owned']
        assert len(owned)==17 and sum(bool(v['content'].get('isRoot')) for v in owned.values())==1
        for revision,status in ((10,200),(9,409),(10,200),(11,200)):
            assert request(apis[revision%2],'/pro/dash/sync/system/docks','PUT',{'revision':revision,'content':{'value':revision}},basic)[0]==status
        for i in range(2):
            assert request(apis[i],'/pro/display-settings','POST',{'last':i,'extension':'kept'},basic)[0]==200
        assert json.loads(request(apis[0],'/pro/user',headers=basic)[1])['pro_display_settings']['last']==1
        record('cross-process disjoint first writes/root once; docks stale/equal/new; last-write-wins')
        raw=b'{"x":1}'+b'\t'*262137
        def put(i): return request(gateways[i%2],f'/state/77/dashboards/quota{i}.json','PUT',raw,gateway_headers)[0]
        with ThreadPoolExecutor(max_workers=8) as pool: statuses=list(pool.map(put,range(10)))
        assert statuses.count(204)==8 and statuses.count(413)==2, statuses
        status,body=request(gateways[1],'/state/77',headers=gateway_headers)
        assert status==200 and len(body)==4194499
        assert set(json.loads(body)['files'].values())=={raw.decode()}
        record('atomic concurrent exact 2 MiB quota; complete 4194499-byte gateway state list')
        count=sql("SELECT count(*) FROM pg_stat_activity WHERE usename='openbq_settings_runtime'")
        assert int(count)<=4
        record('runtime connection count bounded: '+count)
        # Accepted JSON number spelling is validated without Python's integer digit cap.
        assert request(apis[0],private+'88/settings.json','PUT',b'1'*5000,bearer)[0]==204
        assert request(apis[0],private+'88/settings.json','PUT',b'NaN',bearer)[0]==400
        for i in range(199):
            assert request(gateways[i%2],f'/state/78/dashboards/f{i}.json','PUT',b'{}',gateway_headers)[0]==204
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(lambda i:request(gateways[i%2],f'/state/78/dashboards/last{i}.json','PUT',b'{}',gateway_headers)[0],range(2)))
        assert sorted(statuses)==[204,413]
        assert len(json.loads(request(gateways[1],'/state/78',headers=gateway_headers)[1])['files'])==200
        record('atomic 200-file race and JS numeric/NaN validation')
        def app_write(i):
            return request(apis[i],'/pro/user-apps/'+str(uuid.UUID(int=i+200)), 'POST',{'padding':'x'*2700000},basic)[0]
        with ThreadPoolExecutor(max_workers=2) as pool: assert list(pool.map(app_write,range(2)))==[200,200]
        assert len(request(apis[1],'/pro/user-apps/sync',headers=basic)[1])>5000000
        assert request(apis[0],'/pro/user-apps/'+str(uuid.UUID(int=200)),'DELETE',headers=basic)[0]==200
        assert request(apis[1],'/pro/user-apps/'+str(uuid.UUID(int=200)),'DELETE',headers=basic)[0]==404
        record('disjoint app transactions; accumulated document above one request; delete404')
        browser=docker('run','--rm','--network',prefix,'-v',str(H.parent/'bdobb-v11')+':/client:ro',
            '-v',str(H/'funnel-gateway')+':/gateway:ro',
            '-v',str(H/'v11/settings/fixtures')+':/runner:ro','-v',str(directory)+':/fixture:ro',
            'node:22','node','/runner/browser.mjs',prefix+'-gateway-a')
        assert b'PASS real browser complete state tabs' in browser.stdout
        assert b'PASS real browser complete state replacement' in browser.stdout
        record('actual C authenticated save/bootstrap through actual PG gateway; valid tabs and UTF8 replacement')
        for statement in ('CREATE TABLE settings.denied(x int)', 'INSERT INTO settings_admin.checkpoints VALUES(\'x\',\'{}\',\'{}\')', 'CREATE SCHEMA denied'):
            result=docker('exec','-i',pg,'psql','-X','-v','ON_ERROR_STOP=1','-U','postgres','-d','openbq_settings',
              input=('SET ROLE openbq_settings_runtime; '+statement).encode(),check=False)
            assert result.returncode!=0
        sql('CREATE ROLE fixture_other LOGIN; CREATE DATABASE fixture_other OWNER fixture_other;',db='postgres')
        sql('REVOKE ALL ON DATABASE fixture_other FROM PUBLIC;',db='postgres')
        assert sql("SELECT has_database_privilege('fixture_other','openbq_settings','CONNECT')")=='f'
        assert sql("SELECT has_database_privilege('openbq_settings_runtime','fixture_other','CONNECT')")=='f'
        record('runtime DDL/checkpoint denial and separate app database ACLs')
        # The same startup verifier executes with real libpq/TLS and actual roles.
        for variant in ('wrong-ca','wrong-host','wrong-role','wrong-db'):
            content=runtime.read_text()
            extra=[]
            if variant=='wrong-ca':
                content=content.replace('/tls/ca.crt','/tls/wrong.crt')
                extra=['-v',str(tls/'wrong.crt')+':/tls/wrong.crt:ro']
            if variant=='wrong-host':
                content=content.replace('host='+prefix+'-pg ','host=wrong-host ')
                ip=docker('inspect','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',pg).stdout.decode().strip()
                extra=['--add-host','wrong-host:'+ip]
            if variant=='wrong-role':content=content.replace('user=openbq_settings_runtime','user=openbq_settings_migrator')
            if variant=='wrong-db':content=content.replace('dbname=openbq_settings ','dbname=postgres ')
            envfile=save(variant+'.env',content)
            result=docker('run','--rm','--network',prefix,'--env-file',envfile,'-v',cert_mount,*extra,
              '--entrypoint','python',IMAGE,'-c',
              "from openbq_settings_pg.config import Config; from openbq_settings_pg.store import Store; s=Store(Config.read()); s.verify()",check=False)
            assert result.returncode!=0
            assert password.encode() not in result.stdout+result.stderr and token.encode() not in result.stdout+result.stderr
        record('real TLS wrong CA/hostname and wrong runtime role/database refusals; secret-safe failures')
        # A real open pool is process-owned; checkout is bounded even with both
        # connections held, and remains usable after the timeout.
        pool_probe=docker('run','--rm','--network',prefix,'--env-file',runtime,'-v',cert_mount,'--entrypoint','python',IMAGE,'-c',
          "import os,time; from openbq_settings_pg.config import Config,SettingsUnavailable; from openbq_settings_pg.store import Store; s=Store(Config.read()); s.verify(); pid=os.fork();\nif pid==0:\n try:\n  with s.connection(): pass\n except SettingsUnavailable: os._exit(0)\n os._exit(1)\nassert os.waitpid(pid,0)[1]==0; a=s.pool.getconn(); b=s.pool.getconn(); start=time.monotonic()\ntry:\n with s.connection(): raise AssertionError('unbounded connection')\nexcept SettingsUnavailable: pass\nassert 9 <= time.monotonic()-start < 13; s.pool.putconn(a); s.pool.putconn(b); s.verify(); s.close(); print('PASS fork refusal and bounded pool recovery')")
        assert b'PASS fork refusal' in pool_probe.stdout
        record('actual inherited pool refused after fork; two held connections bound checkout and recover')
        # A writer dies after its update and checkpoint-ready transaction, before commit.
        writer=run('killed-writer','--network',prefix,'--env-file',runtime,'-v',cert_mount,'--entrypoint','python',IMAGE,'-c',
          "import time; from openbq_settings_pg.config import Config; from openbq_settings_pg.store import Store; s=Store(Config.read()); t=s.transaction('github','77'); d=t.__enter__(); d.write('settings.json',b'{}'); print('transaction-open',flush=True); time.sleep(60)")
        for _ in range(30):
            if b'transaction-open' in docker('logs',writer).stdout:break
            time.sleep(0.2)
        docker('kill',writer)
        assert 'settings.json' not in json.loads(request(gateways[0],'/state/77',headers=gateway_headers)[1])['files']
        assert request(gateways[0],'/state/77/settings.json','PUT',b'{}',gateway_headers)[0]==413
        record('killed precommit writer rolls back and retry observes committed quota')
        assert docker('exec',prefix+'-api-a','python','-m','openbq_settings_pg.health',check=False).returncode==0
        docker('stop',pg)
        assert request(gateways[0],'/state/77',headers=gateway_headers)[0]==502
        assert request(apis[0],'/pro/user',headers=basic)[0]==503
        assert docker('exec',prefix+'-api-a','python','-m','openbq_settings_pg.health',check=False).returncode==1
        docker('start',pg)
        for _ in range(30):
            if docker('exec',pg,'pg_isready','-h','127.0.0.1','-U','postgres',check=False).returncode==0:break
            time.sleep(1)
        record('selected database outage gives gateway502/key503 without empty fallback')
        # Kill the actual API process while its first write waits on a parent lock.
        blocker=run('blocked-parent','--network',prefix,'--env-file',runtime,'-v',cert_mount,'--entrypoint','python',IMAGE,'-c',
          "import time; from openbq_settings_pg.config import Config; from openbq_settings_pg.store import Store; s=Store(Config.read()); t=s.transaction('github','80'); d=t.__enter__(); d.conn.execute('SET LOCAL idle_in_transaction_session_timeout=0'); print('parent-locked',flush=True); time.sleep(60)")
        for _ in range(30):
            if b'parent-locked' in docker('logs',blocker).stdout:break
            time.sleep(0.2)
        def blocked_request():
            try:return request(apis[0],private+'80/settings.json','PUT',b'{}',bearer)[0]
            except Exception:return 0
        start=time.monotonic()
        with ThreadPoolExecutor(max_workers=12) as pool:
            pending=[pool.submit(blocked_request) for _ in range(12)]
            time.sleep(0.5)
            # Read-only traffic on the other process remains responsive while
            # this process has two blocked transactions and a bounded queue.
            assert request(apis[1],private+'00042',headers=bearer,timeout=2)[0]==200
            answers=[future.result() for future in pending]
        assert answers==[503]*12 and time.monotonic()-start<17
        record('actual row-lock timeout and bounded worker queue refuse overload without partial writes')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(blocked_request);time.sleep(0.5)
            docker('kill',prefix+'-api-a');docker('kill',blocker);future.result()
        assert json.loads(request(apis[1],private+'80',headers=bearer)[1])=={'files':{}}
        assert request(apis[1],private+'81/settings.json','PUT',b'{}',bearer)[0]==204
        docker('kill',prefix+'-api-b')
        record('actual API killed before commit rolls back; second API killed after accepted commit')
        for name in resources:
            if '-api-' in name or '-gateway-' in name: docker('restart',name)
        apis=['http://127.0.0.1:'+str(port(prefix+'-api-'+suffix,6900)) for suffix in ('a','b')]
        gateways=['http://127.0.0.1:'+str(port(prefix+'-gateway-'+suffix,8080)) for suffix in ('a','b')]
        for api in apis: wait(api,basic)
        docker('restart',pg)
        for _ in range(30):
            try:
                if request(gateways[0],'/state/77',headers=gateway_headers)[0]==200: break
            except Exception: pass
            time.sleep(1)
        assert len(json.loads(request(gateways[1],'/state/77',headers=gateway_headers)[1])['files'])==8
        assert request(apis[0],private+'80/settings.json','PUT',b'{}',bearer)[0]==204
        assert json.loads(request(apis[1],private+'81',headers=bearer)[1])=={'files':{'settings.json':'{}'}}
        record('both API/gateway and PostgreSQL restart persistence; killed-write retry and committed data survive')
        save('destination-map.json',json.dumps({hashlib.sha256(('fixture:'+password).encode()).hexdigest():principal}))
        migrate('export-legacy','--mapping','/fixture/destination-map.json','--destination','/fixture/export','--quiesced-copy')
        assert hashlib.sha256(b''.join(p.read_bytes() for p in sorted(source.rglob('*')) if p.is_file())).hexdigest()==before
        record('new reverse export after API writes; original source bytes unchanged')
        # Restore the new export through the actual installed legacy middleware and
        # a distinct real gateway process using its existing file backend.
        rotated_password='fixture-rotated-password'
        rotated_env=save('rotated.env',runtime.read_text().replace('OPENBB_API_PASSWORD='+password,'OPENBB_API_PASSWORD='+rotated_password))
        rotated=run('rotated-api','--network',prefix,'--env-file',rotated_env,'-v',cert_mount,'-p','127.0.0.1::6900',IMAGE)
        rotated_base='http://127.0.0.1:'+str(port(rotated,6900))
        rotated_basic={**basic,'Authorization':'Basic '+base64.b64encode(('fixture:'+rotated_password).encode()).decode()}
        wait(rotated_base,rotated_basic)
        assert request(rotated_base,'/pro/user',headers=basic)[0]==401
        assert request(rotated_base,'/pro/user',headers=rotated_basic)==request(apis[0],'/pro/user',headers=basic)
        docker('rm','-f',rotated)
        record('actual Basic password rotation retains stable principal and rejects old credential')
        legacy_env=save('legacy.env','OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=fixture\nOPENBB_API_PASSWORD='+password+'\nOPENBQ_SETTINGS_DIR=/legacy/keys\n')
        legacy=run('legacy-api','--network',prefix,'--env-file',legacy_env,'-v',str(directory/'export')+':/legacy:ro','-p','127.0.0.1::6900',IMAGE)
        legacy_base='http://127.0.0.1:'+str(port(legacy,6900)); wait(legacy_base,basic)
        for path in ('/pro/user','/pro/dash/sync/owned','/pro/user-apps/sync','/pro/dash/sync/system/docks'):
            assert request(legacy_base,path,headers=basic)==request(apis[0],path,headers=basic), path
        legacy_config=directory/'legacy-config'; legacy_config.mkdir()
        settings=json.loads((directory/'gateway.json').read_text()); settings['settings'].pop('stateStorage'); settings['settings']['stateDir']='/legacy/state'
        (legacy_config/'gateway.json').write_text(json.dumps(settings))
        legacy_gateway=run('legacy-gateway','--network',prefix,'-v',str(H/'funnel-gateway')+':/gateway:ro',
          '-v',str(H/'v11/settings/fixtures')+':/runner:ro','-v',str(legacy_config)+':/fixture:ro',
          '-v',str(directory/'export')+':/legacy','-p','127.0.0.1::8080','node:22','node','/runner/gateway.mjs')
        legacy_gateway_base='http://127.0.0.1:'+str(port(legacy_gateway,8080))
        wait_gateway(legacy_gateway_base,gateway_headers)
        for identity in ('00042','77','78','88','99'):
            left=request(legacy_gateway_base,'/state/'+identity,headers=gateway_headers);right=request(gateways[0],'/state/'+identity,headers=gateway_headers)
            assert left[0]==right[0]==200 and json.loads(left[1])==json.loads(right[1])
        browser=docker('run','--rm','--network',prefix,'-v',str(H.parent/'bdobb-v11')+':/client:ro',
          '-v',str(H/'funnel-gateway')+':/gateway:ro',
          '-v',str(H/'v11/settings/fixtures')+':/runner:ro','-v',str(directory)+':/fixture:ro','node:22','node','/runner/browser.mjs',legacy_gateway)
        assert b'PASS real browser complete state replacement' in browser.stdout
        record('actual legacy API and Node22 file gateway restored; real C bootstrap after restored writes')
        backup=docker('exec',pg,'pg_dump','-U','postgres','-Fc','openbq_settings').stdout
        (directory/'settings.dump').write_bytes(backup)
        sql('CREATE DATABASE openbq_settings_restored OWNER openbq_settings_owner;',db='postgres')
        sql('REVOKE ALL ON DATABASE openbq_settings_restored FROM PUBLIC; GRANT CONNECT ON DATABASE openbq_settings_restored TO openbq_settings_runtime,openbq_settings_migrator;',db='postgres')
        docker('exec','-i',pg,'pg_restore','-U','postgres','-d','openbq_settings_restored','--exit-on-error',input=backup)
        signature="SELECT md5(string_agg(namespace||principal_id||document_key||encode(body_bytes,'hex')||revision::text||updated_at::text,',' ORDER BY namespace,principal_id,document_key)) FROM settings.documents"
        assert sql(signature)==sql(signature,db='openbq_settings_restored')
        assert sql('SELECT count(*) FROM settings_admin.checkpoints')==sql('SELECT count(*) FROM settings_admin.checkpoints',db='openbq_settings_restored')
        restore_env=save('restored.env',runtime.read_text().replace('dbname=openbq_settings ','dbname=openbq_settings_restored '))
        for i,suffix in enumerate(('a','b')):
            old_api=prefix+'-api-'+suffix; old_gateway=prefix+'-gateway-'+suffix
            docker('rm','-f',old_gateway,old_api)
            api=run('api-'+suffix,'--network',prefix,'--env-file',restore_env,'-v',cert_mount,'-p','127.0.0.1::6900',IMAGE)
            apis[i]='http://127.0.0.1:'+str(port(api,6900));wait(apis[i],basic)
            ip=docker('inspect','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',api).stdout.decode().strip()
            gw=run('gateway-'+suffix,'--network',prefix,'--add-host','openbq-v11:'+ip,'-p','127.0.0.1::8080',
              '-v',str(H/'funnel-gateway')+':/gateway:ro','-v',str(H/'v11/settings/fixtures')+':/runner:ro','-v',str(directory)+':/fixture:ro','node:22','node','/runner/gateway.mjs')
            gateways[i]='http://127.0.0.1:'+str(port(gw,8080))
            wait_gateway(gateways[i],gateway_headers)
            assert len(json.loads(request(gateways[i],'/state/77',headers=gateway_headers)[1])['files'])==8
            assert json.loads(request(apis[i],'/pro/user',headers=basic)[1])['pro_display_settings']['last']==1
        record('custom pg_dump fresh database pg_restore exact rows/checkpoints; both installed pairs reconnected')
        # A post-import runtime write makes the original target checkpoint divergent.
        migrate('verify','--source','/fixture/source','--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
        record('divergent target checkpoint refused')
        logs=b''.join(docker('logs',name,check=False).stdout+docker('logs',name,check=False).stderr for name in resources if '-api-' in name or '-gateway-' in name)
        assert password.encode() not in logs and token.encode() not in logs
        record('synthetic secret sentinels absent from API/gateway logs')
    finally:
        # Keep task-only diagnostics before cleanup; never print potentially
        # sensitive application logs or Docker configuration into public output.
        diagnostics=directory/'container-diagnostics';diagnostics.mkdir(exist_ok=True,mode=0o700)
        for name in set(resources):
            state=docker('inspect','--format','{{json .State}}',name,check=False)
            if state.returncode==0:
                (diagnostics/(name+'.state.json')).write_bytes(state.stdout)
                logs=docker('logs',name,check=False)
                (diagnostics/(name+'.log')).write_bytes(logs.stdout+logs.stderr)
        for name in reversed(resources): docker('rm','-f',name,check=False)
        docker('network','rm',prefix,check=False)


if __name__=='__main__': main()
