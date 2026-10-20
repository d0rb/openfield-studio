"""Small filesystem helpers that behave on Windows as well as on Linux."""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def replace_file(src: str | os.PathLike[str], dst: str | os.PathLike[str], *, attempts: int = 30) -> None:
    """`os.replace` that rides out a reader holding the destination open.

    On Windows a replace fails with PermissionError while anything has the target open: the interface
    polling a take, an antivirus scan, a sync client. The holder lets go within moments, so retry with a
    short backoff (about six seconds in all) and only then give up.
    """
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(0.01 * 2**attempt, 0.25))


def retry_read(read: Callable[[], T], *, attempts: int = 20) -> T:
    """Run a read that may hit a file momentarily locked by a writer (Windows), retrying briefly."""
    for attempt in range(attempts):
        try:
            return read()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(min(0.01 * 2**attempt, 0.1))
    raise AssertionError("unreachable")  # pragma: no cover


def read_text(path: Path, encoding: str = "utf-8") -> str:
    return retry_read(lambda: Path(path).read_text(encoding=encoding))
