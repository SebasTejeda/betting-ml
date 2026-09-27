"""API tests with TestClient on a synthetic serving environment (contracts/api.md)."""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from betting_ml.api.main import create_app
from betting_ml.application.catalog import RefreshData
from betting_ml.container import ApiServices
from tests.serving import FIXTURE_DAY, ServingEnv, build_serving_env, leagues

API_KEY = "test-key"


@pytest.fixture
def env(tmp_path: Path) -> ServingEnv:
    return build_serving_env(tmp_path)


@pytest.fixture
def refreshed() -> list[str]:
    return []


@pytest.fixture
def client(env: ServingEnv, refreshed: list[str]) -> Iterator[TestClient]:
    experiments = pd.DataFrame(
        [
            {"exp_id": "E02", "val_ll_mean": 0.984, "conclusion": "ok"},
            {"exp_id": "E12", "val_ll_mean": 0.969, "conclusion": None},
        ]
    )
    services = ApiServices(
        predictor=env.predictor,
        tracking=env.tracking,
        leagues=leagues(),
        read_experiments=lambda: experiments,
        admin_api_key=API_KEY,
        refresher=RefreshData(
            refresh_fixtures=lambda: len(env.fixtures.fetch_fixtures(force_refresh=True)),
            rebuild=lambda: refreshed.append("rebuilt"),
            on_done=env.predictor.reset,
        ),
    )
    with TestClient(create_app(services)) as test_client:
        yield test_client


def _assert_error(response, status: int, code: str) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], dict)


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model_version"] == "E12-logistic-2022-09-01"
    assert body["data_last_update"].endswith("Z")


def test_leagues_and_teams(client: TestClient) -> None:
    body = client.get("/api/v1/leagues").json()
    assert body[0] == {"code": "E0", "name": "Toy League", "country": "England", "teams": 8}
    teams = client.get("/api/v1/leagues/E0/teams").json()
    assert len(teams) == 8
    assert teams == sorted(teams, key=lambda t: -t["elo"])
    _assert_error(client.get("/api/v1/leagues/XX/teams"), 404, "LEAGUE_NOT_FOUND")


def test_matches_of_a_day(client: TestClient) -> None:
    body = client.get(
        "/api/v1/matches", params={"date": FIXTURE_DAY.isoformat(), "min_edge": 0}
    ).json()
    assert body["date"] == "2022-09-03"
    assert body["count"] == 3 == len(body["matches"])
    assert body["message"] is None
    for match in body["matches"]:
        probs = match["probabilities"]
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-6)
        assert all(round(v, 4) == v for v in probs.values())
        assert match["over_under_2_5"] is None
        for bet in match["value_bets"]:
            assert bet["outcome"] in ("home", "draw", "away")
            assert bet["expected_value"] == pytest.approx(
                bet["model_probability"] * bet["odds"] - 1, abs=1e-3
            )
            assert 0 <= bet["kelly_fraction"] <= 0.02
    first = body["matches"][0]
    assert first["match_id"] == "E0-2022-09-03-team-00-team-01"
    assert first["kickoff"] == "2022-09-03T14:00:00Z"
    assert first["market"]["source"] == "football-data fixtures.csv"
    assert sum(first["market"]["implied_probabilities"].values()) == pytest.approx(1.0, abs=1e-6)
    assert body["matches"][2]["market"] is None


def test_matches_filters_and_empty_list(client: TestClient) -> None:
    empty = client.get("/api/v1/matches", params={"date": "2022-09-10"})
    assert empty.status_code == 200
    body = empty.json()
    assert body["count"] == 0 and body["matches"] == []
    assert body["message"] == "No hay partidos de las ligas soportadas para 2022-09-10 en la fuente"
    other_league = client.get("/api/v1/matches", params={"date": "2022-09-03", "league": "SP1"})
    assert other_league.json()["count"] == 0
    only_value = client.get(
        "/api/v1/matches", params={"date": "2022-09-03", "only_value": True, "min_edge": 0.9}
    ).json()
    assert all(m["value_bets"] for m in only_value["matches"])
    default_day = client.get("/api/v1/matches").json()
    assert default_day["date"] == "2022-09-03"


def test_matches_validation_errors(client: TestClient) -> None:
    _assert_error(
        client.get("/api/v1/matches", params={"date": "2022-13-45"}), 422, "VALIDATION_ERROR"
    )
    _assert_error(
        client.get("/api/v1/matches", params={"date": "03/09/2022"}), 422, "VALIDATION_ERROR"
    )
    _assert_error(client.get("/api/v1/matches", params={"min_edge": -1}), 422, "VALIDATION_ERROR")
    _assert_error(client.get("/api/v1/matches", params={"league": "XX"}), 404, "LEAGUE_NOT_FOUND")


def test_prediction_with_and_without_odds(client: TestClient) -> None:
    request = {
        "league": "E0",
        "home_team": "Team 00",
        "away_team": "team 01 fc",
        "match_date": "2022-09-03",
        "odds": {"home": 1.98, "draw": 3.9, "away": 4.5},
    }
    body = client.post("/api/v1/predictions", json=request).json()
    assert body["model_variant"] == "with_odds"
    assert body["away_team"] == "Team 01"
    assert body["market"]["source"] == "request"
    assert body["market"]["best_odds"] == {"home": 1.98, "draw": 3.9, "away": 4.5}
    assert sum(body["probabilities"].values()) == pytest.approx(1.0, abs=1e-6)
    no_odds = client.post(
        "/api/v1/predictions", json={"league": "E0", "home_team": "Team 00", "away_team": "Team 01"}
    ).json()
    assert no_odds["model_variant"] == "without_odds"
    assert no_odds["market"] is None and no_odds["value_bets"] == []


def test_prediction_errors(client: TestClient) -> None:
    unknown = client.post(
        "/api/v1/predictions",
        json={"league": "E0", "home_team": "Man Utd FC", "away_team": "Team 01"},
    )
    _assert_error(unknown, 404, "TEAM_NOT_FOUND")
    assert unknown.json()["error"]["message"] == "Equipo 'Man Utd FC' no reconocido en E0"
    _assert_error(
        client.post(
            "/api/v1/predictions", json={"league": "XX", "home_team": "a", "away_team": "b"}
        ),
        404,
        "LEAGUE_NOT_FOUND",
    )
    _assert_error(
        client.post("/api/v1/predictions", json={"league": "E0"}), 422, "VALIDATION_ERROR"
    )
    bad_odds = {
        "league": "E0",
        "home_team": "Team 00",
        "away_team": "Team 01",
        "odds": {"home": 0.5, "draw": 3, "away": 4},
    }
    _assert_error(client.post("/api/v1/predictions", json=bad_odds), 422, "VALIDATION_ERROR")
    bad_date = {"league": "E0", "home_team": "Team 00", "away_team": "Team 01", "match_date": "x"}
    _assert_error(client.post("/api/v1/predictions", json=bad_date), 422, "VALIDATION_ERROR")


def test_model_experiments_and_tracking(client: TestClient) -> None:
    model = client.get("/api/v1/model").json()
    assert model["version"] == "E12-logistic-2022-09-01"
    assert model["success_level"] == "Bueno"
    assert model["features"] and "log_loss" in model["validation_metrics"]
    experiments = client.get("/api/v1/experiments").json()
    assert [e["exp_id"] for e in experiments] == ["E12", "E02"]
    assert experiments[0]["conclusion"] is None
    client.get("/api/v1/matches", params={"date": "2022-09-03"})
    summary = client.get("/api/v1/tracking/summary").json()
    assert summary == {
        "predictions": 3,
        "graded": 0,
        "log_loss": None,
        "accuracy": None,
        "value_bets": 0,
        "roi": None,
    }


def test_admin_refresh(client: TestClient, env: ServingEnv, refreshed: list[str]) -> None:
    _assert_error(client.post("/api/v1/admin/refresh"), 401, "UNAUTHORIZED")
    _assert_error(
        client.post("/api/v1/admin/refresh", headers={"X-API-Key": "wrong"}), 401, "UNAUTHORIZED"
    )
    response = client.post("/api/v1/admin/refresh", headers={"X-API-Key": API_KEY})
    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "fixtures": 3,
        "current_season_refresh": "scheduled",
    }
    assert refreshed == ["rebuilt"]  # background task ran after the response


def test_model_not_available_returns_503(tmp_path: Path) -> None:
    env = build_serving_env(tmp_path)
    env.predictor.production_versions = lambda: {
        "champion": "missing",
        "champion_no_odds": "missing",
    }
    services = ApiServices(
        env.predictor,
        env.tracking,
        leagues(),
        lambda: pd.DataFrame(),
        API_KEY,
        RefreshData(lambda: 0, lambda: None, env.predictor.reset),
    )
    with TestClient(create_app(services)) as client:
        assert client.get("/health").json()["model_loaded"] is False
        _assert_error(client.get("/api/v1/matches"), 503, "MODEL_NOT_AVAILABLE")
        _assert_error(client.get("/api/v1/model"), 503, "MODEL_NOT_AVAILABLE")
        assert client.get("/api/v1/leagues").json()[0]["teams"] == 0
        assert client.get("/api/v1/experiments").json() == []


def test_unknown_route_and_cors(client: TestClient) -> None:
    _assert_error(client.get("/api/v1/nothing"), 404, "NOT_FOUND")
    preflight = client.options(
        "/api/v1/leagues",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
    foreign = client.get("/api/v1/leagues", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in foreign.headers
    assert client.get("/openapi.json").status_code == 200


def test_refresh_data_logs_failures() -> None:
    calls: list[str] = []

    def boom() -> None:
        raise RuntimeError("down")

    refresher = RefreshData(lambda: 1, boom, lambda: calls.append("reset"))
    refresher.data()  # must not raise
    assert calls == []
    assert refresher.fixtures() == 1 and calls == ["reset"]


def test_same_team_is_rejected(client: TestClient) -> None:
    body = {"league": "E0", "home_team": "Team 00", "away_team": "team 00"}
    _assert_error(client.post("/api/v1/predictions", json=body), 422, "VALIDATION_ERROR")


def test_tracking_uses_validated_threshold(client: TestClient, env: ServingEnv) -> None:
    served = client.get("/api/v1/matches", params={"date": "2022-09-03", "min_edge": 0}).json()
    tracked = env.tracking.store.load()
    assert len(tracked) == served["count"]
    # The request asked for min_edge=0 but tracking keeps the model threshold (default 0.05).
    assert (tracked["value_ev"].dropna() > 0.05).all()


def test_admin_disabled_with_default_key(env: ServingEnv) -> None:
    services = ApiServices(
        env.predictor,
        env.tracking,
        leagues(),
        pd.DataFrame,
        "cambia-esto",
        RefreshData(lambda: 0, lambda: None, env.predictor.reset),
    )
    with TestClient(create_app(services)) as client:
        response = client.post("/api/v1/admin/refresh", headers={"X-API-Key": "cambia-esto"})
        _assert_error(response, 503, "ADMIN_DISABLED")
