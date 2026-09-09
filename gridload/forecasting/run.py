"""Run the day-ahead backtest for Spain and write the metrics tables."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from gridload.config import Settings, get_settings
from gridload.forecasting.backtest import BacktestConfig, rolling_backtest
from gridload.forecasting.data import assert_hourly_regular, load_hourly
from gridload.forecasting.features import build_features, spain_holidays
from gridload.forecasting.metrics import summarise
from gridload.forecasting.models import LightGBMForecaster, SeasonalNaiveForecaster

log = logging.getLogger(__name__)

COUNTRY = "ES"
FULL_BACKTEST = BacktestConfig(start=date(2019, 1, 1), end=date(2020, 9, 30))
SMOKE_BACKTEST = BacktestConfig(start=date(2019, 1, 1), end=date(2019, 1, 31), refit_every_days=14)
MODEL_NAMES = ["seasonal_naive", "lightgbm"]


def run_forecast(settings: Settings | None = None, smoke: bool = False) -> pd.DataFrame:
    settings = settings or get_settings()
    config = SMOKE_BACKTEST if smoke else FULL_BACKTEST
    reports = settings.reports_dir
    reports.mkdir(parents=True, exist_ok=True)

    hourly = load_hourly(settings.duckdb_path, COUNTRY)
    assert_hourly_regular(hourly)
    years = range(hourly.index.min().year, hourly.index.max().year + 2)
    features = build_features(hourly, spain_holidays(years))

    log.info("backtest %s to %s, refit every %d days", config.start, config.end, config.refit_every_days)
    predictions = rolling_backtest(
        features,
        {"seasonal_naive": SeasonalNaiveForecaster, "lightgbm": LightGBMForecaster},
        config,
    )

    overall = summarise(predictions, "actual", MODEL_NAMES)
    by_hour = summarise(predictions, "actual", MODEL_NAMES, by="local_hour")
    by_year = summarise(
        predictions.assign(year=predictions["local_timestamp"].dt.year), "actual", MODEL_NAMES, by="year"
    )

    final_model = LightGBMForecaster()
    final_model.fit(features[pd.to_datetime(features["local_date"]) < pd.Timestamp(config.end)])
    importance = final_model.feature_importance().rename("gain").rename_axis("feature")

    if not smoke:
        _write_reports(reports, predictions, overall, by_hour, by_year, importance, config)
    log.info("\n%s", overall.to_string(index=False))
    return overall


def _write_reports(
    reports: Path,
    predictions: pd.DataFrame,
    overall: pd.DataFrame,
    by_hour: pd.DataFrame,
    by_year: pd.DataFrame,
    importance: pd.Series,
    config: BacktestConfig,
) -> None:
    predictions.reset_index().to_parquet(reports / "forecast_predictions.parquet", index=False)
    overall.to_csv(reports / "forecast_metrics.csv", index=False)
    by_hour.to_csv(reports / "forecast_metrics_by_hour.csv", index=False)
    by_year.to_csv(reports / "forecast_metrics_by_year.csv", index=False)
    importance.to_csv(reports / "forecast_feature_importance.csv")
    (reports / "forecast_backtest_config.json").write_text(
        json.dumps(
            {
                "country": COUNTRY,
                "start": config.start.isoformat(),
                "end": config.end.isoformat(),
                "refit_every_days": config.refit_every_days,
                "n_hours_scored": int(len(predictions)),
            },
            indent=2,
        )
    )
    lines = [
        "# Day-ahead forecast backtest",
        "",
        f"Spain, {config.start} to {config.end}, rolling origin, refit every "
        f"{config.refit_every_days} days, {len(predictions)} hours scored.",
        "",
        "| Model | WAPE | MAPE | Bias |",
        "|---|---|---|---|",
    ]
    for row in overall.itertuples():
        lines.append(
            f"| {row.model} | {row.wape:.2%} | {row.mape:.2%} | {row.bias_pct:+.2%} |"
        )
    (reports / "forecast_metrics.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_forecast(smoke="--smoke" in sys.argv)
