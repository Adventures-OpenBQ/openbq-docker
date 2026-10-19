#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create immutable local build inputs; acquire remote commits separately when published."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--eodhd',type=Path,required=True)
parser.add_argument('--yfinance',type=Path,required=True)
parser.add_argument('--build',action='store_true')
parser.add_argument('--tag',default='openbq-local:11.0.0-candidate')
args=parser.parse_args()
lock=json.loads((root/'v11/temporaldb.lock.json').read_text())
destination=root/'v11/build-inputs'
destination.mkdir(exist_ok=True)
arguments=[]
manifest={}
for name,source in [('eodhd',args.eodhd),('yfinance',args.yfinance)]:
    def git(*values): return subprocess.check_output(['git','-C',str(source),*values])
    expected=lock['providers'][name]['reviewed_commit']
    if git('rev-parse','HEAD').decode().strip()!=expected or git('status','--porcelain').strip():
        raise SystemExit(name+' source must be clean at the reviewed immutable commit')
    archive=git('archive','--format=tar',expected)
    digest=sha256(archive).hexdigest()
    (destination/(name+'.tar')).write_bytes(archive)
    manifest[name]={'commit':expected,'archive_sha256':digest,'distribution':'verified local clean commit archive; remote availability not asserted'}
    arguments += ['--build-arg',name.upper()+'_COMMIT='+expected,'--build-arg',name.upper()+'_ARCHIVE_SHA256='+digest]
legacy=(root/'Dockerfile').read_text()
if legacy.count('FROM odp AS api\n')!=1: raise SystemExit('api stage changed; review recipe')
recipe=legacy+'\n'+(root/'v11/Dockerfile.providers').read_text()
(destination/'Dockerfile').write_text(recipe)
(destination/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
command=['docker','build','--platform','linux/arm64','-f',str(destination/'Dockerfile'),'--target','v11','-t',args.tag,*arguments,str(root)]
print(json.dumps({'sources':manifest,'build_command':command},indent=2))
if args.build: subprocess.run(command,check=True)
