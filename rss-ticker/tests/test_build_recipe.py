"""A standalone RSS image must build exclusively with reviewed local tooling."""
from pathlib import Path
import re
import shlex
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def installs():
    recipe = (ROOT / 'Dockerfile').read_text().replace('\\\n', ' ')
    return [shlex.split(command) for command in re.findall(
        r'(?:RUN\s+|&&\s+)(?:python\s+-m\s+)?pip\s+install\s+([^\n&]+)', recipe)]


def test_tool_install_is_hashed_complete_and_precedes_source_builds():
    lock = (ROOT / 'requirements-build.lock').read_text()
    blocks = re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)[^\n]*\n((?:    --hash=[^\n]+\n)*)', lock, re.M)
    pins = {name: version for name, version, hashes in blocks
            if re.search(r'--hash=sha256:[a-f0-9]{64}', hashes)}
    assert len(pins) == len(blocks) >= 9
    assert set(pins) >= {'pip', 'setuptools', 'wheel', 'hatchling', 'packaging',
                         'pathspec', 'pluggy', 'tomlkit', 'trove-classifiers'}
    build_system = tomllib.loads((ROOT / 'pyproject.toml').read_text())['build-system']
    assert build_system['requires'] == ['hatchling==' + pins['hatchling']]
    commands = installs()
    assert commands[0][-2:] == ['-r', 'requirements-build.lock']
    assert {'--require-hashes', '--no-deps'} <= set(commands[0])


def test_hashed_runtime_sdists_use_preinstalled_tools_without_build_isolation():
    command = next(command for command in installs() if 'requirements.lock' in command)
    assert {'--require-hashes', '--no-deps', '--no-build-isolation'} <= set(command)


def test_local_package_cannot_resolve_an_isolated_backend_or_index_dependency():
    command = next(command for command in installs() if '.' in command)
    assert {'--no-build-isolation', '--no-deps', '--no-index'} <= set(command)
    recipe = (ROOT / 'Dockerfile').read_text()
    assert 'COPY requirements-build.lock ./requirements-build.lock' in recipe
    assert 'pip check' in recipe
