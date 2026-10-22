import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from betting_ml.adapters.parquet_repository import HoldoutAccessError, ParquetMatchRepository
from betting_ml.application.validate_cross_league import (
    DEFAULT_RIDGE,
    RIDGE_GRID,
    ValidateCrossLeague,
    choose_ridge,
    match_metrics,
)
from betting_ml.ml.models.cross_league import (
    CrossLeagueModel,
    FrequencyModel,
    MissingRatingsError,
    eligible,
)

TRUE_OFFSETS = {"E0": 0.25, "SP1": 0.2, "NED": -0.2, "POR": -0.1}


def _european(
    n: int = 3000, seed: int = 0, seasons: tuple[str, ...] = ("2020-21",)
) -> pd.DataFrame:
    """European matches where every league mean Elo is 1500: the Elo is blind to the true gap."""
    rng = np.random.default_rng(seed)
    leagues = np.array(list(TRUE_OFFSETS))
    hl, al = rng.choice(leagues, n), rng.choice(leagues, n)
    sh, sa = rng.normal(0, 100, n), rng.normal(0, 100, n)
    xh = 0.8 * sh / 400 + np.array([TRUE_OFFSETS[c] for c in hl])
    xa = 0.8 * sa / 400 + np.array([TRUE_OFFSETS[c] for c in al])
    season = np.resize(np.array(seasons), n)
    return pd.DataFrame(
        {
            "match_id": [f"m{i}" for i in range(n)],
            "season": season,
            "date": pd.Timestamp("2018-09-01") + pd.to_timedelta(np.arange(n) // 10, unit="D"),
            "home_league": hl,
            "away_league": al,
            "home_league_elo": 1500.0,
            "away_league_elo": 1500.0,
            "home_elo": 1500.0 + sh,
            "away_elo": 1500.0 + sa,
            "home_goals": rng.poisson(np.exp(0.2 + 0.25 + xh - xa)),
            "away_goals": rng.poisson(np.exp(0.2 + xa - xh)),
        }
    )


def test_recovers_league_offsets_the_elo_does_not_see() -> None:
    model = CrossLeagueModel(ridge=1.0).fit(_european())
    est = model.offsets
    assert est["E0"] - est["NED"] == pytest.approx(0.45, abs=0.08)
    assert est["SP1"] > est["POR"] > est["NED"]
    assert model.gamma == pytest.approx(0.25, abs=0.06)
    assert model.a == pytest.approx(0.8, abs=0.15)
    raw = CrossLeagueModel(mode="raw").fit(_european())
    assert raw.offsets == {}


def test_matrices_and_rates() -> None:
    data = _european(200)
    model = CrossLeagueModel().fit(data)
    mats = model.score_matrices(data.head(5))
    assert mats.shape == (5, 11, 11)
    np.testing.assert_allclose(mats.sum(axis=(1, 2)), 1.0)
    # A stronger home club gets more expected goals.
    strong = data.head(1).assign(home_elo=1800.0, away_elo=1300.0)
    weak = data.head(1).assign(home_elo=1300.0, away_elo=1800.0)
    assert model.rates(strong)[0][0] > model.rates(weak)[0][0]
    # Unknown league at prediction time: offset 0 (only its mean Elo counts).
    other = data.head(1).assign(home_league="XXX")
    assert np.isfinite(model.rates(other)[0]).all()


def test_ridge_shrinks_offsets() -> None:
    data = _european(400)
    loose = CrossLeagueModel(ridge=0.1).fit(data).offsets
    tight = CrossLeagueModel(ridge=1000.0).fit(data).offsets
    assert max(abs(v) for v in tight.values()) < max(abs(v) for v in loose.values())


def test_missing_ratings() -> None:
    data = _european(10)
    data.loc[0, "home_league_elo"] = np.nan
    assert len(eligible(data)) == 9
    with pytest.raises(MissingRatingsError):
        CrossLeagueModel().fit(data)
    with pytest.raises(ValueError):
        CrossLeagueModel().fit(data.drop(columns=["home_league"]))


def test_frequency_model_and_metrics() -> None:
    data = _european(300)
    freq = FrequencyModel().fit(data)
    mats = freq.score_matrices(data)
    m = match_metrics(mats, data)
    assert m["n"] == 300
    assert m["expected_goals"] == pytest.approx(
        data["home_goals"].mean() + data["away_goals"].mean(), abs=0.05
    )
    better = match_metrics(CrossLeagueModel().fit(data).score_matrices(data), data)
    assert better["log_loss_1x2"] < m["log_loss_1x2"]


def test_choose_ridge_uses_only_training_seasons() -> None:
    data = _european(1500, seasons=("2018-19", "2019-20", "2020-21"))
    assert choose_ridge(data) in RIDGE_GRID
    assert choose_ridge(data[data["season"] == "2019-20"]) == DEFAULT_RIDGE  # one season


def test_eligibility_rules() -> None:
    data = _european(6).assign(
        home_recent=12, away_recent=12, home_days_since_league=5, away_days_since_league=5
    )
    data.loc[0, "home_recent"] = 9  # fewer than 10 rated matches in the previous year
    data.loc[1, "away_days_since_league"] = 75  # league file stopped: frozen league part
    data.loc[2, "away_league_elo"] = np.nan  # club from a country outside the catalog
    assert eligible(data)["match_id"].tolist() == ["m3", "m4", "m5"]


def test_validate_cross_league_use_case(tmp_path: Path) -> None:
    seasons = ("2016-17", "2017-18", "2018-19", "2019-20", "2020-21")
    data = _european(2500, seasons=seasons).sort_values("season")
    data["date"] = pd.to_datetime([f"{s[:4]}-10-01" for s in data["season"]])
    repository = ParquetMatchRepository(tmp_path / "processed")
    repository.save("europe_matches", data)
    repository.save("europe_holdout", data.head(5))
    result = ValidateCrossLeague(repository, tmp_path / "reports").run()
    assert set(result.by_season) == {"2018-19", "2019-20", "2020-21"}
    assert result.chosen == "M2"  # the Elo is blind to the league gap: offsets must help
    assert result.mean["M2"]["log_loss_1x2"] < result.mean["M0"]["log_loss_1x2"]
    payload = json.loads(
        (tmp_path / "reports" / "market_validation_003_europe.json").read_text(encoding="utf-8")
    )
    assert set(payload["levels"]) == {"h2h", "totals:2.5"}
    assert (tmp_path / "reports" / "figures" / "003_calibration_europe.png").exists()
    with pytest.raises(HoldoutAccessError):
        repository.load("europe_holdout")
