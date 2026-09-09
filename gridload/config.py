"""Paths and constants shared by every pipeline step.

Values come from environment variables (or a local .env) with defaults that
match the checked-in .env.example, so a fresh clone runs without any setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

OPSD_DEFAULT_URL = (
    "https://data.open-power-system-data.org/time_series/2020-10-06/"
    "time_series_60min_singleindex.csv"
)

COUNTRIES: dict[str, str] = {"ES": "Europe/Madrid", "PT": "Europe/Lisbon"}
LOAD_COLUMNS: dict[str, str] = {
    "ES": "ES_load_actual_entsoe_transparency",
    "PT": "PT_load_actual_entsoe_transparency",
}
# 2014-12-31 23:00 UTC is 2015-01-01 00:00 in Madrid, so Spain's local calendar starts complete.
DATA_START = "2014-12-31 23:00:00"
DATA_END = "2020-09-30 23:00:00"


def _path(env_var: str, default: str) -> Path:
    raw = Path(os.environ.get(env_var, default))
    return raw if raw.is_absolute() else PROJECT_ROOT / raw


@dataclass(frozen=True)
class Settings:
    duckdb_path: Path
    raw_dir: Path
    reports_dir: Path
    opsd_url: str

    @property
    def raw_csv_path(self) -> Path:
        return self.raw_dir / self.opsd_url.rsplit("/", 1)[-1]

    @property
    def dbt_dir(self) -> Path:
        return PROJECT_ROOT / "dbt"


def get_settings() -> Settings:
    return Settings(
        duckdb_path=_path("GRIDLOAD_DUCKDB_PATH", "data/gridload.duckdb"),
        raw_dir=_path("GRIDLOAD_RAW_DIR", "data/raw"),
        reports_dir=_path("GRIDLOAD_REPORTS_DIR", "reports"),
        opsd_url=os.environ.get("OPSD_TIME_SERIES_URL", OPSD_DEFAULT_URL),
    )
