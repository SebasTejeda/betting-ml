"""Git metadata for experiment traceability."""

from __future__ import annotations

import subprocess
from pathlib import Path

from betting_ml.config import PROJECT_ROOT


def current_commit(root: Path = PROJECT_ROOT) -> str:
    """Short hash of HEAD, with ``-dirty`` when code or configs (tracked or new) differ."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "configs", "pyproject.toml"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha
