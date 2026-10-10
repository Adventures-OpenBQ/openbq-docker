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
import shutil,sys
from pathlib import Path
src,root=map(Path,sys.argv[1:])
out=root/'build-context'
if out.exists(): raise SystemExit('build-context already exists; preserve or remove it explicitly before reassembly')
if src==out or out in src.parents or src in out.parents: raise SystemExit('Unsafe source/output overlap')
ignore=shutil.ignore_patterns('.git','node_modules','.venv','venv','__pycache__','dist','._*','.DS_Store','.env.local')
shutil.copytree(src/'lite',out,ignore=ignore)
shutil.copytree(src/'backend-api/backend',out/'backend',ignore=ignore)
shutil.copytree(src/'terminalpro',out/'terminalpro',ignore=ignore)
print(out)
PY
