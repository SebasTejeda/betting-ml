"""Spec-002 backtest report served by the API (US1), with the best-vs-average margins."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from betting_ml.domain.ports import ReportStore

BACKTEST_REPORT = "backtest_002.json"
MARGINS_REPORT = "margins_002.json"  # justifies the comparator (best vs average)


class BacktestReportNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Aún no se ha ejecutado el backtest final (make backtest-002-final)")


@dataclass
class ReadBacktestReport:
    reports: ReportStore

    def run(self) -> dict[str, Any]:
        report = self.reports.read_json(BACKTEST_REPORT)
        if report is None:
            raise BacktestReportNotFoundError()
        margins = self.reports.read_json(MARGINS_REPORT)
        if margins is not None:
            report["margins"] = margins
        return report
