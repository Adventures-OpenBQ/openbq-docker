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
python3 - "$source_dir" "$workspace_dir" "$pinned" <<'PY'
import hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
src,root=map(Path,sys.argv[1:3])
pinned=sys.argv[3]
lock=root/'resolved-poetry.lock'
expected=json.loads((root/'source.json').read_text())['observed_build']['resolved_lock_sha256']
if hashlib.sha256(lock.read_bytes()).hexdigest()!=expected:
 raise SystemExit('Resolved Workspace lock does not match source.json')
out=root/'build-context'
if out.exists(): raise SystemExit('build-context already exists; preserve or remove it explicitly before reassembly')
if src==out or out in src.parents or src in out.parents: raise SystemExit('Unsafe source/output overlap')
# A clean status does not cover ignored files or assume-unchanged overrides.
# Extract only the reviewed commit, never the checkout's filesystem contents.
with tempfile.TemporaryDirectory(prefix='.assembly-',dir=root) as temp:
 temp=Path(temp)
 archive=temp/'source.tar'
 with archive.open('wb') as stream:
  subprocess.run(['git','-C',str(src),'archive','--format=tar',pinned,
                  'lite','backend-api/backend','terminalpro'],stdout=stream,check=True)
 extracted=temp/'source'
 extracted.mkdir()
 subprocess.run(['tar','-xf',str(archive),'-C',str(extracted)],check=True)
 staged=temp/'build-context'
 shutil.copytree(extracted/'lite',staged,symlinks=True)
 shutil.copytree(extracted/'backend-api/backend',staged/'backend',symlinks=True)
 shutil.copyfile(lock,staged/'backend/poetry.lock')
 shutil.copytree(extracted/'terminalpro',staged/'terminalpro',symlinks=True)
 subprocess.run(['patch','--batch','--forward','--fuzz=0','-p1','-i',
                 str(root/'patches/005-workspace-request-boundaries.patch')],cwd=staged,check=True)
 subprocess.run(['patch','--batch','--forward','--fuzz=0','-p1','-i',
                 str(root/'patches/006-public-test-key-packaging.patch')],cwd=staged,check=True)
 fixtures=staged/'public-test-fixtures'
 fixtures.mkdir()
 shutil.copyfile(root/'scripts/strip_public_test_key.py', fixtures/'strip_public_test_key.py')
 staged.rename(out)
print(out)
PY
