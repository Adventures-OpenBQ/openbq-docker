"""The actual commit hook inspects archive members and retains main's scanner."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def archive_hook(content, *, missing_scanner=False):
    """Use the actual commit hook and credential gate, never a scanner stub."""
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary)
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'scripts').mkdir()
        (repo / 'security').mkdir()
        shutil.copyfile(ROOT / 'scripts/check-public.py', repo / 'scripts/check-public.py')
        for name in ('gate.py', 'gitleaks.toml'):
            shutil.copyfile(ROOT / 'security' / name, repo / 'security' / name)
        archive = repo / 'fixture.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr('fixture.txt', content)
        compressed = archive.read_bytes()
        subprocess.run(['git', 'add', 'fixture.zip'], cwd=repo, check=True)
        environment = dict(os.environ)
        if missing_scanner:
            environment['GITLEAKS_BIN'] = str(repo / 'scanner-not-installed')
        result = subprocess.run(['sh', str(ROOT / '.githooks/pre-commit')], cwd=repo,
                                env=environment, capture_output=True, text=True)
        return result, compressed


def test_commit_hook_checks_compressed_staged_bytes_and_never_echoes_secrets():
    token = 'tskey-' + 'auth-' + 'Ab12Cd34' * 5
    result, compressed = archive_hook(token)
    assert token.encode() not in compressed
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'PASS: public-content scan' in result.stdout
    assert 'tailscale-credential' in result.stderr
    assert token not in result.stdout + result.stderr


def test_commit_hook_accepts_a_clean_compressed_staged_file():
    result, _ = archive_hook('public fixture text')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS: public-content scan' in result.stdout
    assert 'secret-gate: passed' in result.stdout


def test_commit_hook_missing_required_scanner_remains_a_blocking_error():
    result, _ = archive_hook('public fixture text', missing_scanner=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'PASS: public-content scan' in result.stdout
    assert 'secret-gate: ERROR' in result.stderr
    assert 'publication blocked' in result.stderr
    assert 'secret-gate: passed' not in result.stdout
