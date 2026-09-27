import json

from betting_ml.api.main import create_app
from betting_ml.config import PROJECT_ROOT

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
        (
            method.upper(),
            path.replace("{code}", "E0")
            .replace("{match_id}", "{{matchId}}")
            .replace("{bet_id}", "{{betId}}"),
        )
        for path, ops in create_app().openapi()["paths"].items()
        for method in ops
    }
    assert len(routes) >= 24  # 10 of spec 001 + 14 of spec 002
    assert routes <= covered
    assert all(r["event"] and r["event"][0]["listen"] == "test" for r in requests)
    statuses = " ".join(" ".join(r["event"][0]["script"]["exec"]) for r in requests)
    for code in ("200", "202", "401", "404", "422"):
        assert f"have.status({code})" in statuses
