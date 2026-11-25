import importlib.util
from pathlib import Path
import yaml

def test_canonical_missing_rustfs_bind_is_explicit_owned_directory(tmp_path):
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('runner',root/'scripts/compose-run.py'); runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    recipe=yaml.safe_load((root/'docker-compose.yml').read_text())
    mounts=[]
    for name in ('rustfs-perms','rustfs'):
        assert recipe['services'][name]['x-openbq-regression-state-directories']==['/data']
        mount=recipe['services'][name]['volumes'][0]
        assert isinstance(mount,dict) and mount['type']=='bind'
        assert mount['bind']['create_host_path'] is True
        mounts.append(dict(mount,source=str(tmp_path/'absent')))
    model={'services':{'init':{'image':'fixture','x-openbq-regression-state-directories':['/data'],'volumes':[mounts[0]]},'store':{'image':'fixture','x-openbq-regression-state-directories':['/data'],'volumes':[mounts[1]]}},'volumes':{}}
    actual=runner.prepare_model(model,['init','store'],'openbq-regression-reviewfix')
    assert actual['services']['init']['volumes'][0]['source']==actual['services']['store']['volumes'][0]['source']
    assert not (tmp_path/'absent').exists()


def test_normalized_create_host_path_does_not_admit_an_ambiguous_missing_bind(tmp_path):
    import pytest
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('runner',root/'scripts/compose-run.py'); runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    model={'services':{'app':{'image':'fixture','volumes':[{'type':'bind','source':str(tmp_path/'missing'),'target':'/maybe-file','bind':{'create_host_path':True}}]}},'volumes':{}}
    with pytest.raises(ValueError,match='missing bind'):runner.prepare_model(model,['app'],'openbq-regression-reviewfix')


def test_fresh_actual_eod_dependency_closure_reaches_owned_volume_initializer(tmp_path):
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('runner',root/'scripts/compose-run.py'); runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    model=yaml.safe_load((root/'docker-compose.yml').read_text())
    model['volumes']={k:v or {} for k,v in model.get('volumes',{}).items()}
    selected,_=runner.runtime_services(model,['eod-dump'])
    for name in selected:
        service=model['services'][name]
        if isinstance(service.get('networks'),list):service['networks']={n:{} for n in service['networks']}
        if name=='openbq-kdb':service['image']='openbq-kdb-local:10.0.0'
        mounts=[]
        for raw in service.get('volumes',[]):
            if isinstance(raw,dict):
                mount=dict(raw);mount['source']=str(tmp_path/'rustfs-data');mounts.append(mount);continue
            raw=raw.replace('${KDB_LICENSE_DIR:-./kdb-license}',str(root/'kdb-license'))
            source,target,*options=raw.split(':')
            if source.startswith('.'):source=str(root/source)
            mounts.append({'type':'bind' if source.startswith('/') else 'volume','source':source,'target':target,'read_only':'ro' in options})
        service['volumes']=mounts
    actual=runner.prepare_model(model,['eod-dump'],'openbq-regression-freshlake')
    assert {'eod-dump','rustfs','rustfs-init','rustfs-perms','openbq-kdb'}<=actual['services'].keys()
    assert actual['services']['rustfs']['volumes'][0]['type']=='volume'
    assert actual['services']['rustfs']['volumes'][0]['source']==actual['services']['rustfs-perms']['volumes'][0]['source']
    assert not (tmp_path/'rustfs-data').exists()
