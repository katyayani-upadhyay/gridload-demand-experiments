"""Model wrappers with a shared fit/predict surface."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol

import lightgbm as lgb
import numpy as np
import pandas as pd

from gridload.forecasting.features import TARGET, as_matrix, feature_columns


class Forecaster(Protocol):
    name: str

    def fit(self, train: pd.DataFrame) -> None: ...

    def predict(self, frame: pd.DataFrame) -> np.ndarray: ...


@dataclass
class SeasonalNaiveForecaster:
    name: str = "seasonal_naive"

    def fit(self, train: pd.DataFrame) -> None:
        return None

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        # The lag column is computed on the full history, so it is valid on any slice.
        return frame["lag_168h"].to_numpy()


DEFAULT_LGB_PARAMS: dict[str, object] = {
    "objective": "l2",
    "learning_rate": 0.03,
    "num_leaves": 63,
    "min_data_in_leaf": 40,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.8,
    "lambda_l2": 1.0,
    "seed": 42,
    "verbose": -1,
    # Oversubscribing OpenMP threads on laptops slows training by orders of magnitude.
    "num_threads": min(4, os.cpu_count() or 1),
}
DEFAULT_NUM_ROUNDS = 800


@dataclass
class LightGBMForecaster:
    name: str = "lightgbm"
    params: dict[str, object] = field(default_factory=lambda: dict(DEFAULT_LGB_PARAMS))
    num_rounds: int = DEFAULT_NUM_ROUNDS
    columns: list[str] = field(default_factory=list)
    model: lgb.Booster | None = None

    def fit(self, train: pd.DataFrame) -> None:
        self.columns = feature_columns(train)
        usable = train.dropna(subset=self.columns + [TARGET])
        dataset = lgb.Dataset(
            as_matrix(usable, self.columns),
            label=usable[TARGET].to_numpy(),
            feature_name=self.columns,
        )
        self.model = lgb.train(self.params, dataset, num_boost_round=self.num_rounds)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("fit before predict")
        return self.model.predict(as_matrix(frame, self.columns))

    def feature_importance(self) -> pd.Series:
        if self.model is None:
            raise RuntimeError("fit before feature_importance")
        gain = self.model.feature_importance(importance_type="gain")
        return pd.Series(gain, index=self.columns).sort_values(ascending=False)
