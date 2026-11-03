#!/usr/bin/env bash
# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd -P)"
cd "$root"
: "${WORKSPACE_TEST_IMAGE:?Set the actual locally built pinned compiled Workspace image}"
export DOCKER="${DOCKER:-docker}"
command -v "$DOCKER" >/dev/null
command -v python3 >/dev/null
command -v openssl >/dev/null
"$DOCKER" info >/dev/null
# Freeze the exact local artifact before creating generated-only services.
WORKSPACE_TEST_IMAGE="$("$DOCKER" image inspect --format '{{.Id}}' "$WORKSPACE_TEST_IMAGE")"
export WORKSPACE_TEST_IMAGE
printf 'Frozen Workspace image: %s\n' "$WORKSPACE_TEST_IMAGE"
export PYTHONPATH="$root/workspace/tests/postgres${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PROVENANCE'
import hashlib,json,os,subprocess
from pathlib import Path
root=Path('workspace');source=json.loads((root/'source.json').read_text())
result=subprocess.run([os.environ['DOCKER'],'run','--rm','--platform','linux/amd64',
    '--entrypoint','python',os.environ['WORKSPACE_TEST_IMAGE'],'-c',
    "from pathlib import Path;print(Path('/opt/code/workspace-build.json').read_text())"],
    capture_output=True,text=True,check=True)
actual=json.loads(result.stdout)
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
assert actual['status']=='complete' and actual['upstream']==source['commit']
assert actual['patches']=={p.name:sha(p) for p in sorted((root/'patches').glob('*.patch'))}
assert actual['packaged']=={p:sha(root/p) for p in ('postgres/migrate_workspace.py','postgres/schema_manifest.json')}
assert actual['resolved_lock']==sha(root/'resolved-poetry.lock')==source['observed_build']['resolved_lock_sha256']
assert actual['source_record']==source['postgresql_build']['assembly']['source_record']
print('Packaged source, patches, tools, manifest and lock provenance verified.')
PROVENANCE
# A complete run always generates new private data; no operator source argument.
WORKSPACE_FIXTURE="$(python3 -c 'from fixtures import prepare_complete; print(prepare_complete())')"
export WORKSPACE_FIXTURE
export WORKSPACE_SOURCE=full-source-v6.db
python3 -m unittest discover -s workspace/tests/postgres -p test_migration.py -v
python3 - <<'PY'
import os,sys
from pathlib import Path
from fixtures import image_run
root=Path(os.environ['WORKSPACE_FIXTURE'])
for name in ('test_config.py','test_image.py'):
    result=image_run(root,'-m','unittest','discover','-s','/tests','-p',name,'-v',env_file=root/'unicode-runtime.env')
    (root/(name+'.log')).write_text(result.stdout+result.stderr)
    print(name,'exit',result.returncode,flush=True)
    if result.returncode:sys.exit(result.returncode)
PY
python3 -m unittest discover -s workspace/tests/postgres -p test_lifecycle.py -k ProvisionTests -v
python3 -m unittest discover -s workspace/tests/postgres -p test_lifecycle.py -k BootstrapTests -v
python3 -m unittest discover -s workspace/tests/postgres -p test_lifecycle.py -k MigrationTests -v
python3 -m unittest discover -s workspace/tests/postgres -p test_lifecycle.py -k RefusalTests -v
python3 -m unittest discover -s workspace/tests/postgres -p test_restore.py -k TransferImageTests -v
WORKSPACE_SOURCE=full-source-v6-0d4.db python3 -m unittest discover -s workspace/tests/postgres -p test_restore.py -k complete_transfer_checkpoint -v
python3 -m unittest discover -s workspace/tests/postgres -p test_restore.py -k CompleteRestoreTests -v
printf 'All mandatory Workspace PostgreSQL gates passed. Private fixture evidence: %s\n' "$WORKSPACE_FIXTURE"
