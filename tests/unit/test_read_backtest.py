"""Spec 003, T004: the backtest report goes through a use case and the ReportStore port."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from betting_ml.adapters.report_store import JsonReportStore
from betting_ml.application.read_backtest import BacktestReportNotFoundError, ReadBacktestReport
from betting_ml.domain.ports import ReportStore


class MemoryReports:
    def __init__(self, files: dict[str, dict[str, Any]]) -> None:
        self.files = files

    def read_json(self, name: str) -> dict[str, Any] | None:
        return self.files.get(name)


def test_report_with_margins() -> None:
    store = MemoryReports(
        {"backtest_002.json": {"level": "minimo"}, "margins_002.json": {"uplift": 0.05}}
    )
    assert ReadBacktestReport(store).run() == {"level": "minimo", "margins": {"uplift": 0.05}}


def test_report_without_margins() -> None:
    store = MemoryReports({"backtest_002.json": {"level": "minimo"}})
    assert ReadBacktestReport(store).run() == {"level": "minimo"}


def test_missing_report_raises() -> None:
    with pytest.raises(BacktestReportNotFoundError):
        ReadBacktestReport(MemoryReports({})).run()


def test_json_store_reads_files_and_misses_return_none(tmp_path: Path) -> None:
    (tmp_path / "backtest_002.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    store = JsonReportStore(tmp_path)
    assert isinstance(store, ReportStore)
    assert store.read_json("backtest_002.json") == {"a": 1}
    assert store.read_json("missing.json") is None


@pytest.mark.parametrize("name", ["../secret.json", "sub/report.json", "..", "", "report.txt"])
def test_json_store_only_reads_plain_json_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        JsonReportStore(tmp_path / "reports").read_json(name)


def test_json_store_rejects_non_object_json(tmp_path: Path) -> None:
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        JsonReportStore(tmp_path).read_json("list.json")
