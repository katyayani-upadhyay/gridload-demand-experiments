"""Sequence the pipeline steps.

Each step is a plain function with no arguments beyond settings, so an Airflow
DAG can later wrap each one in a PythonOperator without touching the packages.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable

from gridload.causal.run import run_causal
from gridload.config import PROJECT_ROOT, Settings, get_settings
from gridload.experiments.analyze import run_experiment
from gridload.forecasting.run import run_forecast
from gridload.ingest import run_ingest

log = logging.getLogger("gridload.pipeline")


def _dbt(settings: Settings, *args: str) -> None:
    env = {**os.environ, "GRIDLOAD_DUCKDB_PATH": str(settings.duckdb_path)}
    command = [
        sys.executable,
        "-m",
        "dbt.cli.main",
        *args,
        "--project-dir",
        str(settings.dbt_dir),
        "--profiles-dir",
        str(settings.dbt_dir),
    ]
    subprocess.run(command, check=True, cwd=PROJECT_ROOT, env=env)


def step_ingest(settings: Settings) -> None:
    run_ingest(settings)


def step_transform(settings: Settings) -> None:
    _dbt(settings, "seed")
    _dbt(settings, "run")


def step_test(settings: Settings) -> None:
    _dbt(settings, "test")
    _dbt(settings, "source", "freshness")


def step_forecast(settings: Settings, smoke: bool = False) -> None:
    run_forecast(settings, smoke=smoke)


def step_experiment(settings: Settings) -> None:
    run_experiment(settings)


def step_causal(settings: Settings) -> None:
    run_causal(settings)


STEPS: dict[str, Callable[[Settings], None]] = {
    "ingest": step_ingest,
    "transform": step_transform,
    "test": step_test,
    "forecast": step_forecast,
    "experiment": step_experiment,
    "causal": step_causal,
}


def run(steps: list[str], settings: Settings, smoke: bool = False) -> None:
    for name in steps:
        started = time.perf_counter()
        log.info("step %s: start", name)
        if name == "forecast":
            step_forecast(settings, smoke=smoke)
        else:
            STEPS[name](settings)
        log.info("step %s: done in %.1fs", name, time.perf_counter() - started)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run gridload pipeline steps in order.")
    parser.add_argument(
        "steps",
        nargs="*",
        choices=[*STEPS, "all"],
        default=["all"],
        help="steps to run, in pipeline order; default all",
    )
    parser.add_argument("--smoke", action="store_true", help="short forecast backtest for CI")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    steps = list(STEPS) if "all" in args.steps else [s for s in STEPS if s in args.steps]
    run(steps, get_settings(), smoke=args.smoke)


if __name__ == "__main__":
    main()
