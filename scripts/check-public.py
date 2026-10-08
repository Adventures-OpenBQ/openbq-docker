#!/usr/bin/env python3
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
 parser=argparse.ArgumentParser();parser.add_argument('--history',action='store_true');args=parser.parse_args()
 patterns=[
  ('tailscale key',r'tskey-[A-Za-z0-9-]{10,}'),
  ('GitHub token',r'gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,}'),
  ('private key',r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
  ('tailnet host',r'(?i)(?:[a-z0-9-]+\.)+[a-z0-9-]+\.ts\.net\b'),
  # 100.100.100.100 is Tailscale's fixed MagicDNS resolver on every tailnet (rita-resolv.conf), not a deployment detail.
  ('private address',r'\b(?!100\.100\.100\.100\b)(?:100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])|192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b'),
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
 compiled=[(name,re.compile(pattern)) for name,pattern in patterns]
 findings=[]
 def scan(label,data):
  text=data.decode('utf-8',errors='replace')
  text=text.replace('YOUR-TAILNET.ts.net','PLACEHOLDER').replace('YOUR_TAILNET.ts.net','PLACEHOLDER')
  for name,pattern in compiled:
   if pattern.search(text):findings.append((label,name))
  for match in re.finditer(r'(?m)^[ \t]*([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET|ACCESS_KEY_ID))[ \t]*=[ \t]*(.*)$',text):
   value=match.group(2).strip().strip('"').strip("'")
   if value and not value.startswith(('$','<')) and not re.fullmatch(r'(?:YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|PLACEHOLDER|CHANGE_ME|CHANGEME)',value):
    findings.append((label,'filled credential assignment'))
  for match in re.finditer(r'(?i)"[a-z0-9_]*(?:api_key|token|password|secret|access_key_id)"[ \t\r\n]*:[ \t\r\n]*"([^"\n]*)"',text):
   value=match.group(1).strip()
   if value and not value.startswith(('$','<')) and not re.fullmatch(r'(?:YOUR_[A-Z_]+|EXAMPLE_[A-Z_]+|PLACEHOLDER|CHANGE_ME|CHANGEME)',value):
    findings.append((label,'filled JSON credential'))
 files=git('ls-files','--cached','--others','--exclude-standard','-z').decode().split('\0')
 for name in sorted(set(filter(None,files))):
  p=Path(name)
  if p.is_symlink():raise RuntimeError('Refusing symlink: '+name)
  if p.is_file():scan(name,p.read_bytes())
  if '.env' in p.name and not p.name.endswith('.env.example'):findings.append((name,'runtime env file'))
 # The hook must scan staged blobs as well as working files.
 for item in git('ls-files','--stage','-z').decode().split('\0'):
  if not item:continue
  meta,name=item.split('\t',1);oid=meta.split()[1]
  scan('index:'+name,git('cat-file','blob',oid))
 if args.history:
  objects=git('rev-list','--objects','--all').decode().splitlines()
  for item in objects:
   oid,_,name=item.partition(' ')
   kind=git('cat-file','-t',oid).decode().strip()
   if kind=='blob':
    scan('history:'+name,git('cat-file','blob',oid))
    if Path(name).name=='.DS_Store':findings.append(('history:'+name,'machine metadata'))
 for label,name in sorted(set(findings)):print('FAIL:',label,'—',name)
 if findings:return 1
 print('PASS: public-content scan'+(' including reachable history' if args.history else ''))
 return 0
if __name__=='__main__':
 try:sys.exit(main())
 except Exception as e:
  print('FAIL: public-content scan could not complete ('+type(e).__name__+')',file=sys.stderr);sys.exit(2)
