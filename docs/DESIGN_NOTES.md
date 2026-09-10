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

## P2: forecasting

**Forecast origin is local midnight of the target day, so every lag is at least
24 hours.** Real day-ahead markets close around noon on D-1, but a single fixed
origin keeps the leakage rule simple enough to enforce with one constant
(`MIN_LAG_HOURS = 24`) and one test that corrupts all data from the origin
onward and checks the target day's features are unchanged. Rolling statistics
are computed on the series shifted by 24 hours for the same reason.

**Rolling-origin backtest with a 28-day refit, 2019-01 to 2020-09.** Refitting
daily would take 640 fits for no measurable gain; refitting every four weeks
gives 23 fits and still lets the model see the COVID regime shift within a
month. The window deliberately includes 2020 so the metrics show how both
models cope with a structural break, and the by-year table separates the two.

**Seasonal naive reads the precomputed 168-hour lag rather than shifting its
input.** The first version shifted whatever frame it was handed, which on a
test slice produced NaNs for the first week. Reading `lag_168h`, which is built
on the full history, makes the baseline valid on any slice and made the bug
impossible to reintroduce.

**LightGBM's native API, not the scikit-learn wrapper.** The wrapper imports
scikit-learn, a large dependency the project does not otherwise need.
`lgb.train` also exposes `num_threads`, which is pinned to at most four: with
the default all-cores setting OpenMP oversubscription made a two-second fit
take minutes on a laptop.

**WAPE is the primary metric.** It weights each hour's error by its load, which
is how forecast error costs a system operator (balancing energy is bought in
MWh, not in percentage points). MAPE and signed bias are reported alongside so
over- and under-forecasting are visible separately.

## P3: experimentation

**The experiment is simulated and says so in every artifact.** OPSD has no
household data, so the A/B test is generated by a seeded simulator with a known
6 percent peak reduction and 40 percent off-peak rebound. The decision document
and results JSON carry a `simulated: true` flag and an explicit disclaimer, and
the known truth is printed next to the estimate so a reader can check the
estimator recovers it.

**Analysis at the household level, the unit of randomisation.** Household-days
would inflate the sample 28-fold and understate the standard errors. Each
household contributes one pre-period and one post-period mean per metric.

**Peak window derived from the real load curve, restricted to the evening.**
The four highest-load hours of the Spanish system in 2019 were 11:00-13:00 and
21:00, because commercial demand drives a midday peak. A residential rebate
targets the household evening ramp, so the window is the highest-load
contiguous four-hour block starting at or after 17:00, which is 18:00-21:00.

**CUPED with the pre-period value of the same metric.** Theta is estimated on
the pooled sample, which is unbiased because the covariate is fixed before
assignment. The simulator's large between-household spread makes the variance
reduction unusually high (about 95 percent); real programmes typically see
30 to 60 percent.

**SRM uses alpha 0.001.** A sample ratio mismatch means the randomisation is
broken and nothing downstream is trustworthy, so the check should only halt the
analysis on strong evidence, not on ordinary sampling noise at 0.05.

**Ship rule is stated before the numbers are seen.** No SRM, CUPED CI for the
peak reduction entirely below zero, and every guardrail passing. Guardrails
are conservation (total daily kWh must not increase), rebound below half the
peak reduction, and an opt-out increase under three percentage points.

## P4: causal inference

**Year-over-year specification as the headline DiD.** The first estimate used
log load in levels with hour and weekday fixed effects and compared January to
mid-March against mid-March to April. The event study showed the Spain minus
Portugal gap has its own seasonal cycle (Spain's summer cooling load is
larger), so that comparison mixes the lockdown with the spring swing.
Differencing each hour against the same local hour 364 days earlier removes
each country's own seasonal profile and keeps weekdays aligned. The levels
estimate is still reported as a sensitivity check.

**Portugal was treated too, and the numbers say so.** Spain's raw load fell
13.8 percent year-over-year over 14 March to 30 April 2020 and Portugal's fell
9.4 percent. The DiD of about minus 2 percent is the part of Spain's decline
that exceeds Portugal's after netting out the 3 point gap that already existed
in January to March 2020. That is the honest estimand; the raw Spanish figure
is what press releases report and is what the sanity check compares against.

**Weekly event study normalised to the pre-period mean, not a single week.**
The week before the state of alarm was distorted by Carnival falling in a
different week of 2019, which shifted every coefficient when it served as the
reference. Averaging the pre-event weeks to zero removes the dependence on one
noisy week. The dynamics matter more than the window average: the effect
concentrates in the two weeks of Spain's total shutdown of non-essential
activity (30 March to 12 April), at roughly minus 8 to minus 9 percent.

**Per-country holiday indicators for both the current and prior-year date.**
Easter moved from 21 April 2019 to 12 April 2020, so a 364-day shift lines a
holiday up with an ordinary day. Flags for each country's own calendar on both
dates absorb that.

**Cluster by country x week.** Two countries are too few clusters, and hourly
observations within a week are strongly serially correlated. Week clusters give
36 groups and honest, wide confidence intervals.

## P5: orchestration

**A plain function per step, an argparse entry point, and a Makefile.** The
orchestrator has no scheduler, retries or state: each step is a function taking
`Settings`, and `run()` just calls them in order and logs timings. An Airflow
DAG can wrap each function in a PythonOperator later. dbt is invoked as a
subprocess through the same interpreter so the venv is always the one used.

**Long runs are wrapped in `caffeinate` locally.** Several multi-minute steps
took hours of wall-clock time during development with almost no CPU. The cause
was the laptop idling, not the code; the Makefile does not depend on it.

## P6: dashboard and deployment

**The dashboard reads only `reports/`.** Streamlit Community Cloud has no
DuckDB file, no OPSD download and no time budget for a LightGBM backtest. Every
number and curve the page shows comes from the small CSV, JSON and Parquet
artifacts the pipeline commits, so the live app is a faithful view of the last
`make all` and deploys in seconds.

**A dashboard-only `requirements.txt` next to the full `pyproject.toml`.**
Community Cloud installs from `requirements.txt`; listing only Streamlit,
Plotly, pandas and pyarrow keeps the cold start short and avoids compiling
LightGBM or dbt on the hosting side.

**The dashboard has a pytest smoke test.** `streamlit.testing.v1.AppTest`
renders the whole app headlessly and fails on any exception, and a second test
asserts every artifact the page reads is committed. A missing report file
therefore breaks CI instead of the live page.

## P7: CI and documentation

**CI runs the real pipeline, not a mock.** The workflow downloads the OPSD CSV
(cached by URL between runs), loads DuckDB, runs `dbt build` with all 56 tests,
then a short forecast backtest plus the experiment and causal steps. The whole
job takes about a minute, so there was no reason to stub anything.

**Two CI-only failures and their fixes.** `astral-sh/setup-uv` pre-creates
`.venv` when given a Python version, so `uv venv` now runs with `--clear`. And
statsmodels' `solve_power` returned a one-element array on the runner where it
returned a float locally; both power helpers now squeeze to a scalar. Neither
showed up locally, which is the point of running the pipeline in CI.

**README order follows the brief and stays under 1,500 words.** Live link
first, architecture, problem framing, one metrics table per phase, stack,
quickstart, the DST failure, limitations, references. The metrics are copied
from the committed reports rather than re-derived so the README and the
dashboard cannot disagree.
