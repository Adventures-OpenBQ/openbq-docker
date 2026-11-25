import importlib.util
from pathlib import Path
import subprocess
import pytest

spec=importlib.util.spec_from_file_location('preflight',Path(__file__).parents[1]/'scripts/live_grid_preflight.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PIN='ghcr.io/adventures-openbq/openbq-live-grid@sha256:'+'a'*64

class Docker:
    def __init__(self,state='running',image='expected',health=None,exists=True,probe=True):
        self.calls=[];self.state=state;self.image=image;self.health=health;self.exists=exists;self.probe=probe
    def __call__(self,args):
        self.calls.append(args)
        if args[:2]==['image','inspect']:return 'expected'
        if 'ps' in args:return 'container' if self.exists else ''
        if args[0]=='inspect':
            import json
            return json.dumps([{'Image':self.image,'State':{'Status':self.state,**({'Health':{'Status':self.health}} if self.health else {})}}])
        if 'up' in args:self.exists=True;self.state='running';self.image='expected';self.health='healthy'
        if args[0]=='exec' and not self.probe:raise m.PreflightError('probe failed')
        return ''

@pytest.mark.parametrize('kwargs',[{'exists':False},{'state':'exited'},{'image':'old'},{'health':'unhealthy'}])
def test_reconciles_only_selected_compose_service(kwargs):
    d=Docker(**kwargs)
    m.ensure(d,['compose','-p','chosen'],PIN,timeout=0)
    updates=[c for c in d.calls if 'up' in c]
    assert len(updates)==1 and updates[0][-1]=='live-grid'
    assert '--no-deps' in updates[0] and '--force-recreate' in updates[0]
    assert ['pull',PIN] in d.calls

def test_ready_service_not_recreated():
    d=Docker();m.ensure(d,['compose','-p','chosen'],PIN,timeout=0)
    assert not any('up' in c for c in d.calls)
    assert any(c[0]=='exec' for c in d.calls)

@pytest.mark.parametrize('kwargs',[{'exists':False},{'state':'exited'},{'image':'old'},{'health':'unhealthy'}])
def test_check_only_refuses_stale_without_mutation(kwargs):
    d=Docker(**kwargs)
    with pytest.raises(m.PreflightError):m.ensure(d,['compose'],PIN,timeout=0,check_only=True)
    assert not any(c[0]=='pull' or 'up' in c for c in d.calls)

def test_probe_failure_blocks_deployment():
    with pytest.raises(m.PreflightError):m.ensure(Docker(probe=False),['compose'],PIN,timeout=0)

def test_newer_release_requires_its_own_pin(tmp_path):
    p=tmp_path/'pins.json';p.write_text('{"10":"'+PIN+'"}')
    assert m.release_image('9.0.0',None,p) is None
    assert m.release_image('10.0.0',None,p)==PIN
    with pytest.raises(m.PreflightError):m.release_image('12.0.0',None,p)
    assert m.release_image('12.0.0',PIN,p)==PIN
    with pytest.raises(m.PreflightError):m.release_image('10','ghcr.io/example/grid:latest',p)

def test_initializes_volume_only_when_project_defines_permission_service():
    class WithPerms(Docker):
        def __call__(self,args):
            if args[-2:]==['config','--services']:
                self.calls.append(args);return 'live-grid\nlive-grid-perms\n'
            return super().__call__(args)
    d=WithPerms(exists=False);m.ensure(d,['compose','-p','chosen'],PIN,timeout=0)
    init=next(i for i,c in enumerate(d.calls) if 'run' in c)
    up=next(i for i,c in enumerate(d.calls) if 'up' in c)
    assert init<up and d.calls[init][-1]=='live-grid-perms'


def test_v9_check_does_not_contact_docker(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('Docker should not be contacted')
    monkeypatch.setattr(m.subprocess,'run',forbidden)
    assert m.main(['--release','9.0.0','--check-only'])==0

@pytest.mark.parametrize('probe,expected_exit',[(True,0),(False,1)])
def test_deploy_runs_only_after_probe_and_keeps_override(monkeypatch,tmp_path,probe,expected_exit):
    d=Docker(probe=probe)
    def run(args,**kwargs):
        cmd=args[1:]
        if cmd[-2:]==['config','--services']:
            d.calls.append(cmd);out='live-grid\nlive-grid-perms'
        else:
            try:out=d(cmd)
            except m.PreflightError:return subprocess.CompletedProcess(args,1,'','private error text')
        return subprocess.CompletedProcess(args,0,out,'')
    monkeypatch.setattr(m.subprocess,'run',run)
    assert m.main(['--release','10','--image',PIN,'--directory',str(tmp_path),'--timeout','0','--deploy'])==expected_exit
    deployments=[i for i,c in enumerate(d.calls) if 'up' in c]
    if probe:
        assert len(deployments)==1
        assert next(i for i,c in enumerate(d.calls) if c[0]=='exec')<deployments[0]
    else:assert not deployments
    import json
    overlay=next((tmp_path/'.openbq').glob('live-grid-image-*.json'))
    assert json.loads(overlay.read_text())['services']['live-grid']['image']==PIN
    assert json.loads(overlay.read_text())['services']['live-grid-perms']['image']==PIN
    if probe:
        original=overlay.read_text()
        other=PIN.rsplit(':',1)[0]+':'+'b'*64
        assert m.main(['--release','10','--image',other,'--directory',str(tmp_path),'--project-name','another','--timeout','0'])==0
        assert overlay.read_text()==original
        assert len(list((tmp_path/'.openbq').glob('live-grid-image-*.json')))==2

@pytest.mark.parametrize('status,passes',[('ok',True),('degraded',False)])
def test_probe_reads_application_health_body(monkeypatch,status,passes):
    import io,json,urllib.request
    def urlopen(request,**kw):
        body={'status':status} if request.full_url.endswith('/health') else {'live_grid':{},'day_chart':{}}
        response=io.BytesIO(json.dumps(body).encode());response.status=200
        return response
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    if passes:exec(m.PROBE.replace('CHECK_CHART_STREAM','False'),{})
    else:
        with pytest.raises(AssertionError):exec(m.PROBE.replace('CHECK_CHART_STREAM','False'),{})


def test_probe_auth_truthy_matches_application(monkeypatch):
    import io,json,urllib.request
    monkeypatch.setenv('OPENBB_API_AUTH',' true ')
    monkeypatch.setenv('OPENBB_API_USERNAME','fixture')
    monkeypatch.setenv('OPENBB_API_PASSWORD','fixture')
    def urlopen(request,**kw):
        assert request.get_header('Authorization')=='Basic Zml4dHVyZTpmaXh0dXJl'
        body={'status':'ok'} if request.full_url.endswith('/health') else {'live_grid':{},'day_chart':{}}
        r=io.BytesIO(json.dumps(body).encode());r.status=200;return r
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    exec(m.PROBE.replace('CHECK_CHART_STREAM','False'),{})
