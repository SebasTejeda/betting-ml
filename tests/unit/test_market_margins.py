import pandas as pd
import pytest

from betting_ml.ml.market_margins import best_price_uplift, margin_summary, market_report


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "league": ["E0", "SP1"],
            **{f"avg_odds_{s}": [v, v] for s, v in zip("hda", (1.9, 3.4, 4.0), strict=True)},
            **{f"b365_odds_{s}": [v, v] for s, v in zip("hda", (1.85, 3.3, 3.9), strict=True)},
            **{f"ps_odds_{s}": [v, v] for s, v in zip("hda", (1.95, 3.5, 4.2), strict=True)},
            **{f"max_odds_{s}": [v, None] for s, v in zip("hda", (2.0, 3.6, 4.4), strict=True)},
        }
    )


def test_margins_and_uplift() -> None:
    margins = margin_summary(_frame())
    assert margins["avg"]["margin_mean"] == pytest.approx(1 / 1.9 + 1 / 3.4 + 1 / 4.0 - 1)
    assert margins["max"]["n_matches"] == 1
    uplift = best_price_uplift(_frame(), "avg")
    expected = ((2.0 / 1.9) + (3.6 / 3.4) + (4.4 / 4.0)) / 3 - 1
    assert uplift["n_quotes"] == 3 and uplift["uplift_mean"] == pytest.approx(expected)
    report = market_report(_frame())
    assert set(report["by_league"]) == {"E0", "SP1"}
    assert report["best_vs_b365"]["uplift_mean"] > report["best_vs_avg"]["uplift_mean"]
