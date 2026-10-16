# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Assemble only the pinned OpenBQ reference recipe and reviewed local additions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def assemble(source, output):
    pin = json.loads((ROOT / 'source.json').read_text())
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if head != pin['commit']:
        raise ValueError('Reference source revision does not match source.json')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Reference source checkout must be clean')
    if output.exists():
        raise ValueError('Assembly output already exists; use a fresh directory')
    shutil.copytree(source / pin['directory'], output)
    shutil.copy2(source / 'LICENSE', output / 'LICENSE.upstream')
    subprocess.run([sys.executable, str(ROOT / 'patch-cors.py'), str(output / 'core.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'patch-pdf.py'), str(output / 'widgets_types.py')], check=True)
    reference = json.loads((output / 'apps.json').read_text())
    recipes = [a for a in json.loads((ROOT / 'apps.json').read_text()) if a['name'].startswith('Episode 3')]
    if len(reference) != 1 or len(recipes) != 1:
        raise ValueError('Unexpected app catalog: review the reference recipe')
    # v3: no BDOBB layout extensions (BDOBB v3 refuses them); the Pivot examples app arrives with v4.
    (output / 'apps.json').write_text(json.dumps(reference, indent=2) + '\n')
    (output / 'bundle.apps.json').write_text(json.dumps(reference + recipes, indent=2) + '\n')
    (output / 'market-examples.apps.json').write_text(json.dumps(recipes, indent=2) + '\n')
    for name in ['server.py', 'reference_app.py', 'data.json', 'source.json']:
        shutil.copy2(ROOT / name, output / name)
    shutil.copytree(ROOT / 'assets', output / 'assets')
    print('Assembled pinned OpenBQ reference backend and the Episode 3 market examples')

if __name__ == '__main__':
    assemble(Path(sys.argv[1]), Path(sys.argv[2]))
