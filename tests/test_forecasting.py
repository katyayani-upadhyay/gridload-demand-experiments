from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from gridload.forecasting.backtest import BacktestConfig, rolling_backtest
from gridload.forecasting.data import assert_hourly_regular
from gridload.forecasting.features import (
    MIN_LAG_HOURS,
    TARGET,
    build_features,
    feature_columns,
)
from gridload.forecasting.metrics import bias_pct, mape, summarise, wape
from gridload.forecasting.models import LightGBMForecaster, SeasonalNaiveForecaster


def test_metrics_match_hand_computed_values() -> None:
    actual = np.array([100.0, 200.0, 300.0])
    predicted = np.array([110.0, 180.0, 300.0])
    assert wape(actual, predicted) == pytest.approx(30 / 600)
    assert mape(actual, predicted) == pytest.approx((0.10 + 0.10 + 0.0) / 3)
    assert bias_pct(actual, predicted) == pytest.approx(-10 / 600)


def test_wape_weights_by_load_while_mape_does_not() -> None:
    actual = np.array([10.0, 1000.0])
    predicted = np.array([20.0, 1000.0])
    assert mape(actual, predicted) == pytest.approx(0.5)
    assert wape(actual, predicted) == pytest.approx(10 / 1010)


def test_seasonal_naive_is_same_hour_previous_week(
    synthetic_hourly: pd.DataFrame, no_holidays: set[date]
) -> None:
    features = build_features(synthetic_hourly, no_holidays)
    t = synthetic_hourly.index[500]
    baseline = SeasonalNaiveForecaster().predict(features.loc[[t]])
    assert baseline[0] == synthetic_hourly.loc[t - pd.Timedelta(hours=168), TARGET]


def test_features_never_use_data_after_forecast_origin(
    synthetic_hourly: pd.DataFrame, no_holidays: set[date]
) -> None:
    """Corrupting every observation from the origin onward must leave the
    target day's features untouched."""
    origin = pd.Timestamp("2019-06-10 23:00")  # local midnight of 2019-06-11
    clean = build_features(synthetic_hourly, no_holidays)
    corrupted_input = synthetic_hourly.copy()
    corrupted_input.loc[corrupted_input.index >= origin, TARGET] = 1e9
    corrupted = build_features(corrupted_input, no_holidays)

    target_day = clean["local_date"] == date(2019, 6, 11)
    cols = feature_columns(clean)
    pd.testing.assert_frame_equal(clean.loc[target_day, cols], corrupted.loc[target_day, cols])


def test_every_lag_feature_respects_minimum_horizon(
    synthetic_hourly: pd.DataFrame, no_holidays: set[date]
) -> None:
    features = build_features(synthetic_hourly, no_holidays)
    lag_cols = [c for c in features.columns if c.startswith("lag_") and c.endswith("h")]
    assert lag_cols
    for col in lag_cols:
        lag = int(col.removeprefix("lag_").removesuffix("h"))
        assert lag >= MIN_LAG_HOURS


def test_backtest_trains_only_on_hours_before_each_block(
    synthetic_hourly: pd.DataFrame, no_holidays: set[date]
) -> None:
    seen: list[pd.Timestamp] = []

    class RecordingModel(SeasonalNaiveForecaster):
        def fit(self, train: pd.DataFrame) -> None:
            seen.append(train.index.max())

    features = build_features(synthetic_hourly, no_holidays)
    config = BacktestConfig(start=date(2019, 3, 1), end=date(2019, 3, 20), refit_every_days=7)
    result = rolling_backtest(features, {"seasonal_naive": RecordingModel}, config)

    assert len(seen) == 3
    block_starts = [pd.Timestamp("2019-03-01"), pd.Timestamp("2019-03-08"), pd.Timestamp("2019-03-15")]
    for last_train_hour, block_start in zip(seen, block_starts, strict=True):
        assert last_train_hour + pd.Timedelta(hours=1) < block_start
    assert result["local_date"].min() == date(2019, 3, 1)
    assert result["local_date"].max() == date(2019, 3, 20)
    assert len(result) == 20 * 24


def test_lightgbm_beats_seasonal_naive_on_synthetic_data(
    synthetic_hourly: pd.DataFrame, no_holidays: set[date]
) -> None:
    features = build_features(synthetic_hourly, no_holidays)
    config = BacktestConfig(start=date(2019, 9, 1), end=date(2019, 9, 28), refit_every_days=28)
    fast = LightGBMForecaster(params={"learning_rate": 0.1, "verbose": -1}, num_rounds=150)
    result = rolling_backtest(
        features,
        {"seasonal_naive": SeasonalNaiveForecaster, "lightgbm": lambda: fast},
        config,
    )
    table = summarise(result, "actual", ["seasonal_naive", "lightgbm"]).set_index("model")
    assert table.loc["lightgbm", "wape"] < table.loc["seasonal_naive", "wape"]


def test_assert_hourly_regular_detects_gaps(synthetic_hourly: pd.DataFrame) -> None:
    assert_hourly_regular(synthetic_hourly)
    with pytest.raises(ValueError):
        assert_hourly_regular(synthetic_hourly.drop(synthetic_hourly.index[10]))
