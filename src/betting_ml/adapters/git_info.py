"""Git metadata for experiment traceability."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from betting_ml.config import PROJECT_ROOT


def current_commit(root: Path = PROJECT_ROOT) -> str:
    """Short hash of HEAD, with ``-dirty`` when code or configs (tracked or new) differ."""
    git = shutil.which("git")  # an absolute path: never whatever "git" the cwd provides
    if git is None:
        return "unknown"
    try:
        sha = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [git, "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            [git, "status", "--porcelain", "--", "src", "configs", "pyproject.toml"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
