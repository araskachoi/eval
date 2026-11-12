#!/usr/bin/env python3
"""Publish checked local releases, refresh Record, and safely switch the collector."""
from __future__ import annotations

import argparse
import ast
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_eval.__main__ import control
from codex_eval.core import private_directory

RELEASE_ID = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{12}\Z')
SKILL_FILES = ('SKILL.md', 'agents/openai.yaml')
PROCESSES = {}


def source_files(root):
    files = {}
    for folder, suffixes in (('codex_eval', {'.py', '.html', '.js', '.css'}),
                             ('scripts', {'.py'}), ('regression/benchmarks', {'.py', '.json', '.md'}),
                             ('integrations/codex/record', {'.md', '.yaml'})):
        base = root / folder
        if base.is_symlink() or any(p.is_symlink() for p in base.parents):
            raise ValueError('Symlinked release source refused')
        for path in sorted(base.rglob('*')):
            relative = path.relative_to(root)
            if any(p.startswith('.') or p == '__pycache__' for p in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError('Symlinked release source refused')
            if path.is_file() and path.suffix in suffixes:
                data = path.read_bytes()
                if len(data) > 1024 * 1024:
                    raise ValueError('Release file too large')
                if path.suffix == '.py':
                    compile(data, str(relative), 'exec')
                files[relative.as_posix()] = data
    project = root / 'pyproject.toml'
    if project.is_symlink():
        raise ValueError('Symlinked project metadata refused')
    files['pyproject.toml'] = project.read_bytes()
    if not {'codex_eval/__main__.py', 'codex_eval/version.py', 'scripts/install_record_skill.py', 'integrations/codex/record/SKILL.md'} <= files.keys():
        raise ValueError('Incomplete release source')
    if len(files) > 400 or sum(map(len, files.values())) > 16 * 1024 * 1024:
        raise ValueError('Release exceeds bounds')
    return files


def digest(files):
    result = hashlib.sha256()
    for name, data in sorted(files.items()):
        result.update(name.encode() + b'\0' + data)
    return result.hexdigest()


def validation_digest(root):
    files = source_files(root)
    for path in sorted((root / 'tests').glob('*.py')):
        if path.is_symlink():
            raise ValueError('Symlinked tests refused')
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return digest(files)


def atomic(path, data):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Symlinked output refused')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())


def git_info(root):
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        dirty = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'codex_eval', 'scripts', 'integrations', 'regression/benchmarks', 'pyproject.toml'], cwd=root, capture_output=True, timeout=5).returncode != 0
        return (commit if re.fullmatch('[0-9a-f]{40,64}', commit) else None), dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def make_release(root, directory, validation):
    files = source_files(root)
    tree = ast.parse(files['codex_eval/version.py'])
    version = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets))
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Use a major.minor.patch application version')
    sha = digest(files)
    release_id = version + '-' + sha[:12]
    destination = directory / release_id
    if destination.exists():
        verify_release(destination)
        return destination
    commit, dirty = git_info(root)
    manifest = dict(version=version, release_id=release_id, source_digest=sha,
                    git_commit=commit, git_dirty=dirty, created=time.time(),
                    schema_versions=[0, 1], validation=validation)
    stage = directory / ('.stage-' + uuid.uuid4().hex)
    stage.mkdir(mode=0o700, parents=True)
    try:
        for name, data in files.items():
            atomic(stage / name, data)
        write_json(stage / 'release.json', manifest)
        write_json(stage / 'codex_eval/_release.json', manifest)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return destination


def verify_release(path):
    if not RELEASE_ID.fullmatch(path.name) or path.is_symlink():
        raise ValueError('Invalid release identifier')
    manifest = json.loads((path / 'release.json').read_text())
    if manifest.get('release_id') != path.name or not manifest.get('validation', {}).get('passed'):
        raise ValueError('Release lacks validation evidence')
    if digest(source_files(path)) != manifest['source_digest'] or path.name != manifest['version'] + '-' + manifest['source_digest'][:12]:
        raise ValueError('Release content changed; activation refused')
    if json.loads((path / 'codex_eval/_release.json').read_text()) != manifest:
        raise ValueError('Runtime version differs from release manifest')
    return manifest


def isolated_checks(root, magen):
    result = subprocess.run([sys.executable, str(root / 'scripts/isolated.py'), 'test', '--magen', str(magen), '--no-export'], cwd=root, capture_output=True, timeout=180)
    if result.returncode:
        raise ValueError('Isolated validation failed. Run scripts/isolated.py test to inspect; no release activated')
    output = (result.stdout + result.stderr).decode(errors='replace')
    match = re.search(r'Ran ([0-9]+) tests in', output)
    if not match or 'OK' not in output:
        raise ValueError('Validation evidence unavailable')
    print(f'Isolated checks passed: {match[1]} tests', flush=True)
    return dict(passed=True, runner='dedicated-vm-rootless-container', tests=int(match[1]), checked_at=time.time())


def collector_status(state):
    try:
        return control(state, {'action':'status'})
    except (FileNotFoundError, ConnectionRefusedError):
        return None


def check_database(state, manifest):
    path = state / 'metrics.sqlite3'
    if not path.exists():
        return
    if path.is_symlink():
        raise ValueError('Symlinked database refused')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as database:
        if database.execute('PRAGMA user_version').fetchone()[0] not in manifest['schema_versions']:
            raise ValueError('Release is incompatible with the current database; no migration or downgrade performed')
        if database.execute("SELECT 1 FROM sqlite_master WHERE name='recordings'").fetchone() and database.execute('SELECT 1 FROM recordings WHERE finished IS NULL').fetchone():
            raise ValueError('Finish the active recording before publishing or rolling back')


def prepare(state):
    status = collector_status(state)
    if status:
        if any(r['finished'] is None for r in status['recordings']):
            raise ValueError('Finish the active recording before updating')
        try:
            control(state, {'action':'prepare_update'})
        except ValueError:
            raise ValueError('Collector cannot reserve an update. Stop the legacy collector once, then retry') from None
    return status is not None


def stop_collector(state):
    control(state, {'action':'shutdown_for_update'})
    deadline = time.monotonic() + 8
    while (state / 'control.sock').exists() and time.monotonic() < deadline:
        time.sleep(.05)
    if (state / 'control.sock').exists():
        raise ValueError('Collector did not stop; activation refused')
    process = PROCESSES.pop(str(state), None)
    if process is not None:
        process.wait(timeout=3)


def start_collector(release, cfg):
    state = Path(cfg['state'])
    stale = state / 'control.sock'
    if stale.exists():
        if collector_status(state) is not None:
            raise ValueError('Another collector owns this state')
        if stale.is_symlink():
            raise ValueError('Symlinked socket refused')
        stale.unlink()
    env = {'PATH':str(Path(cfg['python']).parent) + ':/usr/bin:/bin', 'LANG':'C.UTF-8', 'PYTHONDONTWRITEBYTECODE':'1'}
    process = subprocess.Popen([cfg['python'], '-m', 'codex_eval', '--state', str(state), 'collector', 'start', '--port', str(cfg['port'])], cwd=release, env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and process.poll() is None:
            try:
                info = control(state, {'action':'version'})
                if info['release_id'] == release.name:
                    PROCESSES[str(state)] = process
                    return process
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        raise ValueError('Published collector failed its startup health check')
    except BaseException:
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
        raise


def skill_files(release, cfg, staging):
    result = subprocess.run([cfg['python'], str(release / 'scripts/install_record_skill.py'), '--skills-dir', str(staging), '--state', cfg['state']], capture_output=True, timeout=10)
    if result.returncode:
        raise ValueError('Could not render the release-specific Record skill')
    return {name:(staging / 'record' / name).read_bytes() for name in SKILL_FILES}


def read_skill(cfg):
    folder = Path(cfg['skills_dir']) / 'record'
    values = {}
    for name in SKILL_FILES:
        path = folder / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError('Symlinked global skill refused')
        values[name] = path.read_bytes() if path.exists() else None
    return values


def hashes(values):
    return {k:hashlib.sha256(v).hexdigest() if v is not None else None for k,v in values.items()}


def activate(release, cfg, app_dir, reserved, adopt=False):
    manifest = verify_release(release)
    state = Path(cfg['state'])
    check_database(state, manifest)
    before = read_skill(cfg)
    expected = cfg.get('skill_hashes')
    if expected is not None and hashes(before) != expected:
        raise ValueError('Installed Record skill changed outside the publisher; not overwritten')
    if expected is None and any(v is not None for v in before.values()) and not adopt:
        raise ValueError('Existing skill requires --adopt-skill for the first managed publish')
    previous = app_dir / 'releases' / cfg['active'] if cfg.get('active') else None
    if previous:
        verify_release(previous)
    with tempfile.TemporaryDirectory(prefix='.skill-', dir=app_dir) as temp:
        new_skill = skill_files(release, cfg, Path(temp))
        if reserved:
            stop_collector(state)
        process = None
        changed = False
        try:
            process = start_collector(release, cfg)
            if read_skill(cfg) != before:
                raise ValueError('Global skill changed during activation; update refused')
            changed = True
            for name, data in new_skill.items():
                atomic(Path(cfg['skills_dir']) / 'record' / name, data)
            updated = cfg | {'active':release.name, 'previous':cfg.get('active'), 'skill_hashes':hashes(new_skill)}
            write_json(app_dir / 'install.json', updated)
            return updated
        except BaseException:
            if process is not None:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
                PROCESSES.pop(str(state), None)
            try:
                if changed:
                    for name, data in before.items():
                        target = Path(cfg['skills_dir']) / 'record' / name
                        if data is None:
                            target.unlink(missing_ok=True)
                        elif not target.exists() or target.read_bytes() != data:
                            atomic(target, data)
            finally:
                if reserved and previous:
                    start_collector(previous, cfg)
            raise


@contextmanager
def publisher_lock(app_dir):
    path = app_dir / 'publish.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Another publish/rollback is running') from None
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    publish = commands.add_parser('publish')
    publish.add_argument('--state', type=Path)
    publish.add_argument('--skills-dir', type=Path)
    publish.add_argument('--magen', type=Path)
    publish.add_argument('--port', type=int)
    publish.add_argument('--adopt-skill', action='store_true')
    commands.add_parser('versions')
    commands.add_parser('status')
    commands.add_parser('stop')
    rollback = commands.add_parser('rollback')
    rollback.add_argument('release_id')
    args = parser.parse_args()
    os.umask(0o077)
    reserved = False
    state = None
    try:
        app_dir = private_directory(ROOT / '.runtime/app')
        releases = private_directory(app_dir / 'releases')
        config_path = app_dir / 'install.json'
        cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
        if args.command == 'versions':
            for release in sorted(releases.iterdir()):
                if RELEASE_ID.fullmatch(release.name):
                    info = verify_release(release)
                    print(f"{release.name}{'  ACTIVE' if cfg.get('active') == release.name else ''}  git={info['git_commit'] or 'unavailable'}{' (dirty source)' if info['git_dirty'] else ''}")
            return
        if args.command == 'status':
            print(json.dumps(cfg, indent=2))
            return
        if args.command == 'publish':
            defaults = dict(state=str(Path.home() / 'Library/Application Support/codex-eval'), skills_dir=str(Path.home() / '.codex/skills'), python=sys.executable, port=8765)
            cfg = defaults | cfg
            for name in ('state', 'skills_dir', 'magen'):
                value = getattr(args, name)
                if value is not None:
                    value = str(value.expanduser().absolute())
                    if config_path.exists() and name in ('state','skills_dir') and value != cfg[name]:
                        raise ValueError('Changing managed state or skill location requires a separate installation')
                    cfg[name] = value
            if args.port is not None: cfg['port'] = args.port
            if not 1 <= cfg['port'] <= 65535 or not cfg.get('magen'):
                raise ValueError('First publish requires --magen PATH and a valid local port')
        elif not cfg:
            raise ValueError('No managed release exists; publish first')
        state = private_directory(Path(cfg['state']))
        with publisher_lock(app_dir):
            reserved = prepare(state)
            check_database(state, {'schema_versions':[0,1]})
            if args.command == 'stop':
                if reserved: stop_collector(state)
                reserved = False
                print('Collector stopped; releases and recordings retained.')
                return
            if args.command == 'publish':
                before = validation_digest(ROOT)
                validation = isolated_checks(ROOT, Path(cfg['magen']))
                if validation_digest(ROOT) != before:
                    raise ValueError('Source changed during validation; publish again after edits are finished')
                validation['inputs_digest'] = before
                release = make_release(ROOT, releases, validation)
            else:
                if not RELEASE_ID.fullmatch(args.release_id):
                    raise ValueError('Select an exact release ID from versions')
                release = releases / args.release_id
            updated = activate(release, cfg, app_dir, reserved, adopt=getattr(args,'adopt_skill',False))
            reserved = False
            print(f"Active: {updated['active']}\nApp: http://127.0.0.1:{updated['port']}/\nRecord skill refreshed. Reload the browser and obtain a fresh panel code.\nRecordings were retained; rollback changes code, not data.")
    except KeyboardInterrupt:
        parser.exit(1, 'Publish interrupted; inspect status before retrying.\n')
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        parser.exit(1, f'Update refused: {exc}\n')
    finally:
        if reserved and state is not None:
            try: control(state, {'action':'cancel_update'})
            except (OSError, ValueError): pass


if __name__ == '__main__':
    main()
