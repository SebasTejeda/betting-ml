"""Reads generated JSON reports from reports/ (ReportStore port)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# A plain file name: no directories, no traversal, only .json.
REPORT_NAME = re.compile(r"^[A-Za-z0-9_-]+\.json$")


class JsonReportStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def read_json(self, name: str) -> dict[str, Any] | None:
        if not REPORT_NAME.match(name):
            raise ValueError(f"invalid report name {name!r}")
        path = self.root / name
        if not path.exists():
            return None
        content = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            raise ValueError(f"{name} must contain a JSON object")
        return content
