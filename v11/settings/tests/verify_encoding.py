#!/usr/bin/env python3
"""Real installed key encoding -> PostgreSQL -> new export -> legacy API proof."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import urllib.error
import uuid

H=Path(__file__).resolve().parents[3]
D=os.environ.get('DOCKER','/Applications/Docker.app/Contents/Resources/bin/docker')
IMAGE=os.environ.get('SETTINGS_IMAGE','openbq-task51:fix1')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts',type=Path,required=True)
    directory=parser.parse_args().artifacts.resolve();directory.mkdir(mode=0o700)
    prefix='openbq-task51-encoding-'+uuid.uuid4().hex[:8];resources=[];network=False;checks=[]
    def docker(*args,input=None,check=True):
        result=subprocess.run([D,*map(str,args)],input=input,capture_output=True)
        if check and result.returncode:
            (directory/'last-error.log').write_bytes(result.stdout+result.stderr)
            raise AssertionError('task Docker command failed: '+args[0])
        return result
    def record(message):
        checks.append(message);print('PASS '+message,flush=True)
        (directory/'checks.json').write_text(json.dumps(checks,indent=2))
    def save(name,text):
        path=directory/name;path.write_text(text);path.chmod(0o600);return path
    def run(suffix,*args):
        name=prefix+'-'+suffix;docker('run','-d','--name',name,*args);resources.append(name);return name
    def sql(text):
        return docker('exec','-i',prefix+'-pg','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','openbq_settings',input=text.encode()).stdout
    def url(name):return 'http://127.0.0.1:'+docker('port',name,'6900').stdout.decode().strip().rsplit(':',1)[1]
    def request(base,path,headers,method='GET',body=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers,method=method,data=body),timeout=5) as response:
                return response.status,json.loads(response.read() or b'null')
        except urllib.error.HTTPError as error:return error.code,None
    def ready(base,headers):
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            try:
                if request(base,'/pro/user',headers)[0]==200:return
            except Exception:pass
            time.sleep(.2)
        raise AssertionError('installed API startup failed')
    password='encoding-fixture'+"@:/%?#'\\-secret";token='fixture_encoding_gateway_1234567890';principal='aaaaaaaa-1111-4111-8111-111111111111'
    basic={'Authorization':'Basic '+base64.b64encode(('fixture:'+password).encode()).decode(),'Content-Type':'application/json'}
    bearer={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    stem=hashlib.sha256(('fixture:'+password).encode()).hexdigest()
    escape=lambda value:value.replace('\\','\\\\').replace("'","\\'")
    def dsn(role,ca):return f"host={prefix}-pg dbname=openbq_settings user={role} password='{escape(password)}' connect_timeout=3 sslmode=verify-full sslrootcert={ca}"
    admin=save('admin.env','POSTGRES_PASSWORD='+password+'\nOPENBQ_SETTINGS_RUNTIME_PASSWORD='+password+'\nOPENBQ_SETTINGS_MIGRATION_PASSWORD='+password+'\n')
    runtime=save('runtime.env','\n'.join(['OPENBQ_SETTINGS_BACKEND=postgresql','OPENBQ_SETTINGS_GATEWAY_STATE=1','OPENBQ_SETTINGS_PRINCIPAL_ID='+principal,'OPENBQ_SETTINGS_DSN='+dsn('openbq_settings_runtime','/tls/ca.crt'),'GATEWAY_TOKEN='+token,'OPENBB_API_AUTH=true','OPENBB_API_USERNAME=fixture','OPENBB_API_PASSWORD='+password])+'\n')
    migration=save('migration.env','OPENBQ_SETTINGS_MIGRATION_DSN='+dsn('openbq_settings_migrator','/fixture/tls/ca.crt')+'\n')
    legacy_env=save('legacy.env','OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=fixture\nOPENBB_API_PASSWORD='+password+'\nOPENBQ_SETTINGS_DIR=/legacy/current/keys\n')
    save('mapping.json',json.dumps({stem:principal}));(directory/'exports').mkdir(mode=0o700)
    tls=directory/'tls';tls.mkdir(mode=0o700)
    def openssl(*args):subprocess.run(['/usr/bin/openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    openssl('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Task51 encoding fixture CA','-keyout',tls/'ca.key','-out',tls/'ca.crt')
    openssl('req','-newkey','rsa:2048','-nodes','-subj','/CN='+prefix+'-pg','-keyout',tls/'server.key','-out',tls/'server.csr')
    (tls/'extensions').write_text('subjectAltName=DNS:'+prefix+'-pg\n')
    openssl('x509','-req','-in',tls/'server.csr','-CA',tls/'ca.crt','-CAkey',tls/'ca.key','-CAcreateserial','-days','1','-extfile',tls/'extensions','-out',tls/'server.crt')
    def migrate(*args,expect=0):
        result=docker('run','--rm','--network',prefix,'--env-file',migration,'-v',str(directory)+':/fixture','--entrypoint','python',IMAGE,'-m','openbq_settings_pg.migrate_json',*args,check=False)
        assert result.returncode==expect,(args[0],result.returncode,expect)
        assert password.encode() not in result.stdout+result.stderr and token.encode() not in result.stdout+result.stderr
    try:
        docker('network','create',prefix);network=True
        pg=run('pg','--network',prefix,'--env-file',admin,'-v',str(tls)+':/certs:ro','--entrypoint','sh','postgres:16.11-alpine','-c','cp /certs/server.key /tmp/server.key; cp /certs/server.crt /tmp/server.crt; chown postgres:postgres /tmp/server.key /tmp/server.crt; chmod 600 /tmp/server.key; exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key')
        for _ in range(60):
            if docker('exec',pg,'pg_isready','-h','127.0.0.1','-U','postgres',check=False).returncode==0:break
            time.sleep(.2)
        docker('exec','-i',pg,'psql','-X','-v','ON_ERROR_STOP=1','-v','settings_database=openbq_settings','-U','postgres',input=(H/'v11/settings/provision.sql').read_bytes())
        migrate('migrate')
        refused=docker('run','--rm','--env-file',runtime,'-e','OPENBQ_SETTINGS_PRINCIPAL_ID=',IMAGE,check=False)
        assert refused.returncode==1 and b'Settings unavailable' in refused.stderr
        api=run('api','--network',prefix,'--env-file',runtime,'-v',str(tls/'ca.crt')+':/tls/ca.crt:ro','-p','127.0.0.1::6900',IMAGE)
        base=url(api);ready(base,basic)
        assert docker('exec',api,'python','-m','openbq_settings_pg.health',check=False).returncode==0
        record('fresh installed selected PG startup and readiness; invalid principal refused')
        browser=b' {"duplicate":1,"duplicate":2,"n":1e2,"s":"\xff"} '
        assert request(base,'/_openbq/settings/v1/state/900/settings.json',bearer,'PUT',browser)[0]==204
        browser_hex=sql("SELECT encode(body_bytes,'hex') FROM settings.documents WHERE namespace='github'").strip().decode()
        assert bytes.fromhex(browser_hex)==browser
        sql("INSERT INTO settings_admin.checkpoints(run_id,manifest,target_manifest) VALUES('encoding-fixture','{}','{}')")
        checkpoint=sql('COPY settings_admin.checkpoints TO STDOUT');legacy_base=None
        for encoding in ('utf-8','utf-8-sig','utf-16','utf-32'):
            text='{"encoding":"'+encoding+'","extension":{"unknown":["café 雪",null,true,17,1e2,-0.0]},"theme":"dark"}'
            raw=text.encode(encoding);expected=json.loads(text);canonical=json.dumps(expected).encode('utf-8')
            if encoding!='utf-8':
                # Explicit test-only retained-row injection; no automatic conversion.
                sql("UPDATE settings.documents SET body_bytes=decode('"+raw.hex()+"','hex') WHERE namespace='key' AND document_key='settings'")
                assert request(base,'/pro/user',basic)[1]['pro_display_settings']==expected
                source=directory/('source-'+encoding);(source/'keys').mkdir(parents=True)
                path=source/'keys'/(stem+'.json');path.write_bytes(raw)
                migrate('inventory','--source','/fixture/'+source.name,'--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
                destination='refused-'+encoding
                migrate('export-legacy','--destination','/fixture/exports/'+destination,'--mapping','/fixture/mapping.json','--quiesced-copy',expect=1)
                assert not (directory/'exports'/destination).exists() and path.read_bytes()==raw
                retained=sql("SELECT encode(body_bytes,'hex') FROM settings.documents WHERE namespace='key' AND document_key='settings'").strip().decode()
                assert bytes.fromhex(retained)==raw and sql('COPY settings_admin.checkpoints TO STDOUT')==checkpoint
                record(encoding+' inventory/export refuse before publication; source/retained bytes/checkpoint unchanged')
            status,answer=request(base,'/pro/display-settings',basic,'POST',raw)
            assert status==200 and answer['pro_display_settings']==expected
            assert request(base,'/pro/user',basic)[1]['pro_display_settings']==expected
            stored=sql("SELECT encode(body_bytes,'hex') FROM settings.documents WHERE namespace='key' AND document_key='settings'").strip().decode()
            assert bytes.fromhex(stored)==canonical
            generation='generation-'+encoding
            migrate('export-legacy','--destination','/fixture/exports/'+generation,'--mapping','/fixture/mapping.json','--quiesced-copy')
            exported=directory/'exports'/generation
            assert (exported/'keys'/(stem+'.json')).read_bytes()==canonical
            assert (exported/'state/900/settings.json').read_bytes()==browser
            current=directory/'exports/current';temporary=directory/'exports/.next';temporary.symlink_to(generation);temporary.replace(current)
            if legacy_base is None:
                legacy=run('legacy-api','--network',prefix,'--env-file',legacy_env,'-v',str(directory/'exports')+':/legacy:ro','-p','127.0.0.1::6900',IMAGE)
                legacy_base=url(legacy);ready(legacy_base,basic)
            status,answer=request(legacy_base,'/pro/user',basic);restored=answer['pro_display_settings']
            assert status==200 and restored==expected
            assert type(restored['extension']['unknown'][3]) is int and type(restored['extension']['unknown'][4]) is float
            assert sql("SELECT encode(body_bytes,'hex') FROM settings.documents WHERE namespace='github'").strip().decode()==browser_hex
            assert sql('COPY settings_admin.checkpoints TO STDOUT')==checkpoint
            record(encoding+' POST/PG GET/new export/actual legacy GET agree; canonical key UTF8 and browser byte hash unchanged')
        (directory/'evidence.json').write_text(json.dumps({'image':docker('image','inspect','--format','{{.Id}}',IMAGE).stdout.decode().strip(),'browser_sha256':hashlib.sha256(browser).hexdigest(),'checkpoint_sha256':hashlib.sha256(checkpoint).hexdigest(),'checks':checks},indent=2))
    finally:
        for name in resources:
            logs=docker('logs',name,check=False);(directory/(name+'.log')).write_bytes(logs.stdout+logs.stderr)
            assert password.encode() not in logs.stdout+logs.stderr and token.encode() not in logs.stdout+logs.stderr
        for name in reversed(resources):docker('rm','-f',name,check=False)
        if network:docker('network','rm',prefix,check=False)


if __name__=='__main__':main()
