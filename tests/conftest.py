from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_hourly() -> pd.DataFrame:
    """Two years of hourly load with daily and weekly cycles, indexed by UTC."""
    rng = np.random.default_rng(0)
    index = pd.date_range("2018-01-01", "2019-12-31 23:00", freq="h", name="utc_timestamp")
    hours = np.arange(len(index))
    daily = 5000 * np.sin(2 * np.pi * (hours % 24) / 24)
    weekly = 2000 * np.sin(2 * np.pi * (hours % 168) / 168)
    load = 28000 + daily + weekly + rng.normal(0, 300, len(index))
    local = index + pd.Timedelta(hours=1)
    return pd.DataFrame(
        {
            "local_timestamp": local,
            "local_date": local.date,
            "local_hour": local.hour,
            "day_of_week": local.dayofweek,
            "is_weekend": local.dayofweek >= 5,
            "load_mw": load,
            "is_imputed": False,
        },
        index=index,
    )


@pytest.fixture
def no_holidays() -> set[date]:
    return set()
