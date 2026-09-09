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

## P1: ingest and dbt

**UTC is the only time key; local time is a derived attribute.** OPSD ships both
`utc_timestamp` and `cet_cest_timestamp`. Local clocks skip an hour every March
and repeat one every October, so a local timestamp cannot be unique. The raw
table keeps UTC and dbt derives local time per country with
`timezone(tz, timezone('UTC', utc_ts))`, which is tested at the transition days.

**Spain and Portugal get different time zones.** Madrid is CET/CEST and Lisbon is
WET/WEST, one hour behind. Comparing the two by local hour-of-day is what
matters for the DiD (evening peaks line up), so the seed carries each country's
IANA zone and its standard UTC offset, and the DST test derives the skipped and
repeated local hour from that offset instead of hard-coding hour 2.

**Only 62 missing hours in six years, filled from neighbouring weeks and
flagged.** Spain has 23 nulls and Portugal 39, mostly at the dataset edges and
on 2 January 2015. They are filled with the mean of the same hour one week
before and after (falling back to the neighbouring day) and marked
`is_imputed`, so every downstream model can filter them out. A dbt test fails
if the imputed share ever exceeds 0.5 percent, which would signal a changed
source rather than a few gaps.

**Data window starts 2014-12-31 23:00 UTC.** That instant is midnight on 1
January 2015 in Madrid, so Spain's local calendar starts on a complete day.
Portugal gets one stray hour in 2014 which the daily mart drops because the day
is incomplete.

**Recency is checked against the documented coverage end, not the wall clock.**
The OPSD release is frozen at 2020-09-30, so a `dbt source freshness` check on
load time would always pass or always fail. The `recency` test asserts the
newest timestamp reaches the documented end of the release, which is what
actually goes wrong in practice: a truncated download. Source freshness on
`ingested_at` is kept as well so a stale warehouse still warns.

**The DST tests were verified to fail.** Replacing the tz-aware conversion with a
fixed `+1 hour` offset made 22 local days have the wrong hour count and 34
transition hours the wrong multiplicity. That mistake is the most common silent
bug in this dataset, so the tests exist specifically to catch it, and this is
the documented failure in the README.

**Custom generic tests instead of dbt_utils.** `accepted_range` and `recency`
are ten lines each. Pulling dbt_utils would add a `dbt deps` network step to
every CI run for two macros.
