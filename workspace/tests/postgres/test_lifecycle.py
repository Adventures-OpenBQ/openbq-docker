# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
"""Actual image explicit lifecycle and immutable imported-startup gates."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import unittest

from fixtures import create_database, docker, image_run


class ProvisionTests(unittest.TestCase):
    def test_database_identifier_refuses_before_any_mutation(self):
        from fixtures import prepare,prepare_roles
        root=prepare()
        self.addCleanup(lambda:docker('network','rm',root.name,check=False))
        self.addCleanup(lambda:docker('rm','-f',root.name+'-pg',check=False))
        def catalog():
            return docker('exec',root.name+'-pg','psql','-U','postgres','-Atc',
                "SELECT rolname FROM pg_roles ORDER BY rolname;SELECT datname FROM pg_database ORDER BY datname").stdout
        import time
        for _ in range(30):
            try:before=catalog();break
            except RuntimeError:time.sleep(.5)
        else:self.fail('disposable provisioning server readiness failed')
        for value in ('Uppercase','a'*64,'db$name','db\nname','db\\name',"db'name",'host=invalid dbname=postgres','数据库','', 'valid\n'):
            result=prepare_roles(root,value)
            self.assertNotEqual(result.returncode,0,'invalid database identifier was accepted')
            self.assertIn('Invalid Workspace database identifier',result.stdout+result.stderr)
            if value:self.assertNotIn(value,result.stdout+result.stderr,'invalid input was echoed')
            self.assertEqual(catalog(),before,'invalid input caused catalog mutation')
        self.assertEqual(prepare_roles(root,'openbq_workspace').returncode,0)
        self.assertEqual(docker('exec',root.name+'-pg','psql','-U','postgres','-d','openbq_workspace','-Atc',
            "SELECT count(*) FROM workspace_admin.readiness").stdout.strip(),'0')


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(os.environ['WORKSPACE_FIXTURE']).resolve()
        self.image=os.environ['WORKSPACE_TEST_IMAGE']
        self.db='openbq_workspace_boot_'+secrets.token_hex(4)
        self.assertEqual(create_database(self.root,self.db).returncode,0)
        values=dict(line.split('=',1) for line in (self.root/'maintenance.env').read_text().splitlines())
        values.update(DB_NAME=self.db,WORKSPACE_PERMISSION_MAP_FILE='/data/permission-map.json',
                      OPENBB_ADMIN_EMAIL='generated@example.com',OPENBB_ADMIN_PASSWORD=secrets.token_urlsafe(24)+'Aa1!')
        values['WORKSPACE_TARGET_DSN']=values['WORKSPACE_TARGET_DSN'].rsplit('/',1)[0]+'/'+self.db
        for key in ('OPENBB_AES_KEY','OPENBB_AUTH_TOKEN','JWT_SECRET','LOCAL_STORAGE_SECRET_KEY'):values.pop(key,None)
        self.env=self.root/(self.db+'.env');self.env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));self.env.chmod(0o600)
        self.data=self.root/(self.db+'-data');self.data.mkdir(mode=0o700)
        self.assertEqual(image_run(self.root,'-m','scripts.workspace_pg','migrate',env_file=self.env).returncode,0)

    def bootstrap(self):
        import threading
        samples=[];errors=[];finished=threading.Event()
        def sample():
            while not finished.is_set():
                try:
                    count=docker('exec',self.root.name+'-pg','psql','-U','postgres','-Atc',
                        "SELECT count(*) FROM pg_stat_activity WHERE datname='"+self.db+"' AND usename='openbq_workspace_migrator'").stdout.strip()
                    samples.append(int(count))
                except Exception:errors.append(True);return
                finished.wait(.2)
        monitor=threading.Thread(target=sample);monitor.start()
        try:
            return docker('run','--rm','--platform','linux/amd64','--network',self.root.name,
                          '--env-file',str(self.env),'-e','WORKSPACE_DB_ACTION=bootstrap',
                          '-v',str(self.data)+':/data',self.image,check=False,timeout=180)
        finally:
            finished.set();monitor.join(timeout=10)
            self.assertFalse(monitor.is_alive());self.assertFalse(errors);self.assertTrue(samples)
            self.assertLessEqual(max(samples),7,'bootstrap parent plus bounded child pools exceeded budget')
            print('Observed serialized bootstrap connection peak:',max(samples),flush=True)

    def test_explicit_fresh_bootstrap_seals_once_and_refuses_existing_data(self):
        result=self.bootstrap()
        (self.root/(self.db+'-bootstrap.log')).write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode,0,'fresh explicit bootstrap failed; diagnostics retained privately')
        self.assertTrue((self.data/'permission-map.json').is_file())
        before=(self.data/'secrets.env').read_bytes()
        self.assertEqual((self.data/'secrets.env').stat().st_mode & 0o777,0o600)
        refused=self.bootstrap()
        self.assertEqual(refused.returncode,1)
        self.assertTrue((self.data/'secrets.env').read_bytes()==before,'identity file bytes changed')
        self.assertNotIn(before.decode(),result.stdout+result.stderr+refused.stdout+refused.stderr)
        from fixtures import api_base,api_request
        import time
        for directory in ('redis','storage','state'):
            self.assertTrue((self.data/directory).is_dir(),'fresh bootstrap must prepare pinned runtime companions')
        values=dict(line.split('=',1) for line in (self.root/'runtime.env').read_text().splitlines())
        for key in ('OPENBB_AES_KEY','OPENBB_AUTH_TOKEN','JWT_SECRET','LOCAL_STORAGE_SECRET_KEY'):values.pop(key,None)
        values.update(DB_NAME=self.db,WORKSPACE_PERMISSION_MAP_FILE='/data/permission-map.json')
        values.pop('WORKSPACE_DB_ACTION',None)  # implicit PostgreSQL serve
        runtime=self.root/(self.db+'-runtime.env');runtime.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));runtime.chmod(0o600)
        name=self.db+'-serve'
        docker('run','-d','--name',name,'--label','openbq.task=5.2','--platform','linux/amd64',
            '--network',self.root.name,'--env-file',str(runtime),'-p','127.0.0.1::3000','-v',str(self.data)+':/data',self.image)
        try:
            base=api_base(self.root,name)
            identity=dict(line.split('=',1) for line in before.decode().splitlines())
            for _ in range(90):
                try:
                    if api_request(base,'/health',identity['OPENBB_AUTH_TOKEN'])[0]==200:break
                except Exception:pass
                time.sleep(1)
            else:self.fail('fresh bootstrap serve did not become ready')
            self.assertEqual(docker('exec',name,'redis-cli','ping').stdout.strip(),'PONG')
            bootstrap_values=dict(line.split('=',1) for line in self.env.read_text().splitlines())
            status,_=api_request(base,'/pro/login',identity['OPENBB_AUTH_TOKEN'],body={
                'email':bootstrap_values['OPENBB_ADMIN_EMAIL'],'password':bootstrap_values['OPENBB_ADMIN_PASSWORD']})
            self.assertEqual(status,200,'fresh generated identity must support actual login')
            self.assertTrue((self.data/'secrets.env').read_bytes()==before,'identity file bytes changed')
        finally:docker('stop','-t','40',name,check=False)

    def test_changed_seeds_refuse_before_identity_generation(self):
        docker('exec',self.root.name+'-pg','psql','-U','postgres','-d',self.db,
               '-v','ON_ERROR_STOP=1','-c','UPDATE tier SET has_trial=NOT has_trial')
        result=self.bootstrap()
        self.assertEqual(result.returncode,1)
        self.assertFalse((self.data/'secrets.env').exists())
        self.assertFalse((self.data/'permission-map.json').exists())

    def test_failed_bootstrap_never_seals_or_reseeds_partial_state(self):
        values=dict(line.split('=',1) for line in self.env.read_text().splitlines())
        values['OPENBB_ADMIN_EMAIL']='invalid-generated-address'
        self.env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
        result=self.bootstrap()
        self.assertEqual(result.returncode,1)
        self.assertNotIn(values['OPENBB_ADMIN_PASSWORD'],result.stdout+result.stderr)
        self.assertFalse((self.data/'permission-map.json').exists())
        result=docker('exec',self.root.name+'-pg','psql','-U','postgres','-d',self.db,
                     '-Atc','SELECT count(*) FROM workspace_admin.readiness')
        self.assertEqual(result.stdout.strip(),'0')
        before=(self.data/'secrets.env').read_bytes()
        self.assertEqual(self.bootstrap().returncode,1)
        self.assertTrue((self.data/'secrets.env').read_bytes()==before,'identity file bytes changed')


class MigrationTests(unittest.TestCase):
    def test_competing_keyless_migrations_recheck_after_killed_lock_holder(self):
        import subprocess,time
        from fixtures import DOCKER
        root=Path(os.environ['WORKSPACE_FIXTURE']).resolve();image=os.environ['WORKSPACE_TEST_IMAGE']
        database='openbq_workspace_lock_'+secrets.token_hex(4)
        self.assertEqual(create_database(root,database).returncode,0)
        values=dict(line.split('=',1) for line in (root/'maintenance.env').read_text().splitlines())
        values.update(DB_NAME=database,WORKSPACE_DB_ACTION='migrate',REDIS_HOST='unavailable-fixture-redis')
        for key in ('OPENBB_AES_KEY','OPENBB_AUTH_TOKEN','JWT_SECRET','LOCAL_STORAGE_SECRET_KEY'):values.pop(key,None)
        env=root/(database+'.env');env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));env.chmod(0o600)
        name=database+'_holder'
        sql="SET application_name='"+name+"';SELECT pg_advisory_lock(1791763200,5);SELECT pg_sleep(120)"
        output=open(root/(database+'-holder.log'),'w')
        holder=subprocess.Popen([DOCKER,'exec',root.name+'-pg','psql','-U','postgres','-d',database,'-c',sql],stdout=output,stderr=output)
        jobs=[]
        try:
            for _ in range(50):
                active=docker('exec',root.name+'-pg','psql','-U','postgres','-Atc',
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name='"+name+"' AND wait_event='PgSleep'")
                if active.stdout.strip()=='1':break
                time.sleep(.1)
            else:self.fail('fixture lock holder did not acquire its lock')
            for index in (1,2):
                job=database+'-'+str(index);jobs.append(job)
                docker('run','-d','--name',job,'--platform','linux/amd64','--network',root.name,
                       '--env-file',str(env),image)
            # Ensure both processes exist while the same target lock is held.
            self.assertTrue(all(json.loads(docker('inspect',job).stdout)[0]['State']['Running'] for job in jobs))
            for _ in range(200):
                connected=docker('exec',root.name+'-pg','psql','-U','postgres','-Atc',
                    "SELECT count(*) FROM pg_stat_activity WHERE datname='"+database+"' AND usename='openbq_workspace_migrator'")
                if connected.stdout.strip()=='2':break
                time.sleep(.1)
            else:self.fail('both migrators must reach the held target lock before release')
            absent=docker('exec',root.name+'-pg','psql','-U','postgres','-d',database,'-Atc',
                         "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
            self.assertEqual(absent.stdout.strip(),'0','held migration lock must prevent schema writes')
            docker('exec',root.name+'-pg','psql','-U','postgres','-Atc',
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='"+name+"' AND datname='"+database+"'")
            for job in jobs:
                result=docker('wait',job,timeout=180)
                self.assertEqual(result.stdout.strip(),'0','competing migration failed')
            result=image_run(root,'-m','scripts.workspace_pg','migrate',env_file=env)
            self.assertEqual(result.returncode,0,'repeated migration failed')
            result=docker('exec',root.name+'-pg','psql','-U','postgres','-d',database,'-Atc',
                         'SELECT version_num FROM alembic_version')
            self.assertEqual(result.stdout.strip(),'9b1d0c5e7a42')
        finally:
            for job in jobs:docker('rm','-f',job,check=False)
            docker('exec',root.name+'-pg','psql','-U','postgres','-Atc',
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='"+name+"' AND datname='"+database+"'",check=False)
            holder.wait(timeout=10);output.close()


class AppAPITests(unittest.TestCase):
    def test_original_accounts_sessions_pat_crypto_and_isolation(self):
        from fixtures import api_base,api_request
        root=Path(os.environ['WORKSPACE_FIXTURE']).resolve()
        names=os.environ['WORKSPACE_APP_NAMES'].split(',')
        bases=[api_base(root,name) for name in names]
        env=dict(line.split('=',1) for line in (root/'lifecycle.env').read_text().splitlines())
        cases=json.loads((root/'auth-cases-v5.json').read_text())
        def call(path,**kwargs):return api_request(bases[0],path,env['OPENBB_AUTH_TOKEN'],**kwargs)
        for key,expected in [('session_valid',200),('session_expired',401),('session_revoked',401)]:
            status,_=call('/pro/dash/sync/owned',token=cases[key])
            self.assertEqual(status,expected,key+' response status')
        request={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}
        for key,accepted in [('pat_valid',True),('pat_revoked',False)]:
            status,payload=call('/mcp',token=cases[key],body=request)
            self.assertEqual(status,200,key+' transport status')
            self.assertEqual('result' in payload,accepted,key+' authorization result')
            self.assertEqual('error' in payload,not accepted,key+' authorization error')
        tokens={}
        for email in ('fixture@example.com','second@example.com','coworker@example.com'):
            import time
            deadline=time.monotonic()+65
            while True:
                status,body=call('/pro/login',body={'email':email,'password':env['OPENBB_ADMIN_PASSWORD']})
                if status!=429 or time.monotonic()>=deadline:break
                # The pinned 5/minute policy survives Redis restoration/restart.
                # Wait for its normal window; never flush or exempt the fixture.
                time.sleep(min(5,max(0,deadline-time.monotonic())))
            self.assertEqual(status,200,'original password login')
            tokens[email]=body['access_token']
        token=tokens['fixture@example.com']
        for base in bases:
            def get(path,auth=token):
                status,value=api_request(base,path,env['OPENBB_AUTH_TOKEN'],token=auth)
                self.assertEqual(status,200,path+' response status')
                return value
            owned=get('/pro/dash/sync/owned')['owned']
            self.assertTrue(owned)
            self.assertTrue(get('/pro/user-apps/sync')['owned'])
            encrypted=get('/pro/data-connectors/api-source')
            self.assertTrue(encrypted)
            self.assertTrue(any(row.get('endpointHeaders')==[{'key':'X-Synthetic','value':'preserved','location':'headers'}] for row in encrypted),'actual encrypted field must decrypt to original plaintext')
            hidden=get('/pro/dash/sync/system/docks')['dashboard']
            self.assertIsNotNone(hidden)
            self.assertEqual(hidden['id'],'docks')
            self.assertTrue(hidden['hidden'])
            self.assertNotIn('docks',owned)
            self.assertTrue(all(not item.get('hidden',False) for item in owned.values()))
            secondary=get('/pro/dash/sync/system/docks',tokens['second@example.com'])['dashboard']
            if os.environ.get('WORKSPACE_AFTER_WRITES')=='1':
                expected=json.loads((root/'post-write-expected.json').read_text())['secondary_docks']
                self.assertEqual(secondary['content'],expected['content'])
                self.assertNotEqual(hidden['content'],secondary['content'])
            else:self.assertIsNone(secondary)
        output=root/('api-tokens-'+os.environ.get('WORKSPACE_API_LABEL','fixture')+'.json')
        output.write_text(json.dumps(tokens));output.chmod(0o600)


class NewWriteTests(unittest.TestCase):
    def test_two_instances_new_settings_dashboards_apps_shares_and_dock_races(self):
        from concurrent.futures import ThreadPoolExecutor
        from uuid import uuid4
        from fixtures import api_base,api_request
        root=Path(os.environ['WORKSPACE_FIXTURE']).resolve()
        bases=[api_base(root,name) for name in os.environ['WORKSPACE_APP_NAMES'].split(',')]
        self.assertEqual(len(bases),2,'two independent image processes are mandatory')
        env=dict(line.split('=',1) for line in (root/'lifecycle.env').read_text().splitlines())
        tokens=json.loads((root/'api-tokens-pg.json').read_text())
        def call(index,path,*,email='fixture@example.com',body=None,method=None,expected=200):
            status,value=api_request(bases[index],path,env['OPENBB_AUTH_TOKEN'],token=tokens[email],body=body,method=method)
            self.assertEqual(status,expected,path+' status')
            return value
        display={'theme':'light','fixtureExtension':{'afterMigration':True,'unknown':['preserved',None,77]}}
        call(0,'/pro/display-settings',body=display)
        self.assertEqual(call(1,'/pro/user')['pro_display_settings']['fixtureExtension'],display['fixtureExtension'])
        # Existing update semantics are unconditional last-write-wins.
        display['fixtureExtension']['winner']='second-process'
        call(1,'/pro/display-settings',body=display)
        self.assertEqual(call(0,'/pro/user')['pro_display_settings']['fixtureExtension'],display['fixtureExtension'])
        dashboard=str(uuid4());app=str(uuid4())
        content={'name':'Created after PostgreSQL migration','fixtureExtension':{'postWrite':True}}
        call(0,'/pro/dash/sync',body={'items':{dashboard:content}})
        self.assertEqual(call(1,'/pro/dash/sync/owned')['owned'][dashboard]['content'],content)
        app_content={'name':'Post-migration app','widgets':[],'fixtureExtension':{'postWrite':True}}
        call(1,'/pro/user-apps/'+app,body=app_content)
        call(0,'/pro/user-apps/'+app+'/share',body={'shares':{'coworker@example.com':'view'}})
        shared=call(1,'/pro/user-apps/sync',email='coworker@example.com')['shared']
        self.assertIn(app,shared)
        self.assertNotIn(app,call(0,'/pro/user-apps/sync',email='second@example.com')['shared'])
        path='/pro/dash/sync/system/docks'
        def race(index):
            return api_request(bases[index],path,env['OPENBB_AUTH_TOKEN'],token=tokens['second@example.com'],
                method='PUT',body={'revision':21+index,'content':{'raceProcess':index}})
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(race,(0,1)))
        self.assertTrue(all(status in (200,409) for status,_ in results))
        self.assertTrue(any(status==200 for status,_ in results))
        final={'revision':22,'content':{'raceWinner':'retry','afterMigration':True}}
        call(0,path,email='second@example.com',method='PUT',body=final)
        call(1,path,email='second@example.com',method='PUT',body={'revision':21,'content':{}},expected=409)
        self.assertEqual(call(1,path,email='second@example.com')['dashboard']['content'],final['content'])
        self.assertNotEqual(call(0,path)['dashboard']['content'],final['content'])
        self.assertNotIn('docks',call(1,'/pro/dash/sync/owned')['owned'])
        expected={'display':display,'dashboard':dashboard,'dashboard_content':content,'app':app,'app_content':app_content,'secondary_docks':final}
        output=root/'post-write-expected.json';output.write_text(json.dumps(expected));output.chmod(0o600)


class RestoredWriteTests(unittest.TestCase):
    def test_actual_api_retains_new_postgresql_writes_after_restore(self):
        from fixtures import api_base,api_request
        root=Path(os.environ['WORKSPACE_FIXTURE']).resolve();expected=json.loads((root/'post-write-expected.json').read_text())
        label=os.environ['WORKSPACE_API_LABEL'];tokens=json.loads((root/('api-tokens-'+label+'.json')).read_text())
        env=dict(line.split('=',1) for line in (root/'lifecycle.env').read_text().splitlines())
        for name in os.environ['WORKSPACE_APP_NAMES'].split(','):
            base=api_base(root,name)
            def get(path,email='fixture@example.com'):
                status,value=api_request(base,path,env['OPENBB_AUTH_TOKEN'],token=tokens[email])
                self.assertEqual(status,200,path+' status');return value
            self.assertEqual(get('/pro/user')['pro_display_settings']['fixtureExtension'],expected['display']['fixtureExtension'])
            self.assertEqual(get('/pro/dash/sync/owned')['owned'][expected['dashboard']]['content'],expected['dashboard_content'])
            self.assertEqual(get('/pro/user-apps/sync')['owned'][expected['app']]['content']['fixtureExtension'],expected['app_content']['fixtureExtension'])
            self.assertIn(expected['app'],get('/pro/user-apps/sync','coworker@example.com')['shared'])
            hidden=get('/pro/dash/sync/system/docks','second@example.com')['dashboard']
            self.assertEqual(hidden['revision'],expected['secondary_docks']['revision'])
            self.assertEqual(hidden['content'],expected['secondary_docks']['content'])





class RefusalTests(unittest.TestCase):
    def test_selected_serve_refuses_incomplete_inputs_without_listener_or_mutation(self):
        import shutil
        from uuid import uuid4
        root=Path(os.environ['WORKSPACE_FIXTURE']).resolve();image=os.environ['WORKSPACE_TEST_IMAGE']
        database='openbq_workspace_refuse_'+secrets.token_hex(4)
        self.assertEqual(create_database(root,database).returncode,0)
        maintenance=dict(line.split('=',1) for line in (root/'maintenance.env').read_text().splitlines())
        maintenance['DB_NAME']=database
        maintenance['WORKSPACE_TARGET_DSN']=maintenance['WORKSPACE_TARGET_DSN'].rsplit('/',1)[0]+'/'+database
        env=root/(database+'.env');env.write_text(''.join(k+'='+v+'\n' for k,v in maintenance.items()));env.chmod(0o600)
        self.assertEqual(image_run(root,'-m','scripts.workspace_pg','migrate',env_file=env).returncode,0)
        mapping=root/(database+'-map.json')
        result=image_run(root,'-m','scripts.workspace_migration','import','--root','/fixture',
            '--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source-v6.db'),'--run-id','refusal',
            '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+mapping.name,env_file=env)
        self.assertEqual(result.returncode,0)
        # The checkpoint includes every physical table hash and original source.
        verify=['-m','scripts.workspace_migration','verify','--root','/fixture','--source',
                '/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source-v6.db'),'--run-id','refusal']
        partial=database+'_partial';self.assertEqual(create_database(root,partial).returncode,0)
        runtime=dict(line.split('=',1) for line in (root/'runtime.env').read_text().splitlines())
        runtime.update(DB_NAME=database,WORKSPACE_PERMISSION_MAP_FILE='/data/permission-map.json')
        # No WORKSPACE_DB_ACTION: PostgreSQL's default must fail closed as serve.
        runtime.pop('WORKSPACE_DB_ACTION',None)
        cases={
            'missing_database':{'DB_NAME':database+'_absent'},
            'partial_schema':{'DB_NAME':partial},
            'unavailable_database':{'DB_PORT':'1'},
            'insufficient_role':{'READ_DB_USER':maintenance['READ_DB_USER'],'READ_DB_PASSWORD':maintenance['READ_DB_PASSWORD']},
            'wrong_key':{'OPENBB_AES_KEY':'different accepted text'},
            'missing_keys':{},'missing_mapping':{},'invalid_mapping':{},
            'untrusted_tls':{'SSL_CA':'/run/untrusted.crt'},
            'wrong_tls_hostname':{'SSL_CA':'/run/ca.crt','DB_HOST':root.name+'-pg'},
            'invalid_workers':{'WORKERS':'2'},
        }
        for label,overrides in cases.items():
            with self.subTest(case=label):
                data=root/(database+'-'+label);data.mkdir(mode=0o700)
                shutil.copyfile(mapping,data/'permission-map.json');(data/'permission-map.json').chmod(0o600)
                values={**runtime,**overrides}
                if label=='missing_keys':
                    for key in ('OPENBB_AES_KEY','OPENBB_AUTH_TOKEN','JWT_SECRET','LOCAL_STORAGE_SECRET_KEY'):values.pop(key,None)
                if label=='missing_mapping':(data/'permission-map.json').unlink()
                if label=='invalid_mapping':
                    value=json.loads(mapping.read_text());value['inviting_uuid']=str(uuid4())
                    (data/'permission-map.json').write_text(json.dumps(value))
                case_env=root/(database+'-'+label+'.env');case_env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));case_env.chmod(0o600)
                name=database+'-'+label
                try:
                    result=docker('run','--rm','--name',name,'--label','openbq.task=5.2','--platform','linux/amd64',
                        '--network',root.name,'--env-file',str(case_env),'-v',str(data)+':/data',
                        '-v',str(root/'tls/ca.crt')+':/run/ca.crt:ro',
                        '-v',str(root/'tls/untrusted.crt')+':/run/untrusted.crt:ro',image,check=False,timeout=45)
                    self.assertEqual(result.returncode,1,'unsafe serve did not exit before daemon startup')
                    self.assertNotIn('supervisord',result.stdout+result.stderr)
                    for key in ('OPENBB_AUTH_TOKEN','OPENBB_AES_KEY','JWT_SECRET','READ_DB_PASSWORD','WRITE_DB_PASSWORD'):
                        if values.get(key):self.assertNotIn(values[key],result.stdout+result.stderr)
                    self.assertFalse((data/'openbb.db').exists())
                    self.assertFalse((data/'secrets.env').exists())
                finally:docker('rm','-f',name,check=False)
        self.assertEqual(image_run(root,*verify,env_file=env).returncode,0,'failed startup changed imported physical state')
        # URI query overrides are refused before opening a target connection.
        result=image_run(root,*verify,env_file=env,
                         environment={'WORKSPACE_TARGET_DSN':maintenance['WORKSPACE_TARGET_DSN']+'?password=generated-query-sentinel'})
        self.assertEqual(result.returncode,1)
        self.assertNotIn('generated-query-sentinel',result.stdout+result.stderr)


if __name__=='__main__':unittest.main(verbosity=2)
