"""Spec-004 market calibration served by the API: the league report and, when it exists, the
European one (confidence level per market)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from betting_ml.domain.ports import ReportStore

CALIBRATION_REPORT = "market_calibration.json"
EUROPE_CALIBRATION_REPORT = "market_calibration_europe.json"


class CalibrationReportNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("Falta reports/market_calibration.json (make validate-markets)")


@dataclass
class ReadMarketCalibration:
    reports: ReportStore

    def run(self) -> dict[str, Any]:
        leagues = self.reports.read_json(CALIBRATION_REPORT)
        if leagues is None:
            raise CalibrationReportNotFoundError()
        return {"leagues": leagues, "europe": self.reports.read_json(EUROPE_CALIBRATION_REPORT)}
