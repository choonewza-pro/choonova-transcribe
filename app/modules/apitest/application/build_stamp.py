"""
Build fingerprint for the API Endpoint Self-Test module.

The self-test pass/fail status is persisted in SQLite so it survives a plain
server restart. A NEW build must invalidate it (a new build must be re-tested),
even though the SQLite data directory (./data:/app/data) is mounted into the
container and therefore persists. We detect a new build by fingerprinting the
deployed application source at startup: when the stored fingerprint differs
from the current one, all statuses are reset to "not tested".
"""

import hashlib
import os
from typing import List, Optional

from app.core.config import BASE_DIR, SERVICE_DIR
from app.modules.apitest.domain.ports import SelfTestStatusRepository

_EXTRA_FINGERPRINT_PATHS: List[str] = [
    os.path.join(SERVICE_DIR, "requirements.txt"),
    os.path.join(SERVICE_DIR, "requirements-cpu.txt"),
]


def _iter_source_files(source_dir: str) -> List[str]:
    files: List[str] = []
    for root, dirs, names in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                files.append(os.path.join(root, name))
    return sorted(files)


def compute_build_fingerprint(source_dir: Optional[str] = None) -> str:
    """sha256 over the deployed application source (code + requirements).

    Stable across plain restarts of the same build; changes whenever the
    deployed code changes (i.e. a new build).
    """
    source_dir = source_dir or BASE_DIR
    hasher = hashlib.sha256()
    for path in _iter_source_files(source_dir):
        try:
            with open(path, "rb") as fh:
                hasher.update(path.encode("utf-8"))
                hasher.update(fh.read())
        except OSError:
            continue
    for path in _EXTRA_FINGERPRINT_PATHS:
        try:
            with open(path, "rb") as fh:
                hasher.update(path.encode("utf-8"))
                hasher.update(fh.read())
        except OSError:
            continue
    return hasher.hexdigest()


def reset_self_test_status_on_new_build(
    repo: SelfTestStatusRepository,
    fingerprint: Optional[str] = None,
) -> bool:
    """Reset the persisted self-test statuses when the deployed code changed.

    Returns True when a reset happened (i.e. this is a new build); False on a
    plain restart of the same build.
    """
    current = fingerprint or compute_build_fingerprint()
    stored = repo.get_build_stamp()
    if stored != current:
        repo.clear_all()
        repo.set_build_stamp(current)
        return True
    return False