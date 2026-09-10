"""Leakage-safe feature construction for day-ahead forecasting.

The forecast origin is local midnight of the target day, so every hour of the
day is between 1 and 24 hours ahead. Any lag of at least 24 hours is therefore
observed at forecast time. MIN_LAG_HOURS enforces that floor for every lag and
every rolling window.
"""

from __future__ import annotations

from datetime import date

import holidays
import numpy as np
import pandas as pd

MIN_LAG_HOURS = 24
LAG_HOURS: tuple[int, ...] = (24, 48, 72, 168, 336)
SAME_HOUR_WEEKS = 4
ROLLING_WINDOW_HOURS = 168
TARGET = "load_mw"

CALENDAR_FEATURES = [
    "local_hour",
    "day_of_week",
    "is_weekend",
    "month",
    "day_of_year",
    "is_holiday",
    "is_day_after_holiday",
]


def spain_holidays(years: range) -> set[date]:
    return set(holidays.Spain(years=years).keys())


def build_features(frame: pd.DataFrame, holiday_dates: set[date]) -> pd.DataFrame:
    """Add calendar, lag and rolling features. Rows lacking history keep NaNs."""
    out = frame.copy()
    y = out[TARGET]

    local = out["local_timestamp"]
    out["month"] = local.dt.month
    out["day_of_year"] = local.dt.dayofyear
    out["is_weekend"] = out["is_weekend"].astype(int)
    out["is_holiday"] = out["local_date"].isin(holiday_dates).astype(int)
    prev_day = pd.to_datetime(out["local_date"]) - pd.Timedelta(days=1)
    out["is_day_after_holiday"] = prev_day.dt.date.isin(holiday_dates).astype(int)

    for lag in LAG_HOURS:
        out[f"lag_{lag}h"] = y.shift(lag)

    same_hour = pd.concat([y.shift(168 * k) for k in range(1, SAME_HOUR_WEEKS + 1)], axis=1)
    out["same_hour_mean_4w"] = same_hour.mean(axis=1)
    out["same_hour_std_4w"] = same_hour.std(axis=1)

    known = y.shift(MIN_LAG_HOURS)
    out["rolling_mean_7d"] = known.rolling(ROLLING_WINDOW_HOURS).mean()
    out["rolling_std_7d"] = known.rolling(ROLLING_WINDOW_HOURS).std()
    out["rolling_max_7d"] = known.rolling(ROLLING_WINDOW_HOURS).max()
    out["rolling_min_7d"] = known.rolling(ROLLING_WINDOW_HOURS).min()
    out["lag_24h_vs_week_mean"] = out["lag_24h"] - out["rolling_mean_7d"]

    return out


def feature_columns(frame: pd.DataFrame) -> list[str]:
    lag_cols = [c for c in frame.columns if c.startswith(("lag_", "same_hour_", "rolling_"))]
    return CALENDAR_FEATURES + lag_cols


def as_matrix(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    return frame[columns].to_numpy(dtype=float)
