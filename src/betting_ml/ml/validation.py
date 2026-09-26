"""Walk-forward validation by season with an expanding window (plan.md §5)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pandas as pd

N_VALIDATION_FOLDS = 3


@dataclass(frozen=True)
class Fold:
    name: str
    train_seasons: tuple[str, ...]
    valid_season: str

    def split(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        train = frame[frame["season"].isin(self.train_seasons)]
        valid = frame[frame["season"] == self.valid_season]
        check_temporal_order(train, valid)
        return train, valid

    def inner(self) -> Fold:
        """Internal validation for tuning inside the fold: the last training season."""
        if len(self.train_seasons) < 2:
            raise ValueError("need at least two training seasons for an inner split")
        return Fold(f"{self.name}-inner", self.train_seasons[:-1], self.train_seasons[-1])


def check_temporal_order(train: pd.DataFrame, valid: pd.DataFrame) -> None:
    if train.empty or valid.empty:
        raise ValueError("empty train or validation set")
    overlap = set(train["match_id"]) & set(valid["match_id"])
    if overlap:
        raise ValueError(f"{len(overlap)} matches in both train and validation")
    if not train["date"].max() < valid["date"].min():
        raise ValueError("training data must end before validation starts")


def walk_forward_folds(
    train_seasons: Sequence[str], n_folds: int = N_VALIDATION_FOLDS
) -> list[Fold]:
    """F1..Fn: each fold validates on one of the last ``n_folds`` seasons, training on all
    earlier ones. With 2014-15..2024-25: F1 valid 2022-23, F2 2023-24, F3 2024-25."""
    seasons = sorted(train_seasons)
    if len(seasons) <= n_folds:
        raise ValueError("not enough seasons for walk-forward validation")
    folds = []
    for i in range(n_folds, 0, -1):
        valid = seasons[-i]
        folds.append(Fold(f"F{n_folds - i + 1}", tuple(seasons[:-i]), valid))
    return folds


def final_split(train_seasons: Sequence[str], holdout_season: str) -> Fold:
    """Train on every training season and evaluate once on the holdout (experiments.md §6)."""
    seasons = tuple(sorted(train_seasons))
    if holdout_season <= seasons[-1]:
        raise ValueError("holdout must be after every training season")
    return Fold("final", seasons, holdout_season)


def iter_splits(
    frame: pd.DataFrame, folds: Sequence[Fold]
) -> Iterator[tuple[Fold, pd.DataFrame, pd.DataFrame]]:
    for fold in folds:
        train, valid = fold.split(frame)
        yield fold, train, valid
