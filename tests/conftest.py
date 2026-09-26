"""Shared test helpers: a synthetic league with known team strengths."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from betting_ml.domain.entities import make_match_id


def make_synthetic_matches(
    n_teams: int = 8,
    seasons: tuple[str, ...] = ("2019-20", "2020-21", "2021-22"),
    league: str = "E0",
    seed: int = 42,
    home_advantage: float = 0.25,
    relegate: int = 0,
) -> pd.DataFrame:
    """Double round-robin per season with Poisson goals from attack/defence strengths.

    With ``relegate > 0`` the worst ``relegate`` teams are replaced by new ones each season.
    """
    rng = np.random.default_rng(seed)
    teams = [f"Team {i:02d}" for i in range(n_teams)]
    attack = dict(zip(teams, rng.normal(0, 0.3, n_teams), strict=True))
    defence = dict(zip(teams, rng.normal(0, 0.3, n_teams), strict=True))
    rows = []
    next_team = n_teams
    for s_idx, season in enumerate(seasons):
        start = pd.Timestamp(f"{season[:4]}-08-10")
        pairs = [(h, a) for h in teams for a in teams if h != a]
        rng.shuffle(pairs)
        per_day = max(1, n_teams // 2)
        day = 0
        scheduled = []
        remaining = list(pairs)
        while remaining:
            used: set[str] = set()
            today = []
            for pair in list(remaining):
                if pair[0] in used or pair[1] in used or len(today) >= per_day:
                    continue
                today.append(pair)
                used.update(pair)
                remaining.remove(pair)
            scheduled.extend((day, h, a) for h, a in today)
            day += 7
        for day, home, away in scheduled:
            date = start + pd.Timedelta(days=day)
            lam_h = np.exp(0.2 + home_advantage + attack[home] - defence[away])
            lam_a = np.exp(0.2 + attack[away] - defence[home])
            hg, ag = rng.poisson(lam_h), rng.poisson(lam_a)
            fair = np.array([0.45, 0.27, 0.28]) + rng.normal(0, 0.05, 3)
            fair = np.clip(fair, 0.05, None)
            fair = fair / fair.sum()
            rows.append(
                {
                    "match_id": make_match_id(league, date.date(), home, away),
                    "league": league,
                    "season": season,
                    "date": date,
                    "kickoff_utc": (date + pd.Timedelta(hours=15)).tz_localize("UTC"),
                    "home_team": home,
                    "away_team": away,
                    "home_goals": int(hg),
                    "away_goals": int(ag),
                    "result": "H" if hg > ag else "A" if hg < ag else "D",
                    "home_shots": int(hg * 3 + rng.integers(4, 12)),
                    "away_shots": int(ag * 3 + rng.integers(3, 10)),
                    "home_sot": int(hg + rng.integers(1, 5)),
                    "away_sot": int(ag + rng.integers(1, 4)),
                    "home_xg": float(lam_h * rng.uniform(0.8, 1.2)),
                    "away_xg": float(lam_a * rng.uniform(0.8, 1.2)),
                    **{
                        f"{p}_odds_{s}": float(1 / (fair[i] * m))
                        for p, m in (("avg", 1.05), ("max", 1.0), ("ps", 1.025), ("b365", 1.05))
                        for i, s in enumerate("hda")
                    },
                    **{
                        f"{p}_odds_{s}": float(1 / (fair[i] * 1.025))
                        for p in ("psc", "avgc")
                        for i, s in enumerate("hda")
                    },
                }
            )
        if relegate and s_idx < len(seasons) - 1:
            points: dict[str, int] = dict.fromkeys(teams, 0)
            for r in rows[-len(scheduled) :]:
                if r["result"] == "H":
                    points[r["home_team"]] += 3
                elif r["result"] == "A":
                    points[r["away_team"]] += 3
                else:
                    points[r["home_team"]] += 1
                    points[r["away_team"]] += 1
            worst = sorted(teams, key=lambda t: points[t])[:relegate]
            for team in worst:
                new = f"Team {next_team:02d}"
                next_team += 1
                attack[new], defence[new] = rng.normal(-0.2, 0.2), rng.normal(-0.2, 0.2)
                teams[teams.index(team)] = new
    return pd.DataFrame(rows).sort_values(["date", "home_team"]).reset_index(drop=True)


@pytest.fixture
def synthetic_matches() -> pd.DataFrame:
    return make_synthetic_matches()
