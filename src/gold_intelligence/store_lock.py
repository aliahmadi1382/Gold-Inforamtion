"""Non-waiting OS lock shared by project writers and consistent store backups."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def store_lock(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError("store directory does not exist")
    path = root / "writer.lock"
    if path.is_symlink():
        raise ValueError("store lock must not be a symbolic link")
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("another writer or backup owns this store") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
