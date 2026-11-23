"""Remove only reviewed corpus records, before a dependency layer is published."""
import hashlib
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/sanitize-public-user-agents.py'
MEMBER='user_agents.jl'
ORIGINAL=(b'{"user_agent":"safe one"}\n'
          b'{"user_agent":"remove one"}\n'
          b'{"user_agent":"safe two"}\n'
          b'{"user_agent":"remove two"}\n'
          b'{"user_agent":"safe three"}')
FILTERED=(b'{"user_agent":"safe one"}\n'
          b'{"user_agent":"safe two"}\n'
          b'{"user_agent":"safe three"}')
sha=lambda data:hashlib.sha256(data).hexdigest()

class PublicUserAgentCleanup(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.archive=self.root/'agents.zip'
        with zipfile.ZipFile(self.archive,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment=b'public fixture metadata'
            archive.writestr(MEMBER,ORIGINAL)
            archive.writestr('other.txt',b'preserve other bytes')
        self.original=self.archive.read_bytes()
        self.policy={'package':'random-user-agent','version':'1.0.1',
                     'package_member':'random_user_agent/data/user_agents.zip',
                     'original_zip_sha256':sha(self.original),'member':MEMBER,
                     'original_member_sha256':sha(ORIGINAL),'original_records':5,
                     'remove_raw_line_sha256':[
                         sha(b'{"user_agent":"remove one"}\n'),
                         sha(b'{"user_agent":"remove two"}\n')],
                     'filtered_member_sha256':sha(FILTERED),'filtered_records':3}
        self.policy_path=self.root/'policy.json'

    def run_cleanup(self):
        self.policy_path.write_text(json.dumps(self.policy))
        return subprocess.run([sys.executable,str(SCRIPT),'--archive',str(self.archive),
                               '--policy',str(self.policy_path)],capture_output=True,text=True)

    def test_only_reviewed_records_are_removed_and_other_bytes_preserved(self):
        result=self.run_cleanup()
        self.assertEqual(result.returncode,0,result.stderr)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertEqual(archive.read(MEMBER),FILTERED)
            self.assertEqual(archive.read('other.txt'),b'preserve other bytes')
            self.assertEqual(archive.comment,b'public fixture metadata')
        report=json.loads(result.stdout)
        self.assertEqual(report['removed_records'],2)
        self.assertEqual(report['records_after'],3)
        self.assertNotIn('remove one',result.stdout+result.stderr)

    def test_changed_original_archive_is_rejected_without_writing(self):
        self.archive.write_bytes(self.original+b'changed')
        before=self.archive.read_bytes();result=self.run_cleanup()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.archive.read_bytes(),before)

    def test_missing_reviewed_record_is_rejected_without_writing(self):
        self.policy['remove_raw_line_sha256'][0]=sha(b'unknown synthetic record')
        result=self.run_cleanup()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.archive.read_bytes(),self.original)

    def test_wrong_record_count_is_rejected_without_writing(self):
        self.policy['original_records']=6
        result=self.run_cleanup()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.archive.read_bytes(),self.original)

    def test_stream_count_mismatch_is_rejected_after_valid_policy_arithmetic(self):
        self.policy.update(original_records=6,filtered_records=4)
        result=self.run_cleanup()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.archive.read_bytes(),self.original)

    def test_wrong_filtered_hash_is_rejected_without_writing(self):
        self.policy['filtered_member_sha256']=sha(b'not the reviewed result')
        result=self.run_cleanup()
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.archive.read_bytes(),self.original)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),['agents.zip','policy.json'])

    def test_original_policy_cannot_be_reapplied_to_different_cleaned_bytes(self):
        result=self.run_cleanup();self.assertEqual(result.returncode,0,result.stderr)
        cleaned=self.archive.read_bytes();second=self.run_cleanup()
        self.assertNotEqual(second.returncode,0)
        self.assertEqual(self.archive.read_bytes(),cleaned)

    def test_output_digest_read_failure_preserves_original_archive(self):
        spec=importlib.util.spec_from_file_location('public_agent_sanitizer',SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original_hasher=module.file_sha256
        first=True
        def failing_output_read(path):
            nonlocal first
            if first:
                first=False
                return original_hasher(path)
            raise OSError('Synthetic digest read failure')
        with patch.object(module,'file_sha256',side_effect=failing_output_read):
            with self.assertRaises(OSError):module.sanitize(self.archive,self.policy)
        self.assertEqual(self.archive.read_bytes(),self.original)
        self.assertEqual([p.name for p in self.root.iterdir()],['agents.zip'])

    def test_installed_version_mismatch_refuses_matching_archive(self):
        self.policy_path.write_text(json.dumps(self.policy))
        spec=importlib.util.spec_from_file_location('public_agent_sanitizer_version',SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        distribution=SimpleNamespace(version='1.0.2',locate_file=lambda name:self.archive)
        with patch.object(module.metadata,'distribution',return_value=distribution), \
             patch.object(sys,'argv',[str(SCRIPT),'--policy',str(self.policy_path)]), \
             redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            self.assertEqual(module.main(),1)
        self.assertEqual(self.archive.read_bytes(),self.original)

if __name__=='__main__':unittest.main()
