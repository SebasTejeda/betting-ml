"""Figures: reliability (calibration) diagram and cumulative ROI of the betting simulation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from betting_ml.ml.betting import BetResult

LABELS = ("Local", "Empate", "Visita")
COLORS = ("#2a6f97", "#6c757d", "#c9184a")


def calibration_plot(
    y: np.ndarray, proba: np.ndarray, path: Path, title: str, n_bins: int = 10
) -> Path:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], ls="--", color="#adb5bd", lw=1)
    edges = np.linspace(0, 1, n_bins + 1)
    for k, (label, color) in enumerate(zip(LABELS, COLORS, strict=True)):
        p = proba[:, k]
        bins = np.clip(np.digitize(p, edges[1:-1], right=True), 0, n_bins - 1)
        xs, ys, ns = [], [], []
        for b in range(n_bins):
            mask = bins == b
            if mask.sum() >= 10:
                xs.append(p[mask].mean())
                ys.append((y[mask] == k).mean())
                ns.append(mask.sum())
        ax.plot(xs, ys, marker="o", color=color, label=label)
    ax.set_xlabel("Probabilidad predicha")
    ax.set_ylabel("Frecuencia observada")
    ax.set_title(title)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left")
    fig.tight_layout()
    return _save(fig, path)


def roi_plot(results: Sequence[BetResult], path: Path, title: str) -> Path:
    fig, ax = plt.subplots(figsize=(7, 4))
    for result in results:
        if not result.cumulative_profit:
            continue
        label = (
            f"{'Realista (avg)' if result.scenario == 'avg' else 'Optimista (max)'} — "
            f"{result.n_bets} apuestas, ROI {result.roi_flat:+.1%}"
        )
        ax.plot(np.arange(1, result.n_bets + 1), result.cumulative_profit, label=label)
    ax.axhline(0, color="#adb5bd", lw=1)
    ax.set_xlabel("Nº de apuesta (orden cronológico)")
    ax.set_ylabel("Beneficio acumulado (unidades, stake plano)")
    ax.set_title(title)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
