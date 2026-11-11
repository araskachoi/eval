"""Application identity; independent of model, pricing, and storage versions."""
from functools import lru_cache
import json
from pathlib import Path

VERSION = '0.2.0'


@lru_cache(maxsize=1)
def application():
    path = Path(__file__).with_name('_release.json')
    if path.exists():
        data = json.loads(path.read_text())
        return {key: data[key] for key in ('version', 'release_id', 'source_digest', 'git_commit', 'git_dirty')}
    return dict(version=VERSION, release_id='development', source_digest=None, git_commit=None, git_dirty=None)
