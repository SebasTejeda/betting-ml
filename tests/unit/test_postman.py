import json

from betting_ml.api.main import create_app
from betting_ml.config import PROJECT_ROOT

# Spec-002 routes join the collection in T018.
SPEC_002_PENDING = (
    "/api/v1/odds",
    "/api/v1/bookmakers",
    "/api/v1/comparator",
    "/api/v1/calculator",
    "/api/v1/bets",
    "/api/v1/settings",
    "/api/v1/backtest",
)
COLLECTION = PROJECT_ROOT / "postman" / "betting-ml.postman_collection.json"


def _requests(items: list[dict]) -> list[dict]:
    out = []
    for item in items:
        out += _requests(item["item"]) if "item" in item else [item]
    return out


def test_collection_covers_every_endpoint() -> None:
    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    assert {"key": "baseUrl", "value": "http://localhost:8000"} in data["variable"]
    requests = _requests(data["item"])
    covered = {
        (r["request"]["method"], "/" + "/".join(r["request"]["url"]["path"])) for r in requests
    }
    routes = {
        (method.upper(), path.replace("{code}", "E0"))
        for path, ops in create_app().openapi()["paths"].items()
        for method in ops
        if not path.startswith(SPEC_002_PENDING)
    }
    assert len(routes) >= 9
    assert routes <= covered
    assert all(r["event"] and r["event"][0]["listen"] == "test" for r in requests)
    statuses = " ".join(" ".join(r["event"][0]["script"]["exec"]) for r in requests)
    for code in ("200", "202", "401", "404", "422"):
        assert f"have.status({code})" in statuses
