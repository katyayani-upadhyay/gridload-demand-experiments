"""Error metrics for load forecasts. WAPE is primary because it weights hours
by their load, which is how forecast error costs a system operator."""

from __future__ import annotations

import numpy as np
import pandas as pd


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.abs(predicted - actual).sum() / np.abs(actual).sum())


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float(np.mean(np.abs(predicted - actual) / np.abs(actual)))


def bias_pct(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Signed error relative to total actual load. Positive means over-forecast."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    return float((predicted - actual).sum() / actual.sum())


def summarise(
    predictions: pd.DataFrame,
    actual_col: str,
    model_cols: list[str],
    by: str | None = None,
) -> pd.DataFrame:
    """One row per model (and per group when `by` is given) with the three metrics."""
    rows: list[dict[str, object]] = []
    groups = [(None, predictions)] if by is None else list(predictions.groupby(by))
    for key, group in groups:
        for model in model_cols:
            row: dict[str, object] = {"model": model}
            if by is not None:
                row[by] = key
            row.update(
                wape=wape(group[actual_col], group[model]),
                mape=mape(group[actual_col], group[model]),
                bias_pct=bias_pct(group[actual_col], group[model]),
                n_hours=int(len(group)),
            )
            rows.append(row)
    return pd.DataFrame(rows)
