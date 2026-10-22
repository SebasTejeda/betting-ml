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


def test_private_requests_carry_the_machine_key() -> None:
    """Spec 003, T007: reads are private too; only health, the session flow and the explicit
    401 examples go without X-API-Key."""
    data = json.loads(COLLECTION.read_text(encoding="utf-8"))
    keyless_reads = 0
    for request in _requests(data["item"]):
        path = request["request"]["url"]["path"]
        if path == ["health"] or path[:3] == ["api", "v1", "auth"]:
            continue
        headers = {h["key"]: h["value"] for h in request["request"].get("header", [])}
        expects_401 = "have.status(401)" in " ".join(request["event"][0]["script"]["exec"])
        if expects_401:
            assert "X-API-Key" not in headers or headers["X-API-Key"] != "{{appApiKey}}"
            keyless_reads += request["request"]["method"] == "GET"
        else:
            assert headers.get("X-API-Key") == "{{appApiKey}}", request["name"]
    assert keyless_reads >= 1
