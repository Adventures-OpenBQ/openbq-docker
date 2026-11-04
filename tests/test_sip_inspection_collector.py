# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
from hashlib import sha256
import json
import pytest


def implementation():
    path=Path(__file__).resolve().parents[1]/'v11/sip/collector.py'
    spec=importlib.util.spec_from_file_location('sip_collector',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def source(module,monkeypatch):
    payload=b'bounded source file bytes'
    monkeypatch.setitem(module.PROFILE,'sample_limit',1)
    uri='s3://openbb-delta/ticks_sip/AAPL/day=2025-01-21/part.parquet'
    monkeypatch.setitem(module.PROFILE,'active_manifest_sha256',sha256(json.dumps([uri],separators=(',',':')).encode()).hexdigest())
    monkeypatch.setitem(module.PROFILE,'source_file_sha256',sha256(payload).hexdigest())
    monkeypatch.setitem(module.PROFILE,'source_file_bytes',len(payload))
    seen=[]
    fs=SimpleNamespace(get_file_info=lambda path:SimpleNamespace(size=len(payload),mtime_ns=1),open_input_file=lambda path:BytesIO(payload))
    fragment=SimpleNamespace(path='ticks_sip/AAPL/day=2025-01-21/part.parquet',filesystem=fs,count_rows=lambda:100)
    sample=SimpleNamespace(schema=SimpleNamespace(field=lambda name:SimpleNamespace(type='timestamp[us]')),to_pylist=lambda:[{'date':__import__('datetime').datetime(2025,1,21,9),'price':-1.25,'size':1,'seq':9223372036854775807,'mkt':'Q','sub_mkt':None,'sl':'@','day':'2025-01-21'}])
    dataset=SimpleNamespace(get_fragments=lambda:[fragment],head=lambda limit,columns:(seen.append((limit,columns)) or sample))
    table=SimpleNamespace(version=lambda:1000,file_uris=lambda:[uri],to_pyarrow_dataset=lambda partitions:(seen.append(partitions) or dataset))
    def factory(uri,version,storage_options):seen.append((uri,version));return table
    return factory,table,seen


def test_reads_exact_selected_version_active_file_and_preserves_values(monkeypatch):
    module=implementation();factory,table,seen=source(module,monkeypatch)
    result=module.inspect_source({},table_factory=factory)
    assert seen[0]==('s3://openbb-delta/ticks_sip/AAPL',1000)
    assert result['rows'][0]['seq']=='9223372036854775807'
    assert result['rows'][0]['price_f64hex']==(-1.25).hex()
    assert result['rows'][0]['date']=='2025-01-21T09:00:00.000000'
    assert result['source_file_sha256']==module.PROFILE['source_file_sha256']
    assert result['sample_rows']==1 and result['metadata_rows']==100


@pytest.mark.parametrize('change',['version','active_manifest','file_hash','size'])
def test_refuses_changed_or_unbounded_sources(monkeypatch,change):
    module=implementation();factory,table,seen=source(module,monkeypatch)
    if change=='version':table.version=lambda:1001
    if change=='active_manifest':table.file_uris=lambda:[]
    if change=='file_hash':monkeypatch.setitem(module.PROFILE,'source_file_sha256','a'*64)
    if change=='size':monkeypatch.setitem(module.PROFILE,'source_file_bytes',65*1024*1024)
    with pytest.raises(ValueError):module.inspect_source({},table_factory=factory)


def test_operator_origin_is_fixed_and_tls_is_required():
    module=implementation()
    with pytest.raises(ValueError):module.storage_options({'DELTA_S3_ENDPOINT':'arbitrary.example','DELTA_S3_SECURE':'true'})


def test_packing_retains_corroboration_bytes_and_refuses_secret_parameters(monkeypatch):
    module=implementation();factory,_,_=source(module,monkeypatch)
    observation=module.inspect_source({},table_factory=factory)
    raw=b'{"mkt":[],"price":[],"seq":[],"shares":[],"sl":[],"sub_mkt":[],"ts":[]}'
    receipt={'endpoint':'ticks','parameters':{'s':'AAPL.US','from':1737450000,'to':1737450193,'fmt':'json'},'status':200,
      'received_at':'2026-11-04T05:19:46Z','body_sha256':sha256(raw).hexdigest(),'bytes':len(raw)}
    packed=module.pack_snapshot(observation,raw,receipt)
    assert __import__('base64').b64decode(packed['corroboration']['body_base64'])==raw
    assert packed['inspection_only'] is True and packed['canonical_tick_eligible'] is False
    receipt['parameters']['api_token']='not-a-real-secret'
    with pytest.raises(ValueError):module.pack_snapshot(observation,raw,receipt)


def test_short_sample_read_cannot_claim_the_requested_sample(monkeypatch):
    module=implementation();factory,_,_=source(module,monkeypatch)
    monkeypatch.setitem(module.PROFILE,'sample_limit',2)
    with pytest.raises(ValueError):module.inspect_source({},table_factory=factory)


def test_arrow_table_relative_fragment_is_bound_to_the_selected_active_object(monkeypatch):
    module=implementation();factory,table,_=source(module,monkeypatch)
    fragment=table.to_pyarrow_dataset(partitions=[]).get_fragments()[0]
    fragment.path='day=2025-01-21/part.parquet'
    assert module.inspect_source({},table_factory=factory)['source_file_path']=='ticks_sip/AAPL/day=2025-01-21/part.parquet'
    fragment.path='../other/part.parquet'
    with pytest.raises(ValueError):module.inspect_source({},table_factory=factory)


@pytest.mark.parametrize('dtype',['timestamp[ns]','timestamp[us, tz=UTC]'])
def test_source_timestamp_schema_cannot_be_relabelled_as_naive_microseconds(monkeypatch,dtype):
    module=implementation();factory,table,_=source(module,monkeypatch)
    sample=table.to_pyarrow_dataset(partitions=[]).head(1,[])
    sample.schema=SimpleNamespace(field=lambda name:SimpleNamespace(type=dtype))
    with pytest.raises(ValueError):module.inspect_source({},table_factory=factory)
