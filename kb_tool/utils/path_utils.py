from __future__ import annotations

import fnmatch
import os
from pathlib import Path


def to_posix_path(path: str) -> str:
    return path.replace('\\', '/')


def norm_abs(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def matches_any_glob(path: str, patterns: list[str]) -> bool:
    # Use POSIX-like matching for stability
    posix = to_posix_path(path)
    for pat in patterns:
        if fnmatch.fnmatch(posix, pat) or fnmatch.fnmatch(os.path.basename(posix), pat):
            return True
    return False
