"""Spec 003, T017: a model is unpickled only if its bytes match the SHA-256 recorded in its
metadata.json; models saved before the spec get their hash once, with ``models-rehash``."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
import pytest
from typer.testing import CliRunner

from betting_ml.adapters.joblib_registry import HASH_KEY, JoblibModelRegistry
from betting_ml.api.main import create_app
from betting_ml.application.catalog import RefreshData
from betting_ml.application.maintenance import RehashModels, RehashRefusedError
from betting_ml.cli import app
from betting_ml.config import Settings
from betting_ml.container import ApiServices
from betting_ml.domain.security import ModelIntegrityError
from tests.clients import ReaderClient
from tests.serving import build_serving_env, leagues

API_KEY = "test-key"
VERSION = "E01-2026-09-27"


class _Payload:
    """A pickle that runs code when it is loaded: it creates the directory ``marker``."""

    def __init__(self, marker: Path) -> None:
        self.marker = marker

    def __reduce__(self) -> tuple[Any, ...]:
        return (os.mkdir, (str(self.marker),))


def _registry(tmp_path: Path) -> JoblibModelRegistry:
    registry = JoblibModelRegistry(tmp_path / "models")
    registry.save(VERSION, {"weights": [1, 2, 3]}, {"experiment_id": "E01"})
    return registry


def _model_file(registry: JoblibModelRegistry, version: str = VERSION) -> Path:
    return registry.path(version) / "model.joblib"


def _set_metadata(registry: JoblibModelRegistry, version: str, **changes: Any) -> None:
    path = registry.path(version) / "metadata.json"
    metadata = {**json.loads(path.read_text(encoding="utf-8")), **changes}
    path.write_text(json.dumps({k: v for k, v in metadata.items() if v is not None}), "utf-8")


# ------------------------------------------------------------------ registry
def test_save_records_the_sha256_and_load_checks_it(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    recorded = registry.load_metadata(VERSION)[HASH_KEY]
    assert recorded == hashlib.sha256(_model_file(registry).read_bytes()).hexdigest()
    model, metadata = registry.load(VERSION)
    assert model == {"weights": [1, 2, 3]} and metadata["experiment_id"] == "E01"


def test_a_malicious_artifact_is_never_unpickled(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    # Control: this payload really runs code when joblib loads it.
    control = tmp_path / "control.joblib"
    joblib.dump(_Payload(tmp_path / "ran-control"), control)
    joblib.load(control)
    assert (tmp_path / "ran-control").is_dir()

    joblib.dump(_Payload(tmp_path / "ran"), _model_file(registry), compress=3)
    with pytest.raises(ModelIntegrityError, match="no coincide") as caught:
        registry.load(VERSION)
    assert caught.value.version == VERSION
    assert not (tmp_path / "ran").exists()


def test_another_valid_model_in_its_place_is_refused(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.save("E02-2026-09-27", {"weights": [9]}, {"experiment_id": "E02"})
    _model_file(registry).write_bytes(_model_file(registry, "E02-2026-09-27").read_bytes())
    with pytest.raises(ModelIntegrityError, match="no coincide"):
        registry.load(VERSION)


def test_a_flipped_byte_is_refused(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    data = bytearray(_model_file(registry).read_bytes())
    data[-1] ^= 0x01
    _model_file(registry).write_bytes(bytes(data))
    with pytest.raises(ModelIntegrityError, match="no coincide"):
        registry.load(VERSION)


@pytest.mark.parametrize("recorded", [None, "", "abc", "A" * 64, 42, "g" * 64])
def test_a_model_without_a_valid_recorded_hash_is_refused(tmp_path: Path, recorded: object) -> None:
    registry = _registry(tmp_path)
    if recorded is None:
        _set_metadata(registry, VERSION, **{HASH_KEY: None})
    else:
        _set_metadata(registry, VERSION, **{HASH_KEY: recorded})
    with pytest.raises(ModelIntegrityError, match="no registra su SHA-256"):
        registry.load(VERSION)


def test_unreadable_metadata_is_an_integrity_error(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    (registry.path(VERSION) / "metadata.json").write_text('{"sha256": "ab', "utf-8")
    with pytest.raises(ModelIntegrityError, match="ilegible"):
        registry.load(VERSION)


def test_metadata_is_swapped_in_whole(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.record_sha256(VERSION, "0" * 64)
    assert sorted(p.name for p in registry.path(VERSION).iterdir()) == [
        "metadata.json",
        "model.joblib",
    ]


def test_a_missing_model_is_still_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        JoblibModelRegistry(tmp_path / "models").load("nope")


# ------------------------------------------------------------------ API
def test_api_answers_503_model_integrity_error_and_never_loads_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = build_serving_env(tmp_path)
    champion = "E12-logistic-2022-09-01"
    joblib.dump(_Payload(tmp_path / "ran"), _model_file(env.registry, champion), compress=3)
    services = ApiServices(
        env.predictor,
        env.tracking,
        leagues(),
        lambda: pd.DataFrame(),
        API_KEY,
        RefreshData(lambda: 0, lambda: None, env.predictor.reset),
    )
    with caplog.at_level(logging.ERROR), ReaderClient(create_app(services), API_KEY) as client:
        assert client.get("/health").json()["model_loaded"] is False
        for path in ("/api/v1/model", "/api/v1/matches"):
            response = client.get(path)
            assert response.status_code == 503
            error = response.json()["error"]
            assert error["code"] == "MODEL_INTEGRITY_ERROR"
            assert error["details"] == {"version": champion}
            assert str(tmp_path) not in error["message"]  # no paths in the answer
        assert client.get("/api/v1/leagues").json()[0]["teams"] == 0
    assert "integrity check failed" in caplog.text
    assert not (tmp_path / "ran").exists()


# ------------------------------------------------------------------ models-rehash
def _legacy(tmp_path: Path) -> JoblibModelRegistry:
    """Two models saved before spec 003 (no hash) and one saved after it."""
    registry = _registry(tmp_path)
    registry.save("E02-2026-09-27", {"weights": [9]}, {"experiment_id": "E02"})
    registry.save("E03-2026-09-27", {"weights": [7]}, {"experiment_id": "E03"})
    for version in (VERSION, "E02-2026-09-27"):
        _set_metadata(registry, version, **{HASH_KEY: None})
    return registry


def test_rehash_records_the_missing_hashes_only(tmp_path: Path) -> None:
    registry = _legacy(tmp_path)
    before = registry.load_metadata("E03-2026-09-27")
    hashes = RehashModels(registry).run()
    assert [(h.version, h.status) for h in hashes] == [
        (VERSION, "new"),
        ("E02-2026-09-27", "new"),
        ("E03-2026-09-27", "ok"),
    ]
    for version in (VERSION, "E02-2026-09-27"):
        assert registry.load(version)[1]["experiment_id"] == version[:3]  # loads now
    assert registry.load_metadata("E03-2026-09-27") == before
    assert all(h.status == "ok" for h in RehashModels(registry).plan())  # idempotent


def test_rehash_never_replaces_a_different_recorded_hash(tmp_path: Path) -> None:
    registry = _legacy(tmp_path)
    joblib.dump(_Payload(tmp_path / "ran"), _model_file(registry, "E03-2026-09-27"))
    with pytest.raises(RehashRefusedError, match="E03-2026-09-27"):
        RehashModels(registry).run()
    # All or nothing: the legacy models did not get a hash either.
    assert registry.recorded_sha256(VERSION) is None
    with pytest.raises(ModelIntegrityError):
        registry.load("E03-2026-09-27")
    assert not (tmp_path / "ran").exists()


def test_rehash_records_only_the_hashes_the_owner_saw(tmp_path: Path) -> None:
    registry = _legacy(tmp_path)
    shown = {h.version: h.sha256 for h in RehashModels(registry).plan([VERSION])}
    joblib.dump(_Payload(tmp_path / "ran"), _model_file(registry))  # swapped while asking
    with pytest.raises(RehashRefusedError, match=f"cambiaron desde que se listaron: {VERSION}"):
        RehashModels(registry).run([VERSION], shown=shown)
    assert registry.recorded_sha256(VERSION) is None


def test_rehash_of_unknown_versions_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"sin model\.joblib: nope"):
        RehashModels(_legacy(tmp_path)).plan(["nope", VERSION])


@pytest.fixture
def cli_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JoblibModelRegistry:
    config = Settings(_env_file=None, models_dir=tmp_path / "models")
    monkeypatch.setattr("betting_ml.container.get_settings", lambda: config)
    return _legacy(tmp_path)


def test_cli_models_rehash_asks_first(cli_registry: JoblibModelRegistry) -> None:
    declined = CliRunner().invoke(app, ["models-rehash"], input="n\n")
    assert declined.exit_code == 1 and "¿Registrar el SHA-256 de 2 modelo(s)?" in declined.output
    assert f"{VERSION}: sin registrar" in declined.output
    assert "E03-2026-09-27: ya registrado" in declined.output
    assert cli_registry.recorded_sha256(VERSION) is None

    done = CliRunner().invoke(app, ["models-rehash", "--version", VERSION, "--yes"])
    assert done.exit_code == 0, done.output
    assert "Registrado el SHA-256 de 1 modelo(s)" in done.output
    assert cli_registry.recorded_sha256(VERSION) is not None
    assert cli_registry.recorded_sha256("E02-2026-09-27") is None

    again = CliRunner().invoke(app, ["models-rehash", "--version", VERSION])
    assert again.exit_code == 0 and "Nada que registrar" in again.output


def test_cli_models_rehash_refuses_a_changed_model(
    cli_registry: JoblibModelRegistry, tmp_path: Path
) -> None:
    joblib.dump({"weights": [0]}, _model_file(cli_registry, "E03-2026-09-27"))
    refused = CliRunner().invoke(app, ["models-rehash", "--yes"])
    assert refused.exit_code == 1
    assert "E03-2026-09-27: DISTINTO DEL REGISTRADO" in refused.output
    assert cli_registry.recorded_sha256(VERSION) is None
    unknown = CliRunner().invoke(app, ["models-rehash", "--version", "nope"])
    assert unknown.exit_code == 1 and "sin model.joblib: nope" in unknown.output
