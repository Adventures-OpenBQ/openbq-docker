#!/usr/bin/env bash
# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
set -euo pipefail
workspace_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
python3 - "$workspace_dir" <<'PY'
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);context=root/'build-context'
provenance=json.loads((root/'source.json').read_text())
if provenance['commit']!='be00e95019a55d57af146919ee46b7e1a4859226':
    raise SystemExit('Unrecognized source pin')
if not context.is_dir() or context.is_symlink() or (context/'.workspace-patches.json').exists():
    raise SystemExit('A fresh assembled context is required')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
source_record=json.loads((context/'.workspace-source.json').read_text())
files={p.relative_to(context).as_posix():sha(p) for p in context.rglob('*')
       if p.is_file() and p.name!='.workspace-source.json'}
if (source_record.get('upstream')!=provenance['commit'] or files!=source_record.get('files')
        or any(p.is_symlink() for p in context.rglob('*'))):
    raise SystemExit('Assembled source checksum mismatch; rebuild from the pinned donor')
for relative,digest in provenance['lock_sha256'].items():
    if sha(context/relative)!=digest:raise SystemExit('Unrecognized original lock')
patches=sorted((root/'patches').glob('*.patch'))
if [p.name[:3] for p in patches]!=['001','002','003','004','005']:
    raise SystemExit('Unexpected patch sequence')
# A failed partial application remains visibly unusable; rebuild from a clean
# assembly instead of opportunistically guessing which hunks already applied.
(context/'.workspace-patches.json').write_text('{"status":"applying"}\n')
for patch in patches:
    subprocess.run(['patch','--batch','--forward','-p1','-i',str(patch)],cwd=context,check=True)
resolved=root/'resolved-poetry.lock'
if sha(resolved)!=provenance['observed_build']['resolved_lock_sha256']:
    raise SystemExit('Recorded resolved lock mismatch')
shutil.copyfile(resolved,context/'backend/poetry.lock')
files={'postgres/migrate_workspace.py':'backend/scripts/workspace_migration.py',
       'postgres/schema_manifest.json':'backend/scripts/workspace_schema_manifest.json'}
for source,target in files.items():shutil.copyfile(root/source,context/target)
record={'status':'complete','upstream':provenance['commit'],
        'patches':{p.name:sha(p) for p in patches},
        'packaged':{source:sha(root/source) for source in files},
        'resolved_lock':sha(resolved),'source_record':sha(context/'.workspace-source.json')}
(context/'.workspace-patches.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
print('Applied all five pinned patches and packaged reviewed migration inputs.')
PY
