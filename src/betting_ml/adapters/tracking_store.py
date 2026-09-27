"""Tracking of served predictions: data/tracking/predictions.parquet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

KEY = ["match_id", "model_version"]


class ParquetTrackingStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        return pd.read_parquet(self.path)

    def save(self, frame: pd.DataFrame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.path, index=False)

    def append(self, records: pd.DataFrame) -> int:
        """Idempotent by match + model version: the first prediction served is kept."""
        current = self.load()
        combined = records if current.empty else pd.concat([current, records], ignore_index=True)
        combined = combined.drop_duplicates(KEY, keep="first").reset_index(drop=True)
        self.save(combined)
        return len(combined) - len(current)
