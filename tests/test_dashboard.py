from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
REPORTS = APP.parents[1] / "reports"

REQUIRED_REPORTS = [
    "forecast_predictions.parquet",
    "forecast_metrics.csv",
    "forecast_metrics_by_hour.csv",
    "forecast_backtest_config.json",
    "ab_results.json",
    "ab_decision.md",
    "did_results.json",
    "did_results.md",
    "did_event_study.csv",
    "did_event_study_weekly.csv",
]


@pytest.mark.parametrize("name", REQUIRED_REPORTS)
def test_report_artifact_is_committed(name: str) -> None:
    assert (REPORTS / name).exists(), f"dashboard needs reports/{name}"


def test_dashboard_renders_without_exceptions() -> None:
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception, [e.value for e in app.exception]
    assert len(app.tabs) == 3
    assert any("Simulated data" in w.value for w in app.warning)
