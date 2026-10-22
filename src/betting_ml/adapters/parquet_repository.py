"""Parquet implementation of `MatchRepository` (data/processed/{name}.parquet)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HOLDOUT_NAME = "holdout"
# Every dataset of the 2025-26 holdout (spec 001 leagues; spec 003 European competitions).
HOLDOUT_NAMES = frozenset({HOLDOUT_NAME, "europe_holdout"})


class HoldoutAccessError(PermissionError):
    pass


class ParquetMatchRepository:
    def __init__(self, processed_dir: Path, allow_holdout: bool = False) -> None:
        self.processed_dir = processed_dir
        self.allow_holdout = allow_holdout

    def path(self, name: str) -> Path:
        return self.processed_dir / f"{name}.parquet"

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def save(self, name: str, frame: pd.DataFrame) -> None:
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.path(name), index=False)

    def load(self, name: str) -> pd.DataFrame:
        if name in HOLDOUT_NAMES and not self.allow_holdout:
            raise HoldoutAccessError(
                "The holdout can only be read by the final evaluation (constitution §II)."
            )
        path = self.path(name)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `make data` first")
        return pd.read_parquet(path)
