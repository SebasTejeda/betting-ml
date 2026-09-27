"""`ModelRegistry` on disk: models/{version}/model.joblib + metadata.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib


class JoblibModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir

    def path(self, version: str) -> Path:
        return self.models_dir / version

    def save(self, version: str, model: Any, metadata: dict[str, Any]) -> None:
        target = self.path(version)
        target.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, target / "model.joblib", compress=3)
        (target / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def load(self, version: str) -> tuple[Any, dict[str, Any]]:
        target = self.path(version)
        if not (target / "model.joblib").exists():
            raise FileNotFoundError(f"model version {version!r} not found in {self.models_dir}")
        metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
        return joblib.load(target / "model.joblib"), metadata

    def load_metadata(self, version: str) -> dict[str, Any]:
        return json.loads((self.path(version) / "metadata.json").read_text(encoding="utf-8"))

    def list_versions(self) -> list[str]:
        if not self.models_dir.exists():
            return []
        return sorted(p.parent.name for p in self.models_dir.glob("*/model.joblib"))
