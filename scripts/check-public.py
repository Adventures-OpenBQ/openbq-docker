#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Fail closed on private deployment details; never print matched values.

Inspired by BDOBB's scrub gate. Machine patterns live in the ignored
scripts/scrub-private-patterns.txt. Generic example deployment paths are
permitted; real hostnames, addresses, credentials and user home paths are not.
"""
import argparse,re,subprocess,sys
from pathlib import Path

def git(*args):
 return subprocess.check_output(['git',*args])

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
 findings=[]
 def filled(name,value):
  return (name,value) not in public_demo and bool(value) and not value.startswith(('$','<')) and not re.fullmatch(r'(?:YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|PLACEHOLDER|CHANGE_ME|CHANGEME)',value)
 def scan(label,data):
  text=data.decode('utf-8',errors='replace')
  text=text.replace('YOUR-TAILNET.ts.net','PLACEHOLDER').replace('YOUR_TAILNET.ts.net','PLACEHOLDER')
  for name,pattern in compiled:
   if pattern.search(text):findings.append((label,name))
  for match in re.finditer(r'(?m)^[ \t]*([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET|ACCESS_KEY_ID))[ \t]*=[ \t]*(.*)$',text):
   if filled(match.group(1),match.group(2).strip().strip('"').strip("'")):findings.append((label,'filled credential assignment'))
  for match in re.finditer(r'(?i)"([a-z0-9_]*(?:api_key|token|password|secret|access_key_id))"[ \t\r\n]*:[ \t\r\n]*"([^"\n]*)"',text):
   if filled(match.group(1).upper(),match.group(2).strip()):findings.append((label,'filled JSON credential'))
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
  objects=git('rev-list','--objects',*(args.history or ['--all'])).decode().splitlines()
  for item in objects:
   oid,_,name=item.partition(' ')
   kind=git('cat-file','-t',oid).decode().strip()
   if kind=='blob':
    scan('history:'+name,git('cat-file','blob',oid))
    if Path(name).name=='.DS_Store':findings.append(('history:'+name,'machine metadata'))
 for label,name in sorted(set(findings)):print('FAIL:',label,'—',name)
 if findings:return 1
 print('PASS: public-content scan'+(' including reachable history' if args.history is not None else ''))
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:
  print('FAIL: public-content scan could not complete ('+type(e).__name__+')',file=sys.stderr);sys.exit(2)
