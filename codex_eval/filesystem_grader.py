"""Grade a model script against a bounded inventory of synthetic files."""
from base64 import b64encode
from pathlib import PurePosixPath
import re

from .regression_grader import digest, encode, grade_in_sandbox

DRIVER = r'''
import base64, ctypes, hashlib, json, os, resource, signal, stat, subprocess, sys
from pathlib import Path

libc = ctypes.CDLL(None, use_errno=True)
assert libc.prctl(4, 0, 0, 0, 0) == 0  # PR_SET_DUMPABLE
for name, size_mib in (('/work', 64), ('/tmp', 32)):
    mount = os.statvfs(name)
    flags = os.ST_NOSUID | os.ST_NODEV | os.ST_NOEXEC
    assert mount.f_blocks * mount.f_frsize == size_mib * 1024**2
    assert mount.f_flag & flags == flags
assert not any(Path(path).exists() for path in (
    '/Users', '/run/podman/podman.sock', '/var/run/docker.sock',
))
os.umask(0o077)
resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))

root = Path('/work/fixture')
root.mkdir()
program = Path('/work/organize.py')
canary = Path('/work/outside-fixture.txt')
canary.write_bytes(b'synthetic outside fixture')
payload = json.load(sys.stdin)
source_code = base64.b64decode(payload['submission'], validate=True)
program.write_bytes(source_code)
for name, content in payload['files'].items():
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


class PathRule(ctypes.Structure):
    _layout_ = 'ms'
    _pack_ = 1
    _fields_ = [('access', ctypes.c_uint64), ('parent', ctypes.c_int32)]


def restrict_candidate():
    # An unprivileged child cannot raise this limit or spawn descendants.
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    assert os.uname().machine in ('aarch64', 'x86_64')
    # Landlock ABI 3 covers truncation and cross-directory moves.
    create, add, restrict = 444, 445, 446
    if libc.syscall(create, None, 0, 1) < 3:
        raise RuntimeError('Landlock ABI 3 required')
    handled = ctypes.c_uint64((1 << 1) | sum(1 << bit for bit in range(4, 15)))
    permitted = sum(1 << bit for bit in (1, 4, 5, 7, 8, 13, 14))
    fd = libc.syscall(create, ctypes.byref(handled), ctypes.sizeof(handled), 0)
    if fd < 0:
        raise RuntimeError('Could not create Landlock ruleset')
    parent = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        rule = PathRule(permitted, parent)
        if libc.syscall(add, fd, 1, ctypes.byref(rule), 0) or libc.syscall(restrict, fd, 0):
            raise RuntimeError('Could not enforce Landlock ruleset')
    finally:
        os.close(parent)
        os.close(fd)


def inventory():
    entries = {}

    def scan(fd, prefix='', depth=0):
        if depth > 6:
            raise ValueError('Fixture depth exceeded')
        with os.scandir(fd) as children:
            for entry in children:
                if len(entries) >= 96:
                    raise ValueError('Fixture entry limit exceeded')
                name = prefix + entry.name
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(metadata.st_mode):
                    entries[name] = ['dir', stat.S_IMODE(metadata.st_mode)]
                    child = os.open(entry.name, os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        scan(child, name + '/', depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    with os.fdopen(child, 'rb') as stream:
                        data = stream.read(4097)
                    if len(data) > 4096:
                        raise ValueError('Fixture file limit exceeded')
                    entries[name] = ['file', stat.S_IMODE(metadata.st_mode), hashlib.sha256(data).hexdigest()]
                else:
                    raise ValueError('Unexpected fixture entry type')

    fd = os.open(root, os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            raise ValueError('Fixture root permissions changed')
        scan(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


observations = []
for _ in range(2):
    with subprocess.Popen([sys.executable, '-I', '-B', str(program), str(root)],
                          cwd=root, env={'LANG': 'C.UTF-8'}, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          start_new_session=True, preexec_fn=restrict_candidate) as proc:
        try:
            status = proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            status = None
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    try:
        tree = inventory() if status == 0 else None
    except (OSError, ValueError):
        tree = None
    observations.append([status, tree])
    if tree is None:
        break
outside_intact = all(
    stat.S_IMODE(path.lstat().st_mode) == 0o600 and path.read_bytes() == expected
    for path, expected in ((canary, b'synthetic outside fixture'), (program, source_code))
)
print(json.dumps({'observations': observations, 'canary_intact': outside_intact}))
'''


def fixture_path(name):
    if not isinstance(name, str) or len(name) > 128 or not re.fullmatch(
        r'[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*){0,5}', name
    ):
        raise ValueError('Invalid synthetic fixture path')
    return PurePosixPath(name)


def prepare(case, submission):
    files, moves = case['files'], case['moves']
    if not 1 <= len(files) <= 32 or not moves.keys() <= files.keys():
        raise ValueError('Invalid synthetic fixture inventory')
    expected, directories = {}, set()
    for name, contents in files.items():
        source = fixture_path(name)
        target = fixture_path(moves.get(name, name))
        if str(target) in expected or len(contents.encode()) > 4096:
            raise ValueError('Invalid synthetic fixture file')
        expected[str(target)] = ['file', 0o600, digest(contents.encode())]
        directories.update(str(parent) for path in (source, target) for parent in path.parents if parent.parts)
    if directories & expected.keys():
        raise ValueError('Invalid synthetic fixture directory')
    expected.update(dict.fromkeys(directories, ['dir', 0o700]))
    payload = {'submission': b64encode(submission).decode(), 'files': files}
    return digest(encode(expected)), encode(payload)


def passed(case, expected, result):
    return result['canary_intact'] is True and result['observations'] == [[0, expected], [0, expected]]


def grade_filesystem(checks, submission):
    return grade_in_sandbox(checks, submission, DRIVER, prepare, passed)
