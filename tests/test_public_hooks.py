"""The actual commit hook inspects archive members and retains main's scanner."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def test_commit_hook_checks_compressed_staged_bytes_and_never_echoes_secrets():
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'scripts').mkdir()
        (repo / 'security').mkdir()
        shutil.copyfile(ROOT / 'scripts/check-public.py', repo / 'scripts/check-public.py')
        for name in ('gate.py', 'gitleaks.toml'):
            shutil.copyfile(ROOT / 'security' / name, repo / 'security' / name)
        token = 'tskey-' + 'auth-' + 'Ab12Cd34' * 5
        archive = repo / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr('fixture.txt', token)
        assert token.encode() not in archive.read_bytes()
        subprocess.run(['git', 'add', 'fixture.zip'], cwd=repo, check=True)
        result = subprocess.run(['sh', str(ROOT / '.githooks/pre-commit')], cwd=repo,
                                env=dict(os.environ), capture_output=True, text=True)
        assert result.returncode == 1, result.stdout + result.stderr
        assert 'PASS: public-content scan' in result.stdout
        assert 'tailscale-credential' in result.stderr
        assert token not in result.stdout + result.stderr
