"""Download the OPSD hourly time series and load the raw table into DuckDB.

Only the UTC timestamp and the two actual-load columns are read from the CSV.
The raw layer keeps the UTC clock as the sole time key; local time and DST
handling happen downstream in dbt where they can be tested.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import requests

from gridload.config import DATA_END, DATA_START, LOAD_COLUMNS, Settings, get_settings

log = logging.getLogger(__name__)

RAW_SCHEMA = "raw"
RAW_TABLE = "opsd_load_hourly"


def download_opsd(url: str, destination: Path, chunk_size: int = 1 << 20) -> Path:
    """Fetch the CSV once; later runs reuse the cached file."""
    if destination.exists() and destination.stat().st_size > 0:
        log.info("raw file already present at %s", destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(".part")
    log.info("downloading %s", url)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                handle.write(chunk)
    tmp.rename(destination)
    return destination


def load_raw_table(csv_path: Path, duckdb_path: Path) -> int:
    """Create raw.opsd_load_hourly from the CSV and return the row count."""
    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    ingested_at = datetime.now(tz=UTC).replace(tzinfo=None)
    select_cols = ", ".join(
        f'"{col}"::DOUBLE AS {code.lower()}_load_mw' for code, col in LOAD_COLUMNS.items()
    )
    with duckdb.connect(str(duckdb_path)) as con:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}")
        con.execute(
            f"""
            CREATE OR REPLACE TABLE {RAW_SCHEMA}.{RAW_TABLE} AS
            SELECT
                CAST(strptime(utc_timestamp, '%Y-%m-%dT%H:%M:%SZ') AS TIMESTAMP) AS utc_timestamp,
                cet_cest_timestamp,
                {select_cols},
                $ingested_at::TIMESTAMP AS ingested_at
            FROM read_csv($csv, header = true, all_varchar = true)
            WHERE utc_timestamp >= $start AND utc_timestamp <= $end
            """,
            {
                "csv": str(csv_path),
                "start": DATA_START.replace(" ", "T") + "Z",
                "end": DATA_END.replace(" ", "T") + "Z",
                "ingested_at": ingested_at,
            },
        )
        count = con.execute(f"SELECT count(*) FROM {RAW_SCHEMA}.{RAW_TABLE}").fetchone()[0]
    log.info("loaded %d rows into %s.%s", count, RAW_SCHEMA, RAW_TABLE)
    return count


def run_ingest(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    csv_path = download_opsd(settings.opsd_url, settings.raw_csv_path)
    return load_raw_table(csv_path, settings.duckdb_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_ingest()
