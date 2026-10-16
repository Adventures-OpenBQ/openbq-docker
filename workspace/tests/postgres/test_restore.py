# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
"""Actual-image full transfer and crash/retry qualification; no source mounts."""
import json
import os
from pathlib import Path
import secrets
import unittest

from fixtures import create_database, image_run


class TransferImageTests(unittest.TestCase):
    def setUp(cls):
        cls.root=Path(os.environ['WORKSPACE_FIXTURE']).resolve()
        cls.name='openbq_workspace_gate_'+secrets.token_hex(4)
        result=create_database(cls.root,cls.name)
        if result.returncode:raise RuntimeError('fresh fixture database provisioning failed')
        values=dict(line.split('=',1) for line in (cls.root/'maintenance.env').read_text().splitlines())
        values['DB_NAME']=cls.name
        values['WORKSPACE_TARGET_DSN']=values['WORKSPACE_TARGET_DSN'].rsplit('/',1)[0]+'/'+cls.name
        cls.env=cls.root/(cls.name+'.env')
        cls.env.write_text(''.join(k+'='+v+'\n' for k,v in values.items()));cls.env.chmod(0o600)
        result=image_run(cls.root,'-m','scripts.workspace_pg','migrate',env_file=cls.env)
        (cls.root/(cls.name+'-migration.log')).write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('actual image migration failed')

    def run_image(self,*args,expected=0,environment=None):
        result=image_run(self.root,*args,env_file=self.env,environment=environment)
        self.assertEqual(result.returncode,expected,'actual image operation returned unexpected status; no row diagnostics published')
        return result

    def test_unsupported_source_and_ambiguous_mapping_leave_target_unchanged(self):
        import shutil,sqlite3,uuid,hashlib
        def evidence():
            return self.run_image('-c',"from scripts import workspace_migration as m\ne=m.pg_engine()\nwith m.locked_target(e) as c:print(m.fingerprint(m.data_evidence(c,'postgresql',m.load_manifest())))\ne.dispose()").stdout
        before=evidence()
        original=self.root/os.environ.get('WORKSPACE_SOURCE','full-source-v6.db')
        variants=('partial','missing-table','changed-type','changed-fk','missing-index','unknown-revision','unsupported-json','ambiguous-admin')
        for variant in variants:
            source=self.root/(self.name+'-'+variant+'.db')
            if variant=='partial':
                with sqlite3.connect(source) as db:
                    db.execute('CREATE TABLE user(uuid BLOB PRIMARY KEY)')
                    db.execute('CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)')
                    db.execute("INSERT INTO alembic_version VALUES ('9b1d0c5e7a42')")
            else:
                shutil.copyfile(original,source);source.chmod(0o600)
                with sqlite3.connect(source) as db:
                    if variant=='missing-table':db.execute('DROP TABLE feedback')
                    elif variant=='unknown-revision':db.execute("UPDATE alembic_version SET version_num='unknown'")
                    elif variant=='unsupported-json':db.execute("UPDATE user SET pro_display_settings=?",('{"invalid":"\\u0000"}',))
                    elif variant=='missing-index':
                        index=db.execute("SELECT name FROM sqlite_schema WHERE type='index' AND sql IS NOT NULL LIMIT 1").fetchone()[0]
                        db.execute('DROP INDEX "'+index.replace('"','""')+'"')
                    elif variant=='ambiguous-admin':
                        entity=uuid.UUID(json.loads((self.root/'mapping-input.json').read_text())['entity_uuid']).bytes
                        row=db.execute("SELECT * FROM permissions_entity_map WHERE name='Admin' AND entity_uuid=?",(entity,)).fetchone()
                        columns=[r[1] for r in db.execute('PRAGMA table_info(permissions_entity_map)')]
                        values=list(row);values[columns.index('uuid')]=uuid.uuid4().bytes
                        db.execute('INSERT INTO permissions_entity_map VALUES('+','.join('?' for _ in values)+')',values)
                    else:
                        # Deliberate physical-schema drift, reopened by the actual importer.
                        sql=db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name='user'").fetchone()[0]
                        changed=sql.replace('VARCHAR','TEXT',1)
                        if variant=='changed-fk':
                            import re
                            changed=re.sub(r',?\s*(?:CONSTRAINT \w+ )?FOREIGN KEY\([^)]*\) REFERENCES [^,(]+\([^)]*\)(?: ON DELETE \w+)?','',sql,count=1)
                        self.assertNotEqual(changed,sql)
                        import re
                        indexes=[row[0] for row in db.execute("SELECT sql FROM sqlite_schema WHERE type='index' AND tbl_name='user' AND sql IS NOT NULL")]
                        rebuilt=re.sub(r'(?i)^(CREATE TABLE\s+)(?:"user"|user)',r'\1user_drift',changed,count=1)
                        db.execute(rebuilt)
                        db.execute('INSERT INTO user_drift SELECT * FROM user')
                        db.execute('DROP TABLE user')
                        db.execute('ALTER TABLE user_drift RENAME TO user')
                        for statement in indexes:db.execute(statement)
                db.close()
            digest=hashlib.sha256(source.read_bytes()).digest()
            mapping=self.root/(source.stem+'-map.json')
            self.run_image('-m','scripts.workspace_migration','import','--root','/fixture',
                '--source','/fixture/'+source.name,'--run-id',variant,'--mapping','/fixture/mapping-input.json',
                '--mapping-output','/fixture/'+mapping.name,expected=1)
            self.assertFalse(mapping.exists())
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),digest)
            self.assertEqual(evidence(),before,'rejected import changed target rows')
        self.run_image('-c',"from scripts import workspace_migration as m\ne=m.pg_engine()\nwith m.locked_target(e) as c:assert c.exec_driver_sql('SELECT count(*) FROM workspace_admin.migration_runs').scalar_one()==0\ne.dispose()")

    def test_complete_transfer_checkpoint_binds_identity_and_recovers_map(self):
        mapping='/fixture/'+self.name+'-mapping.json'
        args=['-m','scripts.workspace_migration','import','--root','/fixture','--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source.db'),
              '--run-id','complete','--mapping','/fixture/mapping-input.json','--mapping-output',mapping]
        result=self.run_image(*args)
        self.assertEqual(json.loads(result.stdout)['tables'],54)
        self.run_image(*args)
        self.run_image('-m','scripts.workspace_migration','verify','--root','/fixture','--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source.db'),'--run-id','complete')
        # Same semantic identity, new destination is recovery, not a new import.
        self.run_image(*args[:-1],mapping+'.recovered')
        self.assertEqual((self.root/Path(mapping).name).read_bytes(),(self.root/(Path(mapping).name+'.recovered')).read_bytes())
        # Keep the JWT valid while changing an accepted AES string: checkpoint,
        # not token parsing or output-file collision, must reject this retry.
        self.run_image(*args[:-1],mapping+'.wrong',expected=1,environment={'OPENBB_AES_KEY':'different accepted arbitrary text'})
        self.assertFalse((self.root/(Path(mapping).name+'.wrong')).exists())
        # Another valid entity/admin relationship must not relabel this checkpoint,
        # even with the same keys and a previously nonexistent output destination.
        import sqlite3
        from uuid import UUID
        with sqlite3.connect('file:'+str(self.root/os.environ.get('WORKSPACE_SOURCE','full-source.db'))+'?mode=ro',uri=True) as source:
            user,entity=source.execute("SELECT u.uuid,p.entity_uuid FROM user u JOIN permissions_entity_map p ON p.uuid=u.permissions_uuid WHERE u.email='second@example.com'").fetchone()
        alternate=self.root/(self.name+'-alternate-map.json')
        alternate.write_text(json.dumps({'entity_uuid':str(UUID(bytes=entity)),'inviting_uuid':str(UUID(bytes=user))}));alternate.chmod(0o600)
        changed_mapping=list(args);changed_mapping[changed_mapping.index('--mapping')+1]='/fixture/'+alternate.name
        changed_mapping[-1]=mapping+'.different-identity'
        self.run_image(*changed_mapping,expected=1)
        self.assertFalse((self.root/(Path(mapping).name+'.different-identity')).exists())
        # A completed target is not an overwrite destination for another run.
        different=list(args);different[different.index('complete')]='different-run'
        self.run_image(*different,expected=1)
        mutation="""from scripts import workspace_migration as m
e=m.pg_engine()
with m.locked_target(e) as c:
 with c.begin():c.exec_driver_sql('UPDATE tier SET has_trial=NOT has_trial')
e.dispose()
"""
        self.run_image('-c',mutation)
        self.run_image(*args,expected=1)
        self.run_image('-c',mutation)
        # A same-schema edited source is still a different immutable import.
        import shutil,sqlite3
        changed=self.root/(self.name+'-changed-source.db')
        shutil.copyfile(self.root/os.environ.get('WORKSPACE_SOURCE','full-source.db'),changed)
        with sqlite3.connect(changed) as db:db.execute('UPDATE tier SET has_trial=NOT has_trial')
        db.close()
        different=list(args);different[different.index('--source')+1]='/fixture/'+changed.name
        self.run_image(*different,expected=1)
        self.run_image('-m','scripts.workspace_migration','export-sqlite','--root','/fixture',
                       '--output','/fixture/'+self.name+'-reverse.db','--quiesced',
                       '--mapping','/fixture/mapping-input.json','--mapping-output',mapping+'.reverse')


    def test_row_security_drift_refuses_all_operations_before_mutation_or_listener(self):
        import hashlib,subprocess,time
        mapping=self.root/(self.name+'-rls-map.json')
        source=self.root/os.environ.get('WORKSPACE_SOURCE','full-source-v6.db')
        args=['--root','/fixture','--source','/fixture/'+source.name,'--run-id','rls-check',
              '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+mapping.name]
        self.run_image('-m','scripts.workspace_migration','import',*args)
        evidence="""from scripts import workspace_migration as m
import json
e=m.pg_engine()
with m.locked_target(e) as c:
 print(m.fingerprint({'tables':m.data_evidence(c,'postgresql',m.load_manifest()),
 'checkpoints':[list(r) for r in c.exec_driver_sql('SELECT run_id,source_hash,normalized_hash,manifest_hash,target_identity,evidence FROM workspace_admin.migration_runs')],
 'ready':[list(map(str,r)) for r in c.exec_driver_sql('SELECT * FROM workspace_admin.readiness')]}))
e.dispose()
"""
        before=self.run_image('-c',evidence).stdout
        preserved={p:p.read_bytes() for p in (source,mapping,self.root/'sqlite-baseline-v6/secrets.env')}
        for label,ddl in (
            ('enabled','ALTER TABLE public.dashboard_item ENABLE ROW LEVEL SECURITY'),
            ('forced','ALTER TABLE public.dashboard_item FORCE ROW LEVEL SECURITY'),
            ('policy-only','CREATE POLICY task52_drift ON public.dashboard_item USING (true)')):
            with self.subTest(variant=label):
                docker('exec',self.root.name+'-pg','psql','-U','postgres','-d',self.name,'-v','ON_ERROR_STOP=1','-c',ddl)
                try:
                    # Direct schema validation is the RED boundary on the old image.
                    self.run_image('-c',"from scripts import workspace_migration as m\ne=m.pg_engine()\nwith m.locked_target(e) as c:m.validate_postgres(c,m.load_manifest())",expected=1)
                    self.run_image('-m','scripts.workspace_migration','import',*args,expected=1)
                    self.run_image('-m','scripts.workspace_migration','verify',*args[:6],expected=1)
                    output=self.root/(self.name+'-'+label+'.db');outmap=self.root/(output.name+'.json')
                    self.run_image('-m','scripts.workspace_migration','export-sqlite','--root','/fixture',
                        '--output','/fixture/'+output.name,'--quiesced','--mapping','/fixture/mapping-input.json',
                        '--mapping-output','/fixture/'+outmap.name,expected=1)
                    self.assertFalse(output.exists());self.assertFalse(outmap.exists())
                    values=env_values(self.root/'runtime.env');values.update(DB_NAME=self.name,
                        WORKSPACE_PERMISSION_MAP_FILE='/fixture/'+mapping.name,DATA_DIR='/fixture/sqlite-baseline-v6')
                    env=save_env(self.root/(self.name+'-'+label+'.env'),values)
                    job=self.name+'-'+label
                    docker('run','-d','--name',job,'--label','openbq.task=5.2','--platform','linux/amd64',
                        '--network',self.root.name,'--env-file',str(env),'-v',str(self.root)+':/fixture:ro',
                        os.environ['WORKSPACE_TEST_IMAGE'])
                    try:
                        result=docker('wait',job,timeout=30)
                        self.assertEqual(result.stdout.strip(),'1','row-security drift must refuse serve')
                        logs=docker('logs',job).stdout
                        self.assertNotIn('supervisord started',logs)
                        self.assertEqual(docker('inspect','--format','{{.State.ExitCode}}',job).stdout.strip(),'1')
                    finally:docker('rm','-f',job,check=False)
                finally:
                    docker('exec',self.root.name+'-pg','psql','-U','postgres','-d',self.name,'-v','ON_ERROR_STOP=1','-c',
                        'ALTER TABLE public.dashboard_item DISABLE ROW LEVEL SECURITY; ALTER TABLE public.dashboard_item NO FORCE ROW LEVEL SECURITY; DROP POLICY IF EXISTS task52_drift ON public.dashboard_item')
                self.assertEqual(self.run_image('-c',evidence).stdout,before,'refused operations changed database data/checkpoints')
                for path,content in preserved.items():self.assertTrue(path.read_bytes()==content,'refusal changed preserved source/map/keys')

    def test_reverse_export_refuses_resolved_output_collision_before_work(self):
        mapping=self.root/(self.name+'-collision-map.json')
        self.run_image('-m','scripts.workspace_migration','import','--root','/fixture',
            '--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source-v6.db'),'--run-id','collision-check',
            '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+mapping.name)
        for index,relative in enumerate(('', './', 'alias/../')):
            (self.root/'alias').mkdir(exist_ok=True)
            output=self.root/(self.name+'-overlap-'+str(index)+'.db')
            args=['export-sqlite','--root','/fixture','--output','/fixture/'+output.name,
                  '--quiesced','--mapping','/fixture/mapping-input.json',
                  '--mapping-output','/fixture/'+relative+output.name]
            self.run_image('-m','scripts.workspace_migration',*args,expected=1)
            self.assertFalse(output.exists(),'refused overlap published a non-database artifact')
            # A CLI invocation guard proves rejection precedes engine/temp DB work.
            self.run_image('-c',"from scripts import workspace_migration as m\ndef forbidden(*a,**k):raise AssertionError('work started')\nm.pg_engine=forbidden\nm.tempfile.TemporaryDirectory=forbidden\ntry:m.main()\nexcept ValueError:raise SystemExit(19)",*args,expected=19)
        output=self.root/(self.name+'-distinct.db');outmap=self.root/(output.name+'.json')
        self.run_image('-m','scripts.workspace_migration','export-sqlite','--root','/fixture',
            '--output','/fixture/'+output.name,'--quiesced','--mapping','/fixture/mapping-input.json',
            '--mapping-output','/fixture/'+outmap.name)
        self.assertTrue(output.read_bytes().startswith(b'SQLite format 3\x00'))
        self.assertTrue(outmap.is_file())

    def test_complete_pg_schema_refuses_extra_objects_and_constraint_drift(self):
        code="""from scripts import workspace_migration as m
engine=m.pg_engine();manifest=m.load_manifest()
schema=manifest['schemas']['postgresql-'+m.HEAD]['schema']
foreign=schema['tables']['user']['foreign_keys'][0]['name']
index=schema['tables']['user']['indexes'][0]['name']
statements=['CREATE VIEW public.unrecognized_view AS SELECT 1 AS value',
 "CREATE FUNCTION public.unrecognized_function() RETURNS integer LANGUAGE SQL AS 'SELECT 1'",
 'CREATE SEQUENCE public.unrecognized_sequence',
 'ALTER TABLE public."user" ADD COLUMN unrecognized integer',
 'ALTER TABLE public."user" DROP CONSTRAINT '+m.identifier(foreign),
 'DROP INDEX public.'+m.identifier(index),
 "ALTER TYPE public.permissionenum ADD VALUE 'synthetic_unknown'"]
with m.locked_target(engine) as c:
 for statement in statements:
  transaction=c.begin()
  try:
   c.exec_driver_sql(statement)
   try:m.validate_postgres(c,manifest)
   except ValueError:pass
   else:raise AssertionError('unknown complete schema was accepted')
  finally:transaction.rollback()
 for table in ('entity_entitlement','default_tier','entitlement'):
  check=schema['tables'][table]['check'][0]
  for expression in (check['sqltext'].replace("'private'","'other'"),check['sqltext'].replace('= ANY','<> ALL'),check['sqltext']+' OR true'):
   transaction=c.begin()
   try:
    c.exec_driver_sql('ALTER TABLE '+m.identifier(table)+' DROP CONSTRAINT '+m.identifier(check['name']))
    c.exec_driver_sql('ALTER TABLE '+m.identifier(table)+' ADD CONSTRAINT '+m.identifier(check['name'])+' CHECK ('+expression+') NOT VALID')
    try:m.validate_postgres(c,manifest)
    except ValueError:pass
    else:raise AssertionError('altered pinned CHECK was accepted')
   finally:transaction.rollback()
engine.dispose()
"""
        self.run_image('-c',code)

    def test_transactional_sequence_next_id_empty_negative_and_maximum(self):
        code="""from scripts import workspace_migration as m
from sqlalchemy.exc import DBAPIError
e=m.pg_engine();manifest=m.load_manifest()
with m.locked_target(e) as c:
 before=tuple(c.exec_driver_sql('SELECT last_value,is_called FROM tier_id_seq').one())
 template=dict(c.exec_driver_sql('SELECT * FROM tier LIMIT 1').mappings().one());c.commit()
 for maximum in (None,-1,0,17,2147483647):
  transaction=c.begin()
  try:
   for table in reversed(manifest['mapping']['insert_order']):
    if table!='alembic_version':c.exec_driver_sql('DELETE FROM public.'+m.identifier(table))
   if maximum is not None:
    row={**template,'id':maximum};columns=manifest['mapping']['tables']['tier']['columns']
    m.insert_rows(c,'postgresql','tier',columns,[tuple(row[col['name']] for col in columns)])
   m.reconcile_tier_sequence(c,manifest)
   m.validate_postgres(c,manifest)
   if maximum==2147483647:
    try:c.exec_driver_sql('SELECT nextval(%s)',('tier_id_seq',))
    except DBAPIError:pass
    else:raise AssertionError('exhausted sequence must stay exhausted')
   else:
    value=c.exec_driver_sql('SELECT nextval(%s)',('tier_id_seq',)).scalar_one()
    assert value==(maximum+1 if maximum is not None and maximum>=1 else 1)
    assert c.exec_driver_sql('SELECT count(*) FROM tier WHERE id=%s',(value,)).scalar_one()==0
  finally:transaction.rollback()
  assert tuple(c.exec_driver_sql('SELECT last_value,is_called FROM tier_id_seq').one())==before
  c.commit()
e.dispose()
"""
        self.run_image('-c',code)

    def test_verification_rejects_manifest_or_target_checkpoint_tampering(self):
        source='/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source.db')
        self.run_image('-m','scripts.workspace_migration','import','--root','/fixture','--source',source,
            '--run-id','binding','--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+self.name+'-binding.json')
        for field in ('manifest_hash','target_identity'):
            code="""from scripts import workspace_migration as m
engine=m.pg_engine()
with m.locked_target(engine) as c:
 with c.begin():
  c.exec_driver_sql('UPDATE workspace_admin.migration_runs SET '+__import__('sys').argv[1]+"='synthetic-tamper' WHERE run_id='binding'")
engine.dispose()
"""
            self.run_image('-c',code,field)
            self.run_image('-m','scripts.workspace_migration','verify','--root','/fixture','--source',source,'--run-id','binding',expected=1)
            restore="""from scripts import workspace_migration as m
engine=m.pg_engine()
with m.locked_target(engine) as c:
 with c.begin():
  c.exec_driver_sql("UPDATE workspace_admin.migration_runs SET manifest_hash=%s,target_identity=%s WHERE run_id='binding'",(m.fingerprint(m.load_manifest()),m.target_identity(c,engine)))
engine.dispose()
"""
            self.run_image('-c',restore)

    def test_atomic_failure_and_crash_boundaries(self):
        self.run_image('-c',"""from scripts import workspace_migration as m
e=m.pg_engine()
with m.locked_target(e) as c:
 with c.begin():
  assert c.exec_driver_sql('SELECT max(id) FROM tier').scalar_one()<100
  c.exec_driver_sql('SELECT setval(%s,100,true)',('tier_id_seq',))
e.dispose()
""")
        mapping='/fixture/'+self.name+'-crash-map.json'
        args=['import','--root','/fixture','--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source.db'),
              '--run-id','crashcase','--mapping','/fixture/mapping-input.json','--mapping-output',mapping]
        setup="""import os,sys
from sqlalchemy import event
from sqlalchemy.engine import Engine
from scripts import workspace_migration as m
"""
        late=setup+"""last=m.load_manifest()['mapping']['insert_order'][-1]
@event.listens_for(Engine,'before_cursor_execute')
def fail(connection,cursor,statement,parameters,context,many):
 if statement.startswith('INSERT INTO public.'+m.identifier(last)+'('):cursor.execute('SELECT 1/0')
m.main()
"""
        self.run_image('-c',late,*args,expected=1)
        empty=setup+"""engine=m.pg_engine()
with m.locked_target(engine) as c:
 manifest=m.load_manifest()
 assert m.seed_signature(c,manifest)==manifest['seed_signature']
 assert c.exec_driver_sql('SELECT count(*) FROM workspace_admin.migration_runs').scalar_one()==0
 assert c.exec_driver_sql('SELECT count(*) FROM workspace_admin.readiness').scalar_one()==0
 assert tuple(c.exec_driver_sql('SELECT last_value,is_called FROM tier_id_seq').one())==(100,True)
 for table in manifest['mapping']['insert_order']:
  if table not in manifest['mapping']['seed_tables']:
   assert c.exec_driver_sql('SELECT count(*) FROM '+m.identifier(table)).scalar_one()==0
engine.dispose()
"""
        self.run_image('-c',empty)
        before=setup+"""pending=False
@event.listens_for(Engine,'before_cursor_execute')
def flag(connection,cursor,statement,parameters,context,many):
 global pending
 if statement.startswith('INSERT INTO workspace_admin.migration_runs'):pending=True
@event.listens_for(Engine,'commit')
def stop(connection):
 if pending:os._exit(71)
m.main()
"""
        self.run_image('-c',before,*args,expected=71)
        self.run_image('-c',empty)
        after=setup+"""def crash(path,mapping):os._exit(72)
m.publish_mapping=crash
m.main()
"""
        self.run_image('-c',after,*args,expected=72)
        self.assertFalse((self.root/Path(mapping).name).exists())
        self.run_image('-m','scripts.workspace_migration',*args)
        self.assertTrue((self.root/Path(mapping).name).is_file())
        self.run_image('-m','scripts.workspace_migration','verify','--root','/fixture',
            '--source','/fixture/'+os.environ.get('WORKSPACE_SOURCE','full-source.db'),'--run-id','crashcase')




# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
"""Actual two-process writes, PostgreSQL dump restore, inverse restore and reimport."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest

from fixtures import ROOT,DOCKER,api_base,api_request,create_database,docker,image_run


def env_values(path):
    return dict(line.split('=',1) for line in path.read_text().splitlines() if line and not line.startswith('#'))


def save_env(path,values):
    path.write_text(''.join(k+'='+str(v)+'\n' for k,v in values.items()));path.chmod(0o600)
    return path


class CompleteRestoreTests(unittest.TestCase):
    def test_new_writes_survive_both_actual_restores_and_reimport(self):
        self.root=Path(os.environ['WORKSPACE_FIXTURE']).resolve()
        self.image=os.environ['WORKSPACE_TEST_IMAGE'];self.jobs=[]
        self.tag=secrets.token_hex(4);self.source=self.root/os.environ.get('WORKSPACE_SOURCE','full-source-v6.db')
        self.assertTrue(self.source.is_file(),'complete immutable synthetic source required')
        self.env=env_values(self.root/'lifecycle.env')
        # Stop the earlier compatibility process before running the mandatory pair.
        old=self.root.name+'-sqlite'
        docker('stop','-t','30',old,check=False)
        self.pg,self.maintenance=self.new_database('primary')
        mapping=self.root/(self.pg+'-mapping.json')
        self.operation(self.maintenance,'-m','scripts.workspace_migration','import','--root','/fixture',
            '--source','/fixture/'+self.source.name,'--run-id','full-final',
            '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+mapping.name)
        before=self.evidence(self.maintenance)
        baseline=[self.start('baseline-sqlite',None,mapping,sqlite_source=self.source)]
        time.sleep(8)
        self.assertTrue(self.sqlite_evidence(baseline[0][1]/'openbb.db')==before,
                        'compatible SQLite startup changed the complete source')
        self.check_keys(baseline)
        self.api_tests(baseline,'baseline','AppAPITests')
        self.stop(baseline)
        primary=[self.start('pg'+str(i),self.pg,mapping) for i in (1,2)]
        # Startup plus ordinary scheduled-loop window precedes all authenticated writes.
        time.sleep(8)
        self.assertTrue(self.evidence(self.maintenance)==before,'imported startup/background changed stored rows')
        self.check_keys(primary)
        import threading
        samples=[];sampling_errors=[];finished=threading.Event()
        count_query="SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND usename IN ('openbq_workspace_read','openbq_workspace_write')"
        def sample_connections():
            while not finished.is_set():
                try:samples.append(int(self.sql(self.pg,count_query)))
                except Exception:sampling_errors.append(True);return
                finished.wait(.2)
        monitor=threading.Thread(target=sample_connections);monitor.start()
        try:
            self.api_tests(primary,'pg','AppAPITests')
            self.api_tests(primary,'pg','NewWriteTests')
        finally:finished.set();monitor.join(timeout=10)
        self.assertFalse(monitor.is_alive());self.assertFalse(sampling_errors)
        self.assertTrue(samples);self.assertLessEqual(max(samples),12)
        print('Observed runtime connection peak:',max(samples),'samples:',len(samples),flush=True)
        restart_before=self.evidence(self.maintenance)
        for name,_ in primary:docker('restart','-t','40',name)
        for name,_ in primary:
            base=api_base(self.root,name)
            for _ in range(90):
                try:
                    if api_request(base,'/health',self.env['OPENBB_AUTH_TOKEN'])[0]==200:break
                except Exception:pass
                time.sleep(1)
            else:self.fail('restarted actual application readiness deadline exceeded')
        time.sleep(8)
        self.assertTrue(self.evidence(self.maintenance)==restart_before,'restart changed persisted rows')
        self.check_keys(primary)
        self.api_tests(primary,'restart','AppAPITests',after=True)
        self.api_tests(primary,'restart','RestoredWriteTests',after=True)
        self.stop(primary)
        self.assertEqual(self.sql(self.pg,"SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND usename IN ('openbq_workspace_read','openbq_workspace_write')"),'0')
        post=self.evidence(self.maintenance)
        sequence_state=self.sql(self.pg,'SELECT last_value,is_called FROM tier_id_seq')
        # Native dump includes public + restricted metadata, roles/default grants,
        # sequence state and computed columns. Restore into an explicitly NEW DB.
        backup=self.root/(self.pg+'.dump')
        with backup.open('wb') as output:
            result=subprocess.run([DOCKER,'exec',self.root.name+'-pg','pg_dump','-U','postgres','-d',self.pg,'-Fc'],stdout=output,stderr=subprocess.PIPE)
        self.assertEqual(result.returncode,0,'native dump failed');backup.chmod(0o600)
        native,native_env=self.new_database('native',migrate=False)
        with backup.open('rb') as source:
            result=subprocess.run([DOCKER,'exec','-i',self.root.name+'-pg','pg_restore','-U','postgres','-d',native,'--clean','--if-exists','--exit-on-error'],stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(result.returncode,0,'clean native restore failed')
        self.assertTrue(self.evidence(native_env)==post,'native restored full data differs')
        self.assertEqual(self.sql(native,'SELECT last_value,is_called FROM tier_id_seq'),sequence_state)
        native_jobs=[self.start('native',native,mapping,companion=primary[0][1])]
        self.assertTrue(self.evidence(native_env)==post,'native restored startup changed rows')
        self.api_tests(native_jobs,'native','AppAPITests',after=True)
        self.api_tests(native_jobs,'native','RestoredWriteTests',after=True)
        self.stop(native_jobs)
        # Native restoration preserves the old checkpoint as audit evidence. It
        # cannot authorize replay of an import against a different database OID.
        self.operation(native_env,'-m','scripts.workspace_migration','verify','--root','/fixture',
            '--source','/fixture/'+self.source.name,'--run-id','full-final',expected=1)
        exported=self.root/(self.pg+'-post-write.db');reverse_map=self.root/(self.pg+'-reverse-map.json')
        self.operation(self.maintenance,'-m','scripts.workspace_migration','export-sqlite','--root','/fixture',
            '--output','/fixture/'+exported.name,'--quiesced','--mapping','/fixture/mapping-input.json',
            '--mapping-output','/fixture/'+reverse_map.name)
        sqlite_jobs=[self.start('restored-sqlite',None,reverse_map,sqlite_source=exported,companion=primary[0][1])]
        self.assertTrue(self.sqlite_evidence(sqlite_jobs[0][1]/'openbb.db')==post,'restored SQLite startup changed full table evidence')
        self.api_tests(sqlite_jobs,'reverse','AppAPITests',after=True)
        self.api_tests(sqlite_jobs,'reverse','RestoredWriteTests',after=True)
        self.stop(sqlite_jobs)
        fresh,fresh_env=self.new_database('reimport')
        fresh_map=self.root/(fresh+'-mapping.json')
        self.operation(fresh_env,'-m','scripts.workspace_migration','import','--root','/fixture',
            '--source','/fixture/'+exported.name,'--run-id','reverse-reimport',
            '--mapping','/fixture/mapping-input.json','--mapping-output','/fixture/'+fresh_map.name)
        self.assertTrue(self.evidence(fresh_env)==post,'reimport full table evidence differs')
        self.operation(fresh_env,'-c',"""from scripts import workspace_migration as m
e=m.pg_engine()
with m.locked_target(e) as c:
 for table,column in (('copilot_chat','label'),('copilot_messages','searchable_content')):
  assert c.exec_driver_sql('SELECT count(*) FROM '+table+' WHERE search_vector IS NOT NULL').scalar_one()>0
  assert c.exec_driver_sql("SELECT bool_and(search_vector=to_tsvector('simple',"+column+')) FROM '+table).scalar_one()
  assert c.exec_driver_sql("SELECT count(*) FROM "+table+" WHERE search_vector @@ plainto_tsquery('simple',"+column+')').scalar_one()>0
e.dispose()
""")
        fresh_jobs=[self.start('reimport',fresh,fresh_map,companion=primary[0][1])]
        self.api_tests(fresh_jobs,'reimport','AppAPITests',after=True)
        self.api_tests(fresh_jobs,'reimport','RestoredWriteTests',after=True)
        self.stop(fresh_jobs)
        print('Complete two-instance, native restore, inverse app restore and reimport gates passed.',flush=True)

    def new_database(self,label,migrate=True):
        name='openbq_workspace_'+label+'_'+self.tag
        self.assertEqual(create_database(self.root,name).returncode,0)
        values=env_values(self.root/'maintenance.env');values['DB_NAME']=name
        values['WORKSPACE_TARGET_DSN']=values['WORKSPACE_TARGET_DSN'].rsplit('/',1)[0]+'/'+name
        env=save_env(self.root/(name+'.env'),values)
        if migrate:self.operation(env,'-m','scripts.workspace_pg','migrate')
        return name,env

    def operation(self,env,*args,expected=0):
        result=image_run(self.root,*args,env_file=env)
        (self.root/(self.tag+'-last-operation.log')).write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode,expected,'actual image operation failed; private diagnostics retained')
        return result

    def evidence(self,env):
        result=self.operation(env,'-c',"from scripts import workspace_migration as m\nimport json\ne=m.pg_engine()\nwith m.locked_target(e) as c:\n m.validate_postgres(c,m.load_manifest())\n print(json.dumps(m.data_evidence(c,'postgresql',m.load_manifest())))\ne.dispose()")
        return json.loads(result.stdout)

    def sqlite_evidence(self,path):
        result=self.operation(self.maintenance,'-c',"from scripts import workspace_migration as m\nimport json,sys\nwith m.sqlite_read(__import__('pathlib').Path(sys.argv[1])) as c:print(json.dumps(m.data_evidence(c,'sqlite',m.load_manifest())))",'/fixture/'+str(path.relative_to(self.root)))
        return json.loads(result.stdout)

    def sql(self,database,query):
        return docker('exec',self.root.name+'-pg','psql','-U','postgres','-d',database,'-Atc',query).stdout.strip()

    def start(self,label,database,mapping,*,sqlite_source=None,companion=None):
        data=self.root/(self.tag+'-'+label+'-data')
        shutil.copytree(companion or self.root/'sqlite-baseline-v6',data)
        for name in ('openbb.db','openbb.db-wal','openbb.db-shm'):(data/name).unlink(missing_ok=True)
        if sqlite_source:shutil.copyfile(sqlite_source,data/'openbb.db');(data/'openbb.db').chmod(0o600)
        shutil.copyfile(mapping,data/'permission-map.json');(data/'permission-map.json').chmod(0o600)
        # Keep an actual stored-file companion; do not rewrite physical database rows.
        with sqlite3.connect('file:'+str(self.source)+'?mode=ro',uri=True) as db:
            files=db.execute('SELECT s3_file_name FROM stored_file').fetchall()
        for (name,) in files:
            file=data/'storage'/name
            self.assertTrue(file.resolve().is_relative_to((data/'storage').resolve()))
            self.assertTrue(file.is_file(),'declared stored-file companion is missing')
            self.assertTrue(file.read_bytes()==b'synthetic,value\nretained,52\n','stored-file companion changed')
        (data/'companion-inventory.json').write_text(json.dumps([row[0] for row in files]))
        (data/'companion-inventory.json').chmod(0o600)
        values=env_values(self.root/'runtime.env')
        values.update(WORKSPACE_DB_ACTION='serve',WORKSPACE_PERMISSION_MAP_FILE='/data/permission-map.json',
            OPENBB_ADMIN_EMAIL='fixture@example.com',OPENBB_ADMIN_PASSWORD='Changed bootstrap input must not reset imported accounts!',
            FOLDER_STORAGE_PATH='/data/storage',REDIS_HOST='127.0.0.1',SSL_CA='/run/workspace-ca.crt')
        if database:values['DB_NAME']=database
        else:values.update(DATABASE_TYPE='sqlite',DB_PATH='/data/openbb.db');values.pop('SSL_CA',None)
        env=save_env(self.root/(self.tag+'-'+label+'.env'),values)
        name=self.root.name+'-'+self.tag+'-'+label
        docker('run','--rm','--platform','linux/amd64','--entrypoint','chown',
            '-v',str(data)+':/data',self.image,'-R','appuser:appuser','/data')
        docker('run','-d','--name',name,'--label','openbq.task=5.2','--platform','linux/amd64',
            '--network',self.root.name,'--env-file',str(env),'-p','127.0.0.1::3000',
            '-v',str(data)+':/data','-v',str(self.root/'tls/ca.crt')+':/run/workspace-ca.crt:ro',self.image)
        self.jobs.append(name)
        # The imported companion belongs to the pinned appuser. Preserve owner on
        # Docker Desktop copied bind data; no runtime grant changes are involved.
        base=api_base(self.root,name)
        for _ in range(90):
            try:
                status,_=api_request(base,'/health',self.env['OPENBB_AUTH_TOKEN'])
                if status==200:break
            except Exception:pass
            state=json.loads(docker('inspect',name).stdout)[0]['State']
            if not state['Running']:break
            time.sleep(1)
        else:self.fail('actual application readiness deadline exceeded')
        self.assertTrue(json.loads(docker('inspect',name).stdout)[0]['State']['Running'],'serve process exited')
        import urllib.request
        with urllib.request.urlopen(base+'/',timeout=10) as response:
            self.assertEqual(response.status,200)
            self.assertIn(b'<html',response.read().lower(),'built frontend was not served')
        result=docker('exec',name,'python','-c',"""import json
from pathlib import Path
from utilities.config import settings
for name in json.loads(Path('/data/companion-inventory.json').read_text()):
 assert settings.get_local_file_path(name).read_bytes()==b'synthetic,value\\nretained,52\\n'
 signature=settings.generate_signature(name,2051222400)
 assert settings.validate_signature(name,2051222400,signature)
""",check=False)
        self.assertEqual(result.returncode,0,'actual file storage/signature companion validation failed')
        self.assertEqual(docker('exec',name,'redis-cli','ping').stdout.strip(),'PONG')
        self.assertTrue(docker('exec',name,'redis-cli','GET','task52:companion').stdout.strip()=='generated-preserved-value','Redis companion value changed')
        return name,data

    def check_keys(self,jobs):
        original=(self.root/'sqlite-baseline-v6/secrets.env').read_bytes()
        for _,data in jobs:self.assertTrue((data/'secrets.env').read_bytes()==original,'identity file bytes changed')

    def stop(self,jobs):
        for name,_ in jobs:
            docker('stop','-t','40',name)
            self.jobs.remove(name)

    def api_tests(self,jobs,label,selector,after=False):
        env={**os.environ,'WORKSPACE_APP_NAMES':','.join(name for name,_ in jobs),
             'WORKSPACE_API_LABEL':label,'WORKSPACE_AFTER_WRITES':'1' if after else '0'}
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'workspace/tests/postgres'),
            '-p','test_lifecycle.py','-k',selector,'-v'],env=env,capture_output=True,text=True)
        (self.root/(self.tag+'-'+label+'-'+selector+'.log')).write_text(result.stdout+result.stderr)
        self.assertEqual(result.returncode,0,selector+' failed; private assertion diagnostics retained')
        print(label,selector,'passed',flush=True)

    def tearDown(self):
        for name in getattr(self,'jobs',[]):docker('stop','-t','40',name,check=False)


if __name__=='__main__':unittest.main(verbosity=2)
