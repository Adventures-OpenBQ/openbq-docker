#!/usr/bin/env bash
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
pinned=be00e95019a55d57af146919ee46b7e1a4859226
source_dir="$(cd "${1:?Usage: assemble.sh CHECKOUT_PATH}" && pwd -P)"
workspace_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
actual="$(git -C "$source_dir" rev-parse HEAD 2>/dev/null || true)"
if [[ "$actual" != "$pinned" ]]; then
  echo 'Source commit mismatch; refusing assembly.' >&2
  exit 1
fi
if [[ -n "$(git -C "$source_dir" status --porcelain --untracked-files=all)" ]]; then
  echo 'Source checkout must be clean.' >&2
  exit 1
fi
python3 - "$source_dir" "$workspace_dir" <<'PY'
import hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
src,root=map(Path,sys.argv[1:])
out=root/'build-context'
if out.exists(): raise SystemExit('build-context already exists; preserve or remove it explicitly before reassembly')
if src==out or out in src.parents or src in out.parents: raise SystemExit('Unsafe source/output overlap')
# Ignored files and assume-unchanged overrides are invisible to clean status.
# Assemble tracked bytes from the reviewed commit, then publish atomically.
with tempfile.TemporaryDirectory(prefix='.assembly-',dir=root) as temporary:
 temp=Path(temporary)
 archive=temp/'source.tar'
 with archive.open('wb') as stream:
  subprocess.run(['git','-C',str(src),'archive','--format=tar',
                  'be00e95019a55d57af146919ee46b7e1a4859226',
                  'lite','backend-api/backend','terminalpro'],stdout=stream,check=True)
 extracted=temp/'source';extracted.mkdir()
 subprocess.run(['tar','-xf',str(archive),'-C',str(extracted)],check=True)
 staged=temp/'build-context'
 shutil.copytree(extracted/'lite',staged,symlinks=True)
 shutil.copytree(extracted/'backend-api/backend',staged/'backend',symlinks=True)
 shutil.copytree(extracted/'terminalpro',staged/'terminalpro',symlinks=True)
 record={'upstream':'be00e95019a55d57af146919ee46b7e1a4859226',
         'files':{p.relative_to(staged).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(staged.rglob('*')) if p.is_file()}}
 (staged/'.workspace-source.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
 staged.rename(out)
print(out)
PY
