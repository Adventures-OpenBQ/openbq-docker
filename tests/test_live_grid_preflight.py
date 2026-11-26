import importlib.util
from pathlib import Path
import subprocess
import pytest

spec=importlib.util.spec_from_file_location('preflight',Path(__file__).parents[1]/'scripts/live_grid_preflight.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
@pytest.fixture(autouse=True)
def no_operator_auth_environment(monkeypatch):
    for name in ['OPENBB_API_AUTH','OPENBB_API_USERNAME','OPENBB_API_PASSWORD']:
        monkeypatch.delenv(name, raising=False)

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
            return json.dumps({'Image':self.image,'State':{'Status':self.state,**({'Health':{'Status':self.health}} if self.health else {})}})
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

LOCAL='sha256:'+'c'*64

def test_explicit_immutable_local_image_id_is_accepted(tmp_path):
    p=tmp_path/'pins.json';p.write_text('{}')
    assert m.release_image('10.0.0',LOCAL,p)==LOCAL

def test_local_image_is_never_pulled():
    class Local(Docker):
        def __call__(self,args):
            if args[:2]==['image','inspect']:
                self.calls.append(args);return LOCAL
            return super().__call__(args)
    d=Local(image=LOCAL);m.ensure(d,['compose'],LOCAL,timeout=0)
    assert not any(c[0]=='pull' for c in d.calls)

def test_local_inspect_must_match_the_explicit_id():
    with pytest.raises(m.PreflightError):m.ensure(Docker(),['compose'],LOCAL,timeout=0)

def test_no_foreign_release_candidate_is_a_shipping_default():
    import json
    pins=json.loads((Path(__file__).parents[1]/'live-grid/runtime-images.json').read_text())
    assert '10' not in pins
    with pytest.raises(m.PreflightError,match='--image'):
        m.release_image('10.0.0',None)

@pytest.mark.parametrize('value',['nan','inf','-inf'])
def test_nonfinite_timeout_is_rejected_before_docker(monkeypatch,value):
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:pytest.fail('Docker contacted'))
    with pytest.raises(SystemExit):m.main(['--release','10','--image',LOCAL,'--timeout='+value])

def test_deploy_carries_selected_profiles_and_never_pulls_local_image(monkeypatch,tmp_path):
    d=Docker(image=LOCAL)
    def run(args,**kwargs):
        cmd=args[1:]
        if cmd[:2]==['image','inspect']:d.calls.append(cmd);out=LOCAL
        elif cmd[-2:]==['config','--services']:d.calls.append(cmd);out='live-grid\nlive-grid-perms\n'
        else:
            out=d(cmd)
            if 'up' in cmd:d.image=LOCAL
        return subprocess.CompletedProcess(args,0,out,'')
    monkeypatch.setattr(m.subprocess,'run',run)
    assert m.main(['--release','10','--image',LOCAL,'--directory',str(tmp_path),'--profile','web','--deploy','--timeout','0'])==0
    deploy=next(c for c in d.calls if 'up' in c)
    assert '--profile' in deploy and deploy[deploy.index('--profile')+1]=='web'
    assert 'live' in deploy and deploy[-2:]==['--pull','never']
    assert not any(c[0]=='pull' for c in d.calls)

def test_public_reader_entry_builds_local_and_uses_deploy_wrapper():
    root=Path(__file__).parents[1]
    text=(root/'docs/v10/live-grid-preflight.md').read_text()
    assert 'docker image inspect openbq-live-grid:10.0.0' in text
    assert '--image "$LIVE_GRID_IMAGE_ID"' in text and '--deploy' in text
    assert 'cb474b' not in text and 'Services/' not in text
    assert '64 GB Mac' not in text and 'current qualified v10 candidate' not in text
    assert '--deploy' in (root/'README.md').read_text()
    assert '--deploy' in (root/'docs/v10/chart-stream-deployment.md').read_text()

@pytest.mark.parametrize('setting',['',' true ','1','yes','ON','false'])
def test_probe_auth_toggle_matches_actual_application_module(monkeypatch,setting):
    import io,json,urllib.request
    auth_spec=importlib.util.spec_from_file_location('current_grid_auth',Path(__file__).parents[1]/'live-grid/app/auth.py')
    auth=importlib.util.module_from_spec(auth_spec);auth_spec.loader.exec_module(auth)
    monkeypatch.setenv('OPENBB_API_AUTH',setting)
    monkeypatch.setenv('OPENBB_API_USERNAME','fixture')
    monkeypatch.setenv('OPENBB_API_PASSWORD','fixture')
    seen=[]
    def urlopen(request,**kwargs):
        assert kwargs['timeout']==5
        supplied=request.get_header('Authorization')
        assert bool(supplied)==auth.auth_enabled()
        if supplied:assert auth.credentials_ok(supplied)
        seen.append(request.full_url)
        body={'status':'ok'} if request.full_url.endswith('/health') else {'live_grid':{},'day_chart':{}}
        response=io.BytesIO(json.dumps(body).encode());response.status=200;return response
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    exec(m.PROBE.replace('CHECK_CHART_STREAM','False'),{})
    assert seen==['http://127.0.0.1:6903/health','http://127.0.0.1:6903/widgets.json']

@pytest.mark.parametrize('capability',[True,False,1,None])
def test_accepted_stream_probe_requires_true_capability(monkeypatch,capability):
    import io,json,urllib.request
    def urlopen(request,**kwargs):
        body={'status':'ok'} if request.full_url.endswith('/health') else {'live_grid':{},'day_chart':{},'live_chart':{'extra_metadata':{'chart_stream_v1':capability}}}
        response=io.BytesIO(json.dumps(body).encode());response.status=200;return response
    monkeypatch.setattr(urllib.request,'urlopen',urlopen)
    if capability is True:exec(m.PROBE.replace('CHECK_CHART_STREAM','True'),{})
    else:
        with pytest.raises(AssertionError):exec(m.PROBE.replace('CHECK_CHART_STREAM','True'),{})

def test_missing_local_image_never_falls_back_to_pull():
    calls=[]
    def unavailable(args):
        calls.append(args);raise m.PreflightError('unavailable')
    with pytest.raises(m.PreflightError):m.ensure(unavailable,['compose'],LOCAL,timeout=0)
    assert calls==[['image','inspect',LOCAL,'--format','{{.Id}}']]

def test_inspection_requests_only_image_and_health_state():
    d=Docker();m.ensure(d,['compose'],PIN,timeout=0,check_only=True)
    inspections=[c for c in d.calls if c[0]=='inspect']
    assert inspections and all('--format' in c for c in inspections)
    for call in inspections:
        template=call[call.index('--format')+1]
        assert '.Image' in template and '.State.Status' in template
        assert '.State.Health.Status' in template and '.Config' not in template
        assert '.Health.Log' not in template

def test_private_docker_diagnostics_are_never_printed(monkeypatch,tmp_path,capsys):
    diagnostic='opaque upstream diagnostic must stay private'
    monkeypatch.setattr(m.subprocess,'run',lambda args,**kwargs:subprocess.CompletedProcess(args,1,'',diagnostic))
    assert m.main(['--release','10','--image',LOCAL,'--directory',str(tmp_path)])==1
    output=capsys.readouterr()
    assert diagnostic not in output.out+output.err

@pytest.mark.parametrize('kwargs',[{'exists':False},{'state':'exited'},{'image':'old'},{'health':'unhealthy'}])
def test_local_stale_service_reconciles_without_registry_pull(kwargs):
    class Local(Docker):
        def __call__(self,args):
            if args[:2]==['image','inspect']:
                self.calls.append(args);return LOCAL
            result=super().__call__(args)
            if 'up' in args:self.image=LOCAL
            return result
    d=Local(**kwargs);m.ensure(d,['compose','-p','chosen'],LOCAL,timeout=0)
    assert not any(c[0]=='pull' for c in d.calls)
    up=next(c for c in d.calls if 'up' in c)
    assert up[-1]=='live-grid' and '--no-deps' in up and '--pull' in up and 'never' in up
