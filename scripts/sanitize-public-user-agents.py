#!/usr/bin/env python3
# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Remove exact reviewed vendor corpus records before committing an image layer."""
import argparse
import copy
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


def file_sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def sanitize(archive, policy):
    hashes=['original_zip_sha256','original_member_sha256','filtered_member_sha256']
    removed=policy['remove_raw_line_sha256']
    if (not isinstance(removed,list) or not removed or len(set(removed))!=len(removed) or
        not all(isinstance(h,str) and re.fullmatch('[0-9a-f]{64}',h) for h in removed) or
        not all(re.fullmatch('[0-9a-f]{64}',policy[key]) for key in hashes) or
        type(policy['original_records']) is not int or type(policy['filtered_records']) is not int or
        policy['filtered_records']<=0 or policy['original_records']-len(removed)!=policy['filtered_records']):
        raise ValueError('Invalid reviewed corpus policy')
    if archive.is_symlink() or file_sha256(archive)!=policy['original_zip_sha256']:
        raise ValueError('Corpus differs from reviewed original archive')
    fd,temporary=tempfile.mkstemp(prefix='.public-agents-',suffix='.zip',dir=archive.parent)
    os.close(fd)
    temporary=Path(temporary)
    try:
        before_hash=hashlib.sha256();after_hash=hashlib.sha256()
        count=kept=0;seen={h:0 for h in removed}
        with zipfile.ZipFile(archive) as source,zipfile.ZipFile(temporary,'w') as target:
            if source.namelist().count(policy['member'])!=1:
                raise ValueError('Unexpected corpus archive member layout')
            target.comment=source.comment
            for info in source.infolist():
                with source.open(info) as reader,target.open(copy.copy(info),'w') as writer:
                    if info.filename!=policy['member']:
                        shutil.copyfileobj(reader,writer)
                        continue
                    for line in reader:
                        before_hash.update(line);count+=1
                        record=json.loads(line)
                        if not isinstance(record,dict) or not isinstance(record.get('user_agent'),str):
                            raise ValueError('Invalid corpus record structure')
                        digest=hashlib.sha256(line).hexdigest()
                        if digest in seen:
                            seen[digest]+=1
                        else:
                            writer.write(line);after_hash.update(line);kept+=1
            if (before_hash.hexdigest()!=policy['original_member_sha256'] or
                count!=policy['original_records'] or any(n!=1 for n in seen.values()) or
                after_hash.hexdigest()!=policy['filtered_member_sha256'] or
                kept!=policy['filtered_records']):
                raise ValueError('Corpus record guards or reviewed result do not match')
        filtered_archive_sha256=file_sha256(temporary)
        report={'records_before':count,'removed_records':count-kept,'records_after':kept,
                'filtered_member_sha256':after_hash.hexdigest(),'filtered_archive_sha256':filtered_archive_sha256}
        shutil.copystat(archive,temporary)
        os.replace(temporary,archive)
        return report
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy',required=True,type=Path)
    parser.add_argument('--archive',type=Path,help='Explicit archive for offline verification')
    args=parser.parse_args()
    try:
        policy=json.loads(args.policy.read_text())
        archive=args.archive
        if archive is None:
            distribution=metadata.distribution(policy['package'])
            if distribution.version!=policy['version']:
                raise ValueError('Installed corpus package version differs from review')
            archive=Path(distribution.locate_file(policy['package_member']))
        print(json.dumps(sanitize(archive,policy),sort_keys=True))
        return 0
    except Exception as error:
        # Library exceptions can include input records. Never render them.
        print('Public corpus cleanup failed: '+type(error).__name__,file=__import__('sys').stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
