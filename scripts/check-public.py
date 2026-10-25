#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Fail closed on private deployment details; never print matched values.

Inspired by BDOBB's scrub gate. Machine patterns live in the ignored
scripts/scrub-private-patterns.txt. Generic example deployment paths are
permitted; real hostnames, addresses, credentials and user home paths are not.
"""
import argparse,json,re,subprocess,sys
from pathlib import Path

def git(*args):
 return subprocess.check_output(['git',*args])

def reviewed_history_findings():
 """Exact, reviewed historical findings only; current and index scans never use these."""
 manifest=Path('scripts/public-history-findings.json')
 if not manifest.exists():return {}
 data=json.loads(manifest.read_text())
 if not isinstance(data,dict) or set(data)!={'version','findings'} or type(data['version']) is not int or data['version']!=1 or not isinstance(data['findings'],list):
  raise ValueError('Invalid historical finding manifest')
 reasons={'synthetic-network':{'private address'},
          'synthetic-test-fixture':{'tailnet host','filled JSON credential'},
          'published-provider-demo-key':{'filled JSON credential'}}
 reviewed={};seen=set()
 for entry in data['findings']:
  if not isinstance(entry,dict) or set(entry)!={'blob_oid','path','kind','reason'} or not all(isinstance(v,str) for v in entry.values()):
   raise ValueError('Invalid historical finding entry')
  oid,path,kind,reason=(entry[k] for k in ('blob_oid','path','kind','reason'))
  if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})',oid) or not path or path.startswith('/') or any(part in ('','.','..') for part in path.split('/')) or any(ord(c)<32 for c in path) or kind not in reasons.get(reason,set()):
   raise ValueError('Invalid historical finding entry')
  key=(oid,path,kind)
  if key in seen:raise ValueError('Duplicate historical finding entry')
  seen.add(key);reviewed.setdefault((oid,path),set()).add(kind)
 return reviewed

def history_objects(history):
 """Keep every historical blob/path occurrence, including aliases and merges.

 rev-list names only one arbitrary path per OID. Raw commit diffs preserve
 actual paths; the OID-only fallback also retains standalone tagged blobs.
 """
 pairs=set()
 records=git('log','--raw','--root','-m','--no-renames','--no-abbrev','--format=','-z',*history).split(b'\0')
 index=0
 while index<len(records):
  header=records[index].lstrip(b'\n');index+=1
  if not header:continue
  fields=header.split()
  if len(fields)!=5 or not fields[0].startswith(b':') or index>=len(records):
   raise ValueError('Invalid historical object record')
  oid=fields[3].decode('ascii');path=records[index].decode('utf-8');index+=1
  if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})',oid) or not path:
   raise ValueError('Invalid historical object record')
  # Gitlinks identify external commits, not repository blobs.
  if set(oid)!={'0'} and fields[1]!=b'160000':pairs.add((oid,path))
 named={oid for oid,_ in pairs}
 for oid in git('rev-list','--objects','--no-object-names',*history).decode().splitlines():
  if oid not in named:pairs.add((oid,''))
 return sorted(pairs)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--history',nargs='*',metavar='REV',help='also scan history reachable from REVs (default: all refs)');args=parser.parse_args()
 patterns=[
  ('tailscale key',r'tskey-[A-Za-z0-9-]{10,}'),
  ('GitHub token',r'gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}'),
  ('private key',r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
  ('tailnet host',r'(?i)(?:[a-z0-9-]+\.)+[a-z0-9-]+\.ts\.net\b'),
  # 100.100.100.100 is Tailscale's fixed MagicDNS resolver on every tailnet (rita-resolv.conf), not a deployment detail.
  # 100.64.0.0 is the base of the tailnet CGNAT block (100.64.0.0/10, key-maint's tier check), never a host address.
  ('private address',r'\b(?!100\.100\.100\.100\b)(?!100\.64\.0\.0\b)(?:100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])|192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'),
  # Tailscale ULA addresses; the trailing hex digit keeps the bare prefix (a CIDR in docs) from matching.
  ('tailnet IPv6',r'(?i)\bfd7a:115c:a1e0:[0-9a-f:]*[0-9a-f]\b'),
  ('local home',r'/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/'),
  ('cloud key',r'AKIA[0-9A-Z]{16}'),
  ('tailnet node ID',r'\bn[A-Za-z0-9]{10,}CNTRL\b'),
 ]
 private=Path('scripts/scrub-private-patterns.txt')
 if not private.exists():
  common=Path(git('rev-parse','--git-common-dir').decode().strip()).resolve()
  private=common.parent/'scripts/scrub-private-patterns.txt'
 if private.exists():
  for line in private.read_text().splitlines():
   if line.strip() and not line.startswith('#'):patterns.append(('local private pattern',line))
 # Public demo keys the providers publish (credentials.demo.env, docs/credentials-demo-receipt.md): allowed by exact name and value.
 public_demo={('EIA_API_KEY','DEMO_KEY'),('CONGRESS_GOV_API_KEY','DEMO_KEY'),('EODHD_API_KEY','demo')}
 compiled=[(name,re.compile(pattern)) for name,pattern in patterns]
 reviewed=reviewed_history_findings()
 findings=[]
 def filled(name,value):
  return (name,value) not in public_demo and bool(value) and not value.startswith(('$','<')) and not re.fullmatch(r'(?:YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|PLACEHOLDER|CHANGE_ME|CHANGEME)',value)
 def scan(label,data,ignored=frozenset()):
  def add(kind):
   if kind not in ignored:findings.append((label,kind))
  text=data.decode('utf-8',errors='replace')
  text=text.replace('YOUR-TAILNET.ts.net','PLACEHOLDER').replace('YOUR_TAILNET.ts.net','PLACEHOLDER')
  for name,pattern in compiled:
   if pattern.search(text):add(name)
  for match in re.finditer(r'(?m)^[ \t]*([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET|ACCESS_KEY_ID))[ \t]*=[ \t]*(.*)$',text):
   if filled(match.group(1),match.group(2).strip().strip('"').strip("'")):add('filled credential assignment')
  for match in re.finditer(r'(?i)"([a-z0-9_]*(?:api_key|token|password|secret|access_key_id))"[ \t\r\n]*:[ \t\r\n]*"([^"\n]*)"',text):
   if filled(match.group(1).upper(),match.group(2).strip()):add('filled JSON credential')
 files=git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
 for name in sorted(set(filter(None,files))):
  p=Path(name)
  if p.is_symlink():raise RuntimeError('Refusing symlink: '+name)
  if p.is_file():scan(name,p.read_bytes())
  if '.env' in p.name and not p.name.endswith('.env.example') and name!='credentials.demo.env':findings.append((name,'runtime env file'))
 # The hook must scan staged blobs as well as working files.
 for item in git('ls-files','--stage','-z').decode().split('\0'):
  if not item:continue
  meta,name=item.split('\t',1);oid=meta.split()[1]
  scan('index:'+name,git('cat-file','blob',oid))
 if args.history is not None:
  for oid,name in history_objects(args.history or ['--all']):
   kind=git('cat-file','-t',oid).decode().strip()
   if kind=='blob':
    scan('history:'+name,git('cat-file','blob',oid),reviewed.get((oid,name),frozenset()))
    if Path(name).name=='.DS_Store':findings.append(('history:'+name,'machine metadata'))
 for label,name in sorted(set(findings)):print('FAIL:',label,'—',name)
 if findings:return 1
 print('PASS: public-content scan'+(' including reachable history' if args.history is not None else ''))
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:
  print('FAIL: public-content scan could not complete ('+type(e).__name__+')',file=sys.stderr);sys.exit(2)
