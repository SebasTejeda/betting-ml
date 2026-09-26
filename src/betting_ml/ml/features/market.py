"""Market features: margin-free implied probabilities of PRE-closing odds only
(constitution §I.2–3). Closing odds are never features."""

from __future__ import annotations

import pandas as pd

from betting_ml.config import MarketConfig
from betting_ml.domain.odds import normalize, overround

PRE_CLOSING_SOURCES = ("avg", "ps", "b365")
MARKET_COLUMNS = ["mkt_p_home", "mkt_p_draw", "mkt_p_away", "mkt_overround"]


def odds_columns(source: str) -> list[str]:
    if source not in PRE_CLOSING_SOURCES:
        raise ValueError(f"{source!r} is not a pre-closing odds source {PRE_CLOSING_SOURCES}")
    return [f"{source}_odds_{side}" for side in ("h", "d", "a")]


def market_features(matches: pd.DataFrame, config: MarketConfig | None = None) -> pd.DataFrame:
    config = config or MarketConfig()
    odds = matches[odds_columns(config.source)].to_numpy(dtype=float)
    probs = normalize(odds, config.method)
    out = pd.DataFrame(probs, index=matches.index, columns=MARKET_COLUMNS[:3])
    out["mkt_overround"] = overround(odds)
    return out
