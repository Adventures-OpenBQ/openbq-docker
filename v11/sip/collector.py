# SPDX-License-Identifier: Apache-2.0
"""Fixed, read-only v11 SIP inspection collector. Never repairs the source archive."""
import argparse
import base64
from datetime import datetime,timezone
from hashlib import sha256
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

PROFILE={
 'archive_id':'legacy-sip-minio-zfs29','symbol':'AAPL','delta_version':1000,'partition_day':'2025-01-21','sample_limit':2048,
 'active_manifest_sha256':'758a0477679796fe63f6109d1d2c50a2bfa7444457cbdad19dabc5286b31084d',
 'source_file_sha256':'52d1a1bdbf6b1e1a306c7faf02a7596eebee7b0732f12283bb445f64f6e8ed6d','source_file_bytes':8310513,
 'reader_image_id':'sha256:32df9ce0c0b1c69a53c91e4ddeebd48009e0e96d51bd988c585a3c7cdd72cd30',
 'writer_image_id':'sha256:7f576b390437a41d4086d32c2a8b8391a76fd60152ef46d87444dde2742eabd0',
 'writer_code_sha256':'c42a4e6e5561cc197bd9179d902d685437f505ae19a14a2f264f65aa228538fa',
 'origin_sha256':'454b004a44dbf2e500da86ab50ce7c741d8cac03ff5ce5b7d5251ac85f497110'}
COLUMNS=['date','price','size','seq','mkt','sub_mkt','sl','day']
MAX_FILE_BYTES=64*1024*1024
MAX_SNAPSHOT_BYTES=1024*1024


def require(ok):
    if not ok:raise ValueError('unqualified or unbounded SIP inspection source')


def storage_options(env):
    host=env.get('DELTA_S3_ENDPOINT','').strip();port=env.get('DELTA_S3_PORT','').strip()
    origin='https://'+host+':'+port
    require(env.get('DELTA_S3_SECURE','').strip().lower()=='true' and
        sha256(origin.encode()).hexdigest()==PROFILE['origin_sha256'] and
        env.get('DELTA_S3_BUCKET','').strip()=='openbb-delta')
    access=env.get('DELTA_S3_ACCESS','').strip();secret=env.get('DELTA_S3_SECRET','').strip()
    require(bool(access and secret))
    return {'aws_endpoint':origin,'aws_access_key_id':access,'aws_secret_access_key':secret,
        'aws_region':'us-east-1','aws_virtual_hosted_style_request':'false','aws_connect_timeout':'5s','aws_timeout':'30s'}


def inspect_source(options,*,table_factory=None):
    if table_factory is None:
        from deltalake import DeltaTable
        table_factory=DeltaTable
    uri='s3://openbb-delta/ticks_sip/'+PROFILE['symbol']
    table=table_factory(uri,version=PROFILE['delta_version'],storage_options=options)
    require(table.version()==PROFILE['delta_version'])
    files=sorted(table.file_uris());require(0<len(files)<=10000)
    require(sha256(json.dumps(files,separators=(',',':')).encode()).hexdigest()==PROFILE['active_manifest_sha256'])
    selected=[path for path in files if '/day='+PROFILE['partition_day']+'/' in path]
    require(len(selected)==1)
    dataset=table.to_pyarrow_dataset(partitions=[('day','=',PROFILE['partition_day'])])
    fragments=list(dataset.get_fragments());require(len(fragments)==1)
    fragment=fragments[0]
    object_path=urlsplit(selected[0]).path.lstrip('/')
    require(fragment.path in {object_path,'openbb-delta/'+object_path,object_path.removeprefix('ticks_sip/'+PROFILE['symbol']+'/')})
    info=fragment.filesystem.get_file_info(fragment.path)
    require(info.size==PROFILE['source_file_bytes'] and 0<info.size<=MAX_FILE_BYTES)
    digest=sha256();count=0
    with fragment.filesystem.open_input_file(fragment.path) as stream:
        while True:
            chunk=stream.read(1024*1024)
            if not chunk:break
            count+=len(chunk);require(count<=MAX_FILE_BYTES);digest.update(chunk)
    require(count==info.size and digest.hexdigest()==PROFILE['source_file_sha256'])
    sample=dataset.head(PROFILE['sample_limit'],columns=COLUMNS)
    require(str(sample.schema.field('date').type)=='timestamp[us]')
    original=sample.to_pylist();metadata_rows=fragment.count_rows()
    require(0<PROFILE['sample_limit']<=4096 and len(original)==min(PROFILE['sample_limit'],metadata_rows))
    after=fragment.filesystem.get_file_info(fragment.path)
    require(after.size==info.size and after.mtime_ns==info.mtime_ns)
    rows=[]
    for position,row in enumerate(original):
        stamp=row['date'];price=row['price']
        require(isinstance(stamp,datetime) and stamp.tzinfo is None and type(price) is float and math.isfinite(price))
        require(row['day']==PROFILE['partition_day'])
        rows.append({'position':position,'date':stamp.isoformat(timespec='microseconds'),'price_f64hex':price.hex(),
            'size':None if row['size'] is None else str(row['size']),'seq':str(row['seq']),
            'mkt':row['mkt'],'sub_mkt':row['sub_mkt'],'sl':row['sl'],'day':row['day']})
    return {'archive_id':PROFILE['archive_id'],'symbol':PROFILE['symbol'],'delta_version':table.version(),
        'partition_day':PROFILE['partition_day'],'active_manifest_sha256':PROFILE['active_manifest_sha256'],
        'source_file_path':object_path,'source_file_bytes':count,'source_file_sha256':digest.hexdigest(),
        'metadata_rows':metadata_rows,'sample_offset':0,'sample_limit':PROFILE['sample_limit'],'sample_rows':len(rows),
        'source_timestamp_type':'timestamp[us]','source_timestamp_timezone':None,
        'source_inspected_at':datetime.now(timezone.utc).isoformat(),'rows':rows}


def pack_snapshot(observation,raw,receipt):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_SNAPSHOT_BYTES)
    require(receipt.get('endpoint')=='ticks' and receipt.get('status')==200 and
        receipt.get('body_sha256')==sha256(raw).hexdigest() and receipt.get('bytes')==len(raw))
    params=receipt.get('parameters',{})
    require(set(params)=={'s','from','to','fmt'} and params['s']=='AAPL.US' and params['fmt']=='json' and
        type(params['from']) is int and type(params['to']) is int and 0<=params['to']-params['from']<300)
    value=json.loads(raw);require(set(value)=={'mkt','price','seq','shares','sl','sub_mkt','ts'})
    require(all(isinstance(column,list) for column in value.values()))
    snapshot={'schema_version':1,'kind':'legacy_sip_inspection','inspection_only':True,'canonical_tick_eligible':False,
        'enterprise_identity_qualified':False,'comparison_policy':'exact_full_trade_tuple_v1',
        'collector_code_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'reader_image_id':PROFILE['reader_image_id'],'writer_evidence':{key:PROFILE[key] for key in ('writer_image_id','writer_code_sha256')},
        'source':observation,'corroboration':{'provider':'eodhd','endpoint':'ticks','parameters':params,
            'http_status':200,'received_at':receipt['received_at'],'body_sha256':sha256(raw).hexdigest(),
            'body_base64':base64.b64encode(raw).decode(),'boundary':'operator_retained_complete_json_value',
            'wire_framing_certified':False,'complete_provider_window_claimed':False}}
    encoded=json.dumps(snapshot,separators=(',',':'),allow_nan=False).encode()
    require(len(encoded)<=MAX_SNAPSHOT_BYTES)
    return snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corroboration',required=True,type=Path)
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args()
    require(args.corroboration.stat().st_size<=MAX_SNAPSHOT_BYTES and args.receipt.stat().st_size<=16384)
    snapshot=pack_snapshot(inspect_source(storage_options(os.environ)),args.corroboration.read_bytes(),json.loads(args.receipt.read_text()))
    snapshot['reader_packages']={name:version(name) for name in ('deltalake','pyarrow')}
    encoded=json.dumps(snapshot,separators=(',',':'),allow_nan=False)
    require(len(encoded.encode())<=MAX_SNAPSHOT_BYTES)
    print(encoded)


if __name__=='__main__':main()
