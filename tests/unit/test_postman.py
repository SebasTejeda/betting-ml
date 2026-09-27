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
        (method, route.path.replace("{code}", "E0"))
        for route in create_app().routes
        for method in getattr(route, "methods", set())
        if not route.path.startswith(("/docs", "/openapi", "/redoc")) and method != "HEAD"
    }
    assert routes <= covered
    assert all(r["event"] and r["event"][0]["listen"] == "test" for r in requests)
    statuses = " ".join(" ".join(r["event"][0]["script"]["exec"]) for r in requests)
    for code in ("200", "202", "401", "404", "422"):
        assert f"have.status({code})" in statuses
