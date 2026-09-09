"""Read the hourly load mart into a UTC-indexed frame."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

HOURLY_COLUMNS = [
    "utc_timestamp",
    "local_timestamp",
    "local_date",
    "local_hour",
    "day_of_week",
    "is_weekend",
    "load_mw",
    "is_imputed",
]


def load_hourly(duckdb_path: Path, country_code: str) -> pd.DataFrame:
    """Return one country's hourly mart ordered by UTC, indexed by utc_timestamp."""
    query = f"""
        select {", ".join(HOURLY_COLUMNS)}
        from marts.fct_load_hourly
        where country_code = ?
        order by utc_timestamp
    """
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        frame = con.execute(query, [country_code]).df()
    frame["utc_timestamp"] = pd.to_datetime(frame["utc_timestamp"])
    frame["local_timestamp"] = pd.to_datetime(frame["local_timestamp"])
    frame["local_date"] = pd.to_datetime(frame["local_date"]).dt.date
    return frame.set_index("utc_timestamp")


def assert_hourly_regular(frame: pd.DataFrame) -> None:
    """Lag features assume one row per hour with no gaps."""
    deltas = frame.index.to_series().diff().dropna()
    if not (deltas == pd.Timedelta(hours=1)).all():
        raise ValueError("hourly frame has gaps or duplicates; lag features would be misaligned")
