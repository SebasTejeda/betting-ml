import json
from pathlib import Path

import pandas as pd
import pytest

from betting_ml.application.select_champion import SelectChampion, eligible, simplicity_rank

SPECS = {
    "E02": {"type": "sklearn", "kind": "logistic", "groups": ["elo"]},
    "E04": {"type": "dixon_coles", "xi": 0.001},
    "E06": {"type": "sklearn", "kind": "logistic", "groups": ["elo", "xg"]},
    "E08": {"type": "optuna_lightgbm", "groups": ["elo", "xg"]},
    "E09": {
        "type": "calibrated",
        "base": {"type": "sklearn", "kind": "xgboost", "groups": ["elo"]},
    },
    "E12": {"type": "optuna_lightgbm", "groups": ["elo", "market"]},
    "E13": {"type": "stacking", "members": []},
}


def _row(exp_id: str, ll: float, ece: float = 0.02, odds: bool = False, folds=None) -> dict:  # type: ignore[no-untyped-def]
    f1, f2, f3 = folds or (ll, ll, ll)
    return {
        "exp_id": exp_id,
        "name": exp_id,
        "model": exp_id,
        "uses_odds": odds,
        "val_ll_f1": f1,
        "val_ll_f2": f2,
        "val_ll_f3": f3,
        "val_ll_mean": ll,
        "val_brier": 0.58,
        "val_rps": 0.2,
        "val_ece": ece,
        "val_acc": 0.5,
        "bet_threshold": 0.05,
    }


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("E01-avg", 0.965, odds=True),
            _row("E02", 0.984),
            _row("E04", 0.986),
            _row("E06", 0.9795, ece=0.025),
            _row("E08", 0.97852),
            _row("E09", 0.970, ece=0.035),  # badly calibrated
            _row("E12", 0.9694, odds=True),
            _row("E13", 0.9690, odds=True, folds=(0.95, 0.96, 0.997)),  # unstable in F3
        ]
    )


def _selector(tmp_path: Path, rows: pd.DataFrame) -> SelectChampion:
    return SelectChampion(
        read_rows=lambda: rows,
        load_details=lambda e: {"spec": SPECS[e], "config": {"feature_overrides": {}}},
        output_path=tmp_path / "models" / "champion.json",
        git_commit=lambda: "abc",
    )


def test_simplicity_order() -> None:
    ranks = [simplicity_rank(SPECS[e]) for e in ("E02", "E04", "E08", "E13")]
    assert ranks == sorted(ranks) and len(set(ranks)) == 4
    assert simplicity_rank(SPECS["E09"]) == simplicity_rank(SPECS["E08"])
    assert simplicity_rank({"type": "blend"}) == 2
    assert simplicity_rank({"type": "market"}) == 0


def test_eligibility_rules() -> None:
    candidates, excluded = eligible(_rows())
    assert set(candidates["exp_id"]) == {"E02", "E04", "E06", "E08", "E12"}
    assert "ECE" in excluded["E09"]
    assert "inestable" in excluded["E13"]
    assert "línea base" in excluded["E01-avg"]
    with pytest.raises(ValueError, match="E02"):
        eligible(_rows()[_rows()["exp_id"] != "E02"])


def test_champion_and_simplicity_tiebreak(tmp_path: Path) -> None:
    selection = _selector(tmp_path, _rows()).run()
    assert selection.champion["experiment_id"] == "E12"
    # E06 (logistic) is within 0.001 of E08 (boosting) -> the simpler model wins.
    assert selection.champion_no_odds["experiment_id"] == "E06"
    assert "simplicidad" in selection.champion_no_odds["reason"]
    payload = json.loads((tmp_path / "models" / "champion.json").read_text(encoding="utf-8"))
    assert payload["champion"]["uses_odds"] is True
    assert payload["champion_no_odds"]["validation_metrics"]["log_loss_by_fold"]["F3"] == 0.9795
    assert payload["git_commit"] == "abc"
    assert payload["candidates"][0]["experiment_id"] == "E12"


def test_no_candidates(tmp_path: Path) -> None:
    rows = pd.DataFrame([_row("E02", 0.98, ece=0.05)])
    with pytest.raises(ValueError, match="no eligible"):
        _selector(tmp_path, rows).run()
