"""Evaluation metrics for 1X2 probabilistic forecasts.

Probabilities are ``(n, 3)`` arrays with columns ``[H, D, A]``; targets are integer class
indices ``0=H, 1=D, 2=A``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

EPS = 1e-15


def _validate(y_true: ArrayLike, proba: ArrayLike) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    y = np.asarray(y_true, dtype=np.int64)
    p = np.asarray(proba, dtype=float)
    if p.ndim != 2 or p.shape[0] != y.shape[0]:
        raise ValueError(f"shape mismatch: y {y.shape}, proba {p.shape}")
    if y.size == 0:
        raise ValueError("empty input")
    if y.min() < 0 or y.max() >= p.shape[1]:
        raise ValueError("labels out of range")
    return y, p


def _one_hot(y: NDArray[np.int64], n_classes: int) -> NDArray[np.float64]:
    return np.eye(n_classes)[y]


def log_loss(y_true: ArrayLike, proba: ArrayLike) -> float:
    """Multiclass cross-entropy (natural log). Rows are renormalised after clipping."""
    y, p = _validate(y_true, proba)
    p = np.clip(p, EPS, 1 - EPS)
    p = p / p.sum(axis=1, keepdims=True)
    return float(-np.mean(np.log(p[np.arange(y.size), y])))


def brier_score(y_true: ArrayLike, proba: ArrayLike) -> float:
    """Multiclass Brier score: mean over matches of the squared error summed over classes
    (range 0–2; equals ``sklearn.metrics.brier_score_loss(..., scale_by_half=False)``)."""
    y, p = _validate(y_true, proba)
    return float(np.mean(np.sum((p - _one_hot(y, p.shape[1])) ** 2, axis=1)))


def ranked_probability_score(y_true: ArrayLike, proba: ArrayLike) -> float:
    """RPS for ordered outcomes (H < D < A): mean of
    ``sum_k (cumP_k - cumO_k)^2 / (r - 1)``."""
    y, p = _validate(y_true, proba)
    cum_p = np.cumsum(p, axis=1)[:, :-1]
    cum_o = np.cumsum(_one_hot(y, p.shape[1]), axis=1)[:, :-1]
    return float(np.mean(np.sum((cum_p - cum_o) ** 2, axis=1) / (p.shape[1] - 1)))


def expected_calibration_error(y_true: ArrayLike, proba: ArrayLike, n_bins: int = 10) -> float:
    """Top-label ECE with equal-width bins: sum_b |B_b|/n * |acc(B_b) - conf(B_b)|."""
    y, p = _validate(y_true, proba)
    confidence = p.max(axis=1)
    correct = (p.argmax(axis=1) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins = np.clip(np.digitize(confidence, edges[1:-1], right=True), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if mask.any():
            ece += mask.mean() * abs(correct[mask].mean() - confidence[mask].mean())
    return float(ece)


def accuracy(y_true: ArrayLike, proba: ArrayLike) -> float:
    y, p = _validate(y_true, proba)
    return float(np.mean(p.argmax(axis=1) == y))


@dataclass(frozen=True)
class MetricSet:
    log_loss: float
    brier: float
    rps: float
    ece: float
    accuracy: float
    n: int

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def evaluate(y_true: ArrayLike, proba: ArrayLike, n_bins: int = 10) -> MetricSet:
    y, p = _validate(y_true, proba)
    return MetricSet(
        log_loss=log_loss(y, p),
        brier=brier_score(y, p),
        rps=ranked_probability_score(y, p),
        ece=expected_calibration_error(y, p, n_bins),
        accuracy=accuracy(y, p),
        n=int(y.size),
    )
