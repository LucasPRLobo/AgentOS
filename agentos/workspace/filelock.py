"""File-based locking for concurrent task operations.

Inspired by Claude Code's proper-lockfile pattern with retry+backoff.
Uses fcntl on Unix for atomic lock acquisition.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_RETRIES = 30
_BASE_DELAY = 0.005  # 5ms
_MAX_DELAY = 0.100   # 100ms


@contextlib.contextmanager
def file_lock(lock_path: Path, timeout: float = 5.0):
    """Acquire a file lock with retry and backoff.

    Usage:
        with file_lock(Path("/tmp/my.lock")):
            # critical section
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    start = time.monotonic()
    delay = _BASE_DELAY

    for attempt in range(_MAX_RETRIES):
        try:
            fd = open(lock_path, "w")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                fd.close()
            return
        except (OSError, BlockingIOError):
            if fd is not None:
                fd.close()
                fd = None
            if time.monotonic() - start > timeout:
                raise TimeoutError(
                    f"Could not acquire lock {lock_path} after {timeout}s"
                )
            time.sleep(delay)
            delay = min(delay * 1.5, _MAX_DELAY)

    raise TimeoutError(f"Could not acquire lock {lock_path} after {_MAX_RETRIES} retries")
