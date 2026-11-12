"""Run one ledger check per verified container. Expected results stay in the launcher."""
from hashlib import sha256
import json
import subprocess
import time

# The guest driver owns the result stream. Submitted code gets private, bounded
# output files and cannot open the driver's file descriptors through /proc.
DRIVER = r'''
import base64, ctypes, hashlib, json, os, resource, signal, stat, subprocess, sys, tempfile
from pathlib import Path

assert ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) == 0  # PR_SET_DUMPABLE
for name, size_mib in (('/work', 64), ('/tmp', 32)):
    mount = os.statvfs(name)
    flags = os.ST_NOSUID | os.ST_NODEV | os.ST_NOEXEC
    assert mount.f_blocks * mount.f_frsize == size_mib * 1024**2
    assert mount.f_flag & flags == flags
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
payload = json.load(sys.stdin)
for name, encoded in payload['files'].items():
    Path(name).write_bytes(base64.b64decode(encoded))

def snapshot(name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            data = stream.read(65537)
            return data if len(data) <= 65536 else None
    except OSError:
        return None

observations = []
for command in payload['commands']:
    with tempfile.TemporaryFile(dir='/tmp') as stdout:
        args = [sys.executable, '-I', '-B', 'ledger.py', command, 'ledger.json']
        if command == 'apply':
            args.append('batch.json')
        with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=stdout,
                              stderr=subprocess.DEVNULL, start_new_session=True) as proc:
            try:
                status = proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                status = None
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        stdout.seek(0)
        observations.append([status, stdout.read(8193).decode('utf-8', errors='replace')])

ledger = snapshot('ledger.json')
protected = {}
for name in ('ledger.py', 'batch.json'):
    data = snapshot(name)
    protected[name] = hashlib.sha256(data).hexdigest() if data is not None else None
print(json.dumps({'steps': observations, 'protected': protected,
                  'ledger': base64.b64encode(ledger).decode() if ledger is not None else None}))
'''


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def digest(data):
    return sha256(data).hexdigest()


def payload_for(case, submission):
    from base64 import b64encode
    batch = case['batch']
    files = {'ledger.py': submission, 'ledger.json': encode(case['ledger']),
             'batch.json': batch.encode() if isinstance(batch, str) else encode(batch)}
    payload = {'files': {name: b64encode(data).decode() for name, data in files.items()},
               'commands': [step['command'] for step in case['steps']]}
    return files, encode(payload)


def passed(case, files, result):
    from base64 import b64decode
    if result['protected'] != {name: digest(files[name]) for name in ('ledger.py', 'batch.json')}:
        return False
    for step, (status, output) in zip(case['steps'], result['steps'], strict=True):
        if status is None or status < 0 or len(output) > 8192:
            return False
        if step['balances'] is None:
            if status == 0:
                return False
        elif status != 0 or not matches(output, step['balances']):
            return False
    if result['ledger'] is None:
        return False
    ledger = b64decode(result['ledger'], validate=True)
    if case['final'] is None:
        return ledger == files['ledger.json']
    return matches(ledger, case['final'])


def matches(actual, expected):
    try:
        return encode(json.loads(actual)) == encode(expected)
    except (ValueError, RecursionError):
        return False


def apply_controls(checks, outcomes):
    for name, case in checks.items():
        control = case.get('positive_control')
        if control is not None and outcomes[name] == 'passed':
            outcomes[name] = outcomes[control]


def grade_ledger(checks, submission):
    from scripts import isolated

    outcomes = dict.fromkeys(checks, 'error')
    start = time.monotonic()
    profile = None
    bootstrap = isolated.GUEST_CHECKS + DRIVER
    try:
        isolated.verify_machine()
        image = isolated.staged_image()
        profile = {'image': image, 'driver_digest': digest(bootstrap.encode()),
                   'cpu': 1, 'ram_mib': 512, 'processes': 64,
                   'work_mib': 64, 'tmp_mib': 32, 'step_timeout_ms': 3000}
        for name, case in checks.items():
            files, payload = payload_for(case, submission)
            with isolated.container(image, bootstrap) as container:
                result = json.loads(isolated.workload(container, payload))
            outcomes[name] = 'passed' if passed(case, files, result) else 'failed'
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        # Retain completed checks. A stopped sandbox never yields an eligible pass.
        pass
    apply_controls(checks, outcomes)
    return outcomes, profile, round((time.monotonic() - start) * 1000)
