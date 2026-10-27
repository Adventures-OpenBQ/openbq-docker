#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Vendor an arts-charts-openbq snapshot into v12/arts-charts/source and record it in
v12/arts-charts.lock.json. Reads the arts-charts repository with `git archive` only.

    python3 v12/arts-charts/vendor.py --repo <arts-charts checkout> --commit <sha>
    python3 v12/arts-charts/vendor.py --repo <arts-charts checkout> --tag v0.1.0
"""
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = HERE.parent / 'arts-charts.lock.json'
REPOSITORY = 'https://github.com/Adventures-OpenBQ/arts-charts-openbq'
# The server package, and the client's render page (snapshots draw the real card) with
# what it imports. Nothing else of the repository is shipped.
PATHS = ['LICENSE', 'server/pyproject.toml', 'server/arts_charts',
         'client/package.json', 'client/pnpm-lock.yaml', 'client/tsconfig.json',
         'client/vite.render.config.ts', 'client/render', 'client/src', 'client/LICENSE',
         'client/ARTS_CHARTS_TERMS.md', 'client/THIRD_PARTY_NOTICES.md', 'dev/tokens.css']


def excluded(name: str) -> bool:
    parts = name.split('/')
    return 'test' in parts or '__pycache__' in parts or name.endswith(('.test.ts', '.test.tsx'))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(f'{rel}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n'.encode())
    return digest.hexdigest()


def git(repo: str, *args: str) -> bytes:
    return subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    ref = parser.add_mutually_exclusive_group(required=True)
    ref.add_argument('--commit')
    ref.add_argument('--tag')
    args = parser.parse_args()
    name = args.commit or f'refs/tags/{args.tag}'
    commit = git(args.repo, 'rev-parse', '--verify', f'{name}^{{commit}}').decode().strip()
    archive = git(args.repo, 'archive', '--format=tar', commit, *PATHS)
    source = HERE / 'source'
    shutil.rmtree(source, ignore_errors=True)
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = [m for m in tar.getmembers() if m.isfile() and not excluded(m.name)]
        tar.extractall(source, members=members, filter='data')
    lock = {'service': 'arts-charts', 'image': 'openbq-arts-charts:12.0.0',
            'source_repository': REPOSITORY, 'tag': args.tag, 'source_commit': commit,
            'source_tree_sha256': tree_hash(source), 'license': 'BUSL-1.1', 'paths': PATHS}
    if args.tag is None:
        lock['repin'] = 'pending: re-run vendor.py --tag v0.1.0 once the user tags arts-charts-openbq'
    LOCK.write_text(json.dumps(lock, indent=2) + '\n')
    print(f'vendored {commit} ({lock["source_tree_sha256"]})')


if __name__ == '__main__':
    main()
