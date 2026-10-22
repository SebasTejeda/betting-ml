"""`ModelRegistry` on disk: models/{version}/model.joblib + metadata.json.

``metadata.json`` records the SHA-256 of ``model.joblib`` (spec 003, US6) and is versioned in
git, so a new or changed hash shows up in review. ``load`` refuses a model whose bytes do not
match it before unpickling anything.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any

import joblib

from betting_ml.domain.security import ModelIntegrityError

MODEL_FILE = "model.joblib"
METADATA_FILE = "metadata.json"
HASH_KEY = "sha256"
_SHA256 = re.compile(r"[0-9a-f]{64}")
CHUNK = 1 << 20


class JoblibModelRegistry:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir

    def path(self, version: str) -> Path:
        return self.models_dir / version

    def save(self, version: str, model: Any, metadata: dict[str, Any]) -> None:
        target = self.path(version)
        target.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, target / MODEL_FILE, compress=3)
        self._write_metadata(version, {**metadata, HASH_KEY: self.artifact_sha256(version)})

    def load(self, version: str) -> tuple[Any, dict[str, Any]]:
        target = self.path(version)
        if not (target / MODEL_FILE).exists():
            raise FileNotFoundError(f"model version {version!r} not found in {self.models_dir}")
        try:
            metadata = self.load_metadata(version)
        except ValueError as exc:  # truncated or not JSON
            raise ModelIntegrityError(version, "metadata.json ilegible") from exc
        expected = metadata.get(HASH_KEY)
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise ModelIntegrityError(
                version, "metadata.json no registra su SHA-256 (revísalo y usa models-rehash)"
            )
        # Hash and unpickle the very same bytes: the file cannot change in between.
        data = (target / MODEL_FILE).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ModelIntegrityError(version, "el SHA-256 de model.joblib no coincide")
        return joblib.load(io.BytesIO(data)), metadata

    def load_metadata(self, version: str) -> dict[str, Any]:
        metadata: dict[str, Any] = json.loads(
            (self.path(version) / METADATA_FILE).read_text(encoding="utf-8")
        )
        return metadata

    def list_versions(self) -> list[str]:
        if not self.models_dir.exists():
            return []
        return sorted(p.parent.name for p in self.models_dir.glob(f"*/{MODEL_FILE}"))

    # ------------------------------------------------------------------ hashes (ModelHashes)
    def artifact_sha256(self, version: str) -> str:
        digest = hashlib.sha256()
        with (self.path(version) / MODEL_FILE).open("rb") as file:
            while chunk := file.read(CHUNK):
                digest.update(chunk)
        return digest.hexdigest()

    def recorded_sha256(self, version: str) -> str | None:
        recorded = self.load_metadata(version).get(HASH_KEY)
        return recorded if isinstance(recorded, str) else None

    def record_sha256(self, version: str, digest: str) -> None:
        self._write_metadata(version, {**self.load_metadata(version), HASH_KEY: digest})

    def _write_metadata(self, version: str, metadata: dict[str, Any]) -> None:
        """Written next to it and swapped in: an interrupted write never leaves half a file."""
        target = self.path(version) / METADATA_FILE
        partial = target.with_name(f".{METADATA_FILE}.partial")
        partial.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(partial, target)
