"""Rolling-origin backtest with periodic refits.

Each block of `refit_every_days` target days gets a model trained only on hours
whose target time is strictly before the block starts. Within the block the
model is frozen, and each target day is scored from features that are lagged at
least 24 hours, so every prediction uses only data observable at local midnight
of the target day.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from gridload.forecasting.features import TARGET
from gridload.forecasting.models import Forecaster


@dataclass(frozen=True)
class BacktestConfig:
    start: date
    end: date
    refit_every_days: int = 28


def _blocks(config: BacktestConfig) -> list[tuple[date, date]]:
    blocks: list[tuple[date, date]] = []
    cursor = config.start
    while cursor <= config.end:
        block_end = min(cursor + timedelta(days=config.refit_every_days - 1), config.end)
        blocks.append((cursor, block_end))
        cursor = block_end + timedelta(days=1)
    return blocks


def rolling_backtest(
    features: pd.DataFrame,
    model_factories: dict[str, Callable[[], Forecaster]],
    config: BacktestConfig,
) -> pd.DataFrame:
    """Return actuals and one prediction column per model for the test window."""
    local_date = pd.to_datetime(features["local_date"])
    outputs: list[pd.DataFrame] = []
    for block_start, block_end in _blocks(config):
        train = features[local_date < pd.Timestamp(block_start)]
        test = features[
            (local_date >= pd.Timestamp(block_start)) & (local_date <= pd.Timestamp(block_end))
        ]
        if test.empty:
            continue
        block = test[["local_timestamp", "local_date", "local_hour", "is_imputed", TARGET]].copy()
        block["refit_origin"] = block_start
        for name, factory in model_factories.items():
            model = factory()
            model.fit(train)
            block[name] = model.predict(test)
        outputs.append(block)
    result = pd.concat(outputs)
    result.index.name = "utc_timestamp"
    return result.rename(columns={TARGET: "actual"})
