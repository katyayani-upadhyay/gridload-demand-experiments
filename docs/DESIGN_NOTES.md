# Design notes

Running log of the design decisions behind gridload-demand-experiments, in the
order they were made. Each entry states the decision and the reasoning.

## Setup

**uv-managed Python 3.11 virtualenv.** The machine has no `python3.11` on PATH
but `uv` already manages a CPython 3.11 build, so the Makefile creates `.venv`
through `uv venv --python 3.11` and installs with `uv pip`. Plain `pip` works
too; uv is just faster and avoids adding a system Python install as a
prerequisite.

**Flat `gridload` package with one subpackage per phase.** `gridload.ingest`,
`gridload.forecasting`, `gridload.experiments`, `gridload.causal` each expose
plain functions with no orchestration logic. The orchestrator in
`scripts/run_pipeline.py` and the Makefile only sequence those functions, so an
Airflow DAG later needs one PythonOperator per step and no refactor.

**Raw data and the DuckDB file are gitignored; small report artifacts are
committed.** The OPSD CSV is hundreds of megabytes and reproducible from a URL,
so it is never committed. Model metrics, A/B result JSON, and the DiD
event-study table are a few kilobytes each and are committed under `reports/`
so the Streamlit dashboard can run on Community Cloud without rerunning the
pipeline.

**`.env.example` exists even though the project needs no secrets.** The
pipeline runs on public data only. The file pins the paths and the OPSD URL
the code reads, and gives any future credential a gitignored home so the
hygiene rule is already in place.
