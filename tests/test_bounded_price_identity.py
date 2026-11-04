# SPDX-License-Identifier: Apache-2.0
"""Contract fixtures use real identifiers; no synthetic market prices."""
import importlib.util
import json
from hashlib import sha256
from pathlib import Path
import pytest

ISSUER='889177af-a7b8-5ecc-b28a-709f38056d7f'
LISTING='b26c051d-9380-5edb-9496-abce1acc0376'
SECURITY='0ded9da3-748c-5505-9d4e-299bc74575be'
PROJECTION='security-master-projection/1:admission-floor-1:276020d132c6d2b856cafe6b4bda00b8ab9eae8d011ad8df6b997897565e269b:2026-11-03T21:54:38.454117Z'


def implementation():
    path=Path(__file__).resolve().parents[1]/'v11/price-identity/block_xyz.py'
    spec=importlib.util.spec_from_file_location('bounded_price_identity',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def inputs():
    body={
      'general':json.dumps({'Code':'XYZ','Exchange':'NYSE','CurrencyCode':'USD','CIK':'0001512673'}).encode(),
      'rename':json.dumps([{'exchange':'US','old_symbol':'SQ','new_symbol':'XYZ','effective':'2025-01-21'}]).encode(),
      'announcement':b'<p>NYSE SQ XYZ January 21, 2025 CUSIP unchanged</p>',
      'security_master':json.dumps({'results':[{'symbol':'XYZ','listing_id':LISTING,'issuer_id':ISSUER,'security_id':SECURITY}],
       'extra':{'security_master_receipt':{'temporal_mode':'current_corrected','availability_policy':'local_as_ingested',
       'effective_at':None,'known_at':None,'projection_version':PROJECTION}}}).encode()}
    manifest={'schema_version':1,'identity_basis':'provisional_provider_symbol','issuer_cik':'0001512673',
      'business_history_qualified':False,'index_membership_qualified':False,'security_master_projection':PROJECTION,
      'mappings':[{'symbol':'XYZ.US','listing_id':LISTING,'issuer_id':ISSUER,'start':'2025-01-21','end':'2025-01-22'}],
      'sources':{name:{'filename':name+'.json','sha256':sha256(raw).hexdigest()} for name,raw in body.items()}}
    return manifest,body


def test_exact_sources_export_only_bounded_existing_map_and_provenance():
    module=implementation();manifest,bodies=inputs();result=module.validate_example(manifest,bodies)
    assert result['mappings']==manifest['mappings']
    expected=sha256(json.dumps(manifest['mappings'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert result['identity_map_sha256']==expected
    assert result['business_history_qualified'] is False
    assert result['identity_basis']=='provisional_provider_symbol'
    assert manifest==inputs()[0]  # no source/master mutation


@pytest.mark.parametrize('change',['bytes','cik','venue','rename_day','rename_ambiguity','wider_window','authoritative','history','foreign_listing','source_projection'])
def test_unqualified_or_expanded_identity_is_refused(change):
    module=implementation();manifest,bodies=inputs()
    if change=='bytes':bodies['general']+=b' '
    if change in {'cik','venue'}:
        value=json.loads(bodies['general']);value['CIK' if change=='cik' else 'Exchange']='0000320193' if change=='cik' else 'ASX'
        bodies['general']=json.dumps(value).encode();manifest['sources']['general']['sha256']=sha256(bodies['general']).hexdigest()
    if change in {'rename_day','rename_ambiguity'}:
        value=json.loads(bodies['rename'])
        if change=='rename_day':value[0]['effective']='2025-01-22'
        else:value.append(value[0])
        bodies['rename']=json.dumps(value).encode();manifest['sources']['rename']['sha256']=sha256(bodies['rename']).hexdigest()
    if change=='wider_window':manifest['mappings'][0]['end']='2025-02-01'
    if change=='authoritative':manifest['identity_basis']='authoritative'
    if change=='history':manifest['business_history_qualified']=True
    if change=='foreign_listing':manifest['mappings'][0]['listing_id']='11111111-1111-4111-8111-111111111111'
    if change=='source_projection':manifest['security_master_projection']='unqualified'
    with pytest.raises(ValueError):module.validate_example(manifest,bodies)
