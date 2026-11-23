#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Omit one unused upstream TLS test key before the final runtime venv COPY.

This is a package overlay, not an assertion that the installed wheel is intact.
Its RECORD and every other resource stay unchanged; a separate receipt records
this precise intentional omission. Unexpected package/resource bytes fail closed.
"""
import argparse
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import stat
import sysconfig

EXPECTED_VERSION = '6.5.8'
EXPECTED_SHA256 = '2c95ec86909e3299af80778674140159a44c2b8c8422f31a82e81d40572f0c74'
EXPECTED_SIZE = 1708
WHEEL_SHA256 = '547d63f450d570c14fe0e8db2cfb14c9bbd1c2503b4a6612586267955aa47b58'
WHEEL_URL = ('https://files.pythonhosted.org/packages/6e/de/'
             'f2e733f386b85962d1b1dc82cd63d169b5b4580062b35397eac9244a41fe/'
             'tornado-6.5.8-cp39-abi3-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl')


def strip_test_key(site_packages, manifest, *, expected_sha256=EXPECTED_SHA256,
                   expected_size=EXPECTED_SIZE):
    site, manifest = Path(site_packages), Path(manifest)
    target = site / 'tornado/test/test.key'
    metadata_dir = site / f'tornado-{EXPECTED_VERSION}.dist-info'
    # Never follow a redirected resource or package directory while deleting.
    for path in (site, site / 'tornado', target.parent, target,
                 metadata_dir, metadata_dir / 'METADATA'):
        if path.is_symlink():
            raise ValueError('Unexpected symlink in reviewed Tornado fixture path')
    distributions = sorted(p.name for p in site.iterdir()
                           if p.name.lower().startswith('tornado-') and p.name.endswith('.dist-info'))
    if distributions != [metadata_dir.name]:
        raise ValueError('Unexpected Tornado distribution version or duplicate metadata')
    metadata = Parser().parsestr((metadata_dir / 'METADATA').read_text())
    if metadata.get('Name', '').lower() != 'tornado' or metadata.get('Version') != EXPECTED_VERSION:
        raise ValueError('Unexpected Tornado distribution metadata')
    if not stat.S_ISREG(target.stat().st_mode):
        raise ValueError('Expected regular Tornado test fixture')
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != expected_size or digest != expected_sha256:
        raise ValueError('Unexpected Tornado fixture bytes; no file removed')
    if site.resolve() in manifest.resolve().parents:
        raise ValueError('Removal receipt must stay outside installed package resources')
    retained = []
    for root in (site / 'tornado', metadata_dir):
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Unexpected symlink in preserved Tornado resources')
            if path.is_file() and path != target:
                retained.append((path.relative_to(site).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    retained.sort()
    retained_digest = hashlib.sha256(''.join(f'{name}\0{sha}\n' for name, sha in retained).encode()).hexdigest()
    receipt = {
        'schema_version': 1, 'package': 'tornado', 'version': EXPECTED_VERSION,
        'removed': {'path': 'tornado/test/test.key', 'bytes': len(data), 'sha256': digest},
        'reason': 'Unused public upstream HTTPS unittest private-key fixture; runtime modules retained',
        'official_wheel_url': WHEEL_URL, 'official_wheel_sha256': WHEEL_SHA256,
        'preserved_files': len(retained), 'preserved_tree_sha256': retained_digest,
        'upstream_RECORD_unmodified': True,
    }
    # Validate and serialize everything before mutation. Exclusive creation keeps
    # an existing receipt untouched; failure to write leaves the resource intact.
    encoded = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
    created = False
    try:
        with manifest.open('xb') as stream:
            created = True
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        target.unlink()
    except BaseException:
        if created:
            manifest.unlink(missing_ok=True)
        raise
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-packages', default=sysconfig.get_path('purelib'))
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    receipt = strip_test_key(args.site_packages, args.manifest)
    print(f"Removed one reviewed {receipt['package']} {receipt['version']} public test fixture; "
          f"preserved {receipt['preserved_files']} other resources")


if __name__ == '__main__':
    main()
