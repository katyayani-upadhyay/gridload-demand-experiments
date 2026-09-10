"""Difference-in-differences estimator and event study.

Treated unit: Spain (state of alarm declared 14 March 2020). Control: Portugal,
which shares the Iberian market and climate but locked down later and less
strictly. Both countries were affected, so every estimate here is the
differential effect of Spain's earlier and stricter lockdown relative to
Portugal, not the total effect of the pandemic on Spanish demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

TREATED = "ES"
CONTROL = "PT"
EVENT_DATE = date(2020, 3, 14)
PRE_START = date(2020, 1, 1)
POST_END = date(2020, 4, 30)
EVENT_STUDY_REFERENCE_MONTH = "2020-02"
YOY_DAYS = 364
SEASONAL_BASELINE_YEARS = range(2015, 2020)


@dataclass(frozen=True)
class DidResult:
    specification: str
    coefficient: float
    std_error: float
    ci_low: float
    ci_high: float
    p_value: float
    effect_pct: float
    effect_ci_low_pct: float
    effect_ci_high_pct: float
    n_obs: int
    n_clusters: int
    pre_start: date
    event_date: date
    post_end: date

    def to_dict(self) -> dict[str, object]:
        out = self.__dict__.copy()
        for key in ("pre_start", "event_date", "post_end"):
            out[key] = out[key].isoformat()
        return out


def load_hourly_panel(duckdb_path: Path, start: date, end: date) -> pd.DataFrame:
    query = """
        select country_code, utc_timestamp, local_timestamp, local_date, local_hour,
               day_of_week, is_weekend, load_mw, is_imputed
        from marts.fct_load_hourly
        where local_date between ? and ?
        order by country_code, utc_timestamp
    """
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        frame = con.execute(query, [start, end]).df()
    frame["local_date"] = pd.to_datetime(frame["local_date"])
    return frame


def load_daily_panel(duckdb_path: Path) -> pd.DataFrame:
    query = """
        select country_code, local_date, mean_load_mw, total_mwh, is_weekend, n_imputed_hours
        from marts.fct_load_daily
        order by country_code, local_date
    """
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        frame = con.execute(query).df()
    frame["local_date"] = pd.to_datetime(frame["local_date"])
    return frame


def add_year_over_year_change(hourly: pd.DataFrame, days_back: int = YOY_DAYS) -> pd.DataFrame:
    """Attach log(load) minus log(load at the same local hour 52 weeks earlier).

    Differencing against the prior year removes each country's own seasonal
    profile, so the DiD only has to assume the two countries' year-over-year
    paths would have moved together, a far weaker requirement than assuming
    their seasonal cycles are identical. 364 days keeps weekdays aligned."""
    prior = hourly[["country_code", "local_timestamp", "load_mw"]].copy()
    prior["local_timestamp"] = prior["local_timestamp"] + pd.Timedelta(days=days_back)
    merged = hourly.merge(
        prior.rename(columns={"load_mw": "load_prior_year_mw"}),
        on=["country_code", "local_timestamp"],
        how="inner",
    )
    merged["local_timestamp_prior"] = merged["local_timestamp"] - pd.Timedelta(days=days_back)
    merged["yoy_log_change"] = np.log(merged["load_mw"]) - np.log(merged["load_prior_year_mw"])
    return merged


HolidayCalendars = dict[str, set[date]]


def _holiday_flags(
    frame: pd.DataFrame, calendars: HolidayCalendars | None, include_prior: bool = False
) -> list[str]:
    """Add per-country holiday indicators and return the formula terms that vary."""
    if not calendars:
        return []
    frame["is_holiday"] = [
        d in calendars.get(c, set()) for c, d in zip(frame["country_code"], frame["local_date"].dt.date, strict=True)
    ]
    terms = ["is_holiday"]
    if include_prior and "local_timestamp_prior" in frame:
        prior_dates = frame["local_timestamp_prior"].dt.date
        frame["is_holiday_prior"] = [
            d in calendars.get(c, set()) for c, d in zip(frame["country_code"], prior_dates, strict=True)
        ]
        terms.append("is_holiday_prior")
    for term in terms:
        frame[term] = frame[term].astype(int)
    return [t for t in terms if frame[t].nunique() > 1]


def estimate_did(
    hourly: pd.DataFrame,
    event_date: date = EVENT_DATE,
    treated: str = TREATED,
    holiday_calendars: HolidayCalendars | None = None,
    specification: str = "yoy",
) -> DidResult:
    """Two-by-two DiD on hourly data with two specifications.

    `yoy` (primary): outcome is the year-over-year log change, no further
    controls. `levels`: outcome is log load with hour-of-day, weekday and
    holiday fixed effects; it is reported as a sensitivity check because it
    assumes the Spain-Portugal gap has no seasonal cycle of its own.

    Standard errors are clustered by country and ISO week. With only two
    countries, clustering at the country level is impossible, so week clusters
    absorb the within-week serial correlation that would otherwise make hourly
    observations look far more informative than they are."""
    frame = hourly.copy()
    frame["treated"] = (frame["country_code"] == treated).astype(int)
    frame["post"] = (frame["local_date"] >= pd.Timestamp(event_date)).astype(int)
    iso = frame["local_date"].dt.isocalendar()
    frame["cluster"] = frame["country_code"] + "_" + iso["year"].astype(str) + "_" + iso["week"].astype(str)

    if specification == "yoy":
        if "yoy_log_change" not in frame:
            raise ValueError("yoy specification needs add_year_over_year_change() first")
        controls = _holiday_flags(frame, holiday_calendars, include_prior=True)
        formula = " + ".join(["yoy_log_change ~ treated + post + treated:post", *controls])
    elif specification == "levels":
        frame["log_load"] = np.log(frame["load_mw"])
        controls = _holiday_flags(frame, holiday_calendars)
        formula = " + ".join(
            ["log_load ~ treated + post + treated:post + C(local_hour) + C(day_of_week)", *controls]
        )
    else:
        raise ValueError(f"unknown specification {specification!r}")

    model = smf.ols(formula, data=frame).fit(
        cov_type="cluster", cov_kwds={"groups": frame["cluster"]}
    )

    term = "treated:post"
    coef = float(model.params[term])
    se = float(model.bse[term])
    ci = model.conf_int().loc[term]
    return DidResult(
        specification=specification,
        coefficient=coef,
        std_error=se,
        ci_low=float(ci.iloc[0]),
        ci_high=float(ci.iloc[1]),
        p_value=float(model.pvalues[term]),
        effect_pct=float(np.expm1(coef)),
        effect_ci_low_pct=float(np.expm1(ci.iloc[0])),
        effect_ci_high_pct=float(np.expm1(ci.iloc[1])),
        n_obs=int(model.nobs),
        n_clusters=int(frame["cluster"].nunique()),
        pre_start=frame["local_date"].min().date(),
        event_date=event_date,
        post_end=frame["local_date"].max().date(),
    )


def monthly_gap_event_study(
    daily: pd.DataFrame,
    reference_month: str = EVENT_STUDY_REFERENCE_MONTH,
    treated: str = TREATED,
    control: str = CONTROL,
    seasonal_baseline_years: range = SEASONAL_BASELINE_YEARS,
) -> pd.DataFrame:
    """Treated minus control gap in log daily load, by month, relative to a reference month.

    The daily gap is first seasonally adjusted by subtracting the calendar
    month's mean gap over the baseline years, because the Spain-Portugal gap
    has a seasonal cycle of its own (Spain's summer cooling load is larger).
    Under parallel trends the pre-event coefficients then scatter around zero
    with no drift. Standard errors are Newey-West with 14 lags on the daily
    series."""
    wide = (
        daily.assign(log_load=np.log(daily["mean_load_mw"]))
        .pivot(index="local_date", columns="country_code", values="log_load")
        .dropna()
    )
    gap = (wide[treated] - wide[control]).rename("raw_gap").to_frame()
    gap["month_of_year"] = gap.index.month
    baseline = gap[gap.index.year.isin(list(seasonal_baseline_years))]
    seasonal_norm = baseline.groupby("month_of_year")["raw_gap"].mean()
    gap["gap"] = gap["raw_gap"] - gap["month_of_year"].map(seasonal_norm)
    gap["month"] = gap.index.to_period("M").astype(str)
    gap["month"] = pd.Categorical(gap["month"], categories=sorted(gap["month"].unique()))

    model = smf.ols(
        f"gap ~ C(month, Treatment(reference='{reference_month}'))", data=gap
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 14})
    ci = model.conf_int()

    rows = [
        {"month": reference_month, "coefficient": 0.0, "std_error": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    ]
    for name, value in model.params.items():
        if name == "Intercept":
            continue
        month = name.split("[T.")[1].rstrip("]")
        rows.append(
            {
                "month": month,
                "coefficient": float(value),
                "std_error": float(model.bse[name]),
                "ci_low": float(ci.loc[name].iloc[0]),
                "ci_high": float(ci.loc[name].iloc[1]),
            }
        )
    study = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    study["is_post"] = study["month"] >= "2020-03"
    monthly = gap.groupby("month", observed=True)[["raw_gap", "gap"]].mean().reindex(study["month"])
    study["mean_raw_gap"] = monthly["raw_gap"].to_numpy()
    study["mean_adjusted_gap"] = monthly["gap"].to_numpy()
    return study


def weekly_event_study(
    yoy: pd.DataFrame,
    event_date: date = EVENT_DATE,
    treated: str = TREATED,
    holiday_calendars: HolidayCalendars | None = None,
) -> pd.DataFrame:
    """Week-by-week differential year-over-year change, normalised to the pre-event mean.

    Coefficients on treated x week give the dynamic path of the effect. They are
    estimated relative to the week before the event and then shifted so the
    pre-event weeks average zero, because a single reference week can be
    distorted by a holiday that fell in a different week the year before.
    Standard errors are clustered by country and day."""
    frame = yoy.copy()
    frame["treated"] = (frame["country_code"] == treated).astype(int)
    week_start = frame["local_date"] - pd.to_timedelta(frame["local_date"].dt.dayofweek, unit="D")
    frame["week"] = week_start.dt.strftime("%Y-%m-%d")
    event_week_start = pd.Timestamp(event_date) - pd.Timedelta(days=pd.Timestamp(event_date).dayofweek)
    reference = (event_week_start - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    frame["cluster"] = frame["country_code"] + "_" + frame["local_date"].dt.strftime("%Y-%m-%d")
    controls = _holiday_flags(frame, holiday_calendars, include_prior=True)
    formula = " + ".join(
        [f"yoy_log_change ~ treated * C(week, Treatment(reference='{reference}'))", *controls]
    )
    model = smf.ols(formula, data=frame).fit(cov_type="cluster", cov_kwds={"groups": frame["cluster"]})
    ci = model.conf_int()
    rows = [
        {"week_start": reference, "coefficient": 0.0, "std_error": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    ]
    for name, value in model.params.items():
        if not name.startswith("treated:C(week"):
            continue
        week = name.split("[T.")[1].rstrip("]")
        rows.append(
            {
                "week_start": week,
                "coefficient": float(value),
                "std_error": float(model.bse[name]),
                "ci_low": float(ci.loc[name].iloc[0]),
                "ci_high": float(ci.loc[name].iloc[1]),
            }
        )
    study = pd.DataFrame(rows).sort_values("week_start").reset_index(drop=True)
    study["weeks_from_event"] = (
        (pd.to_datetime(study["week_start"]) - event_week_start).dt.days // 7
    )
    study["is_post"] = study["weeks_from_event"] >= 0
    pre_mean = study.loc[~study["is_post"], "coefficient"].mean()
    for col in ("coefficient", "ci_low", "ci_high"):
        study[col] = study[col] - pre_mean
    return study


def pre_trend_slope(study: pd.DataFrame) -> tuple[float, float]:
    """Slope (per year) of the pre-event event-study coefficients and its p-value.

    A slope indistinguishable from zero is the quantitative check behind the
    parallel-trends plot."""
    pre = study[~study["is_post"]].copy()
    pre["t_years"] = np.arange(len(pre)) / 12.0
    fit = smf.ols("coefficient ~ t_years", data=pre).fit()
    return float(fit.params["t_years"]), float(fit.pvalues["t_years"])


def year_over_year_change(
    daily: pd.DataFrame, country: str, start: date, end: date
) -> float:
    """Raw change in mean load versus the same calendar window one year earlier.

    This is what press releases report and what the DiD is sanity-checked
    against. It is not weather- or calendar-adjusted."""
    this_year = daily[
        (daily["country_code"] == country)
        & (daily["local_date"] >= pd.Timestamp(start))
        & (daily["local_date"] <= pd.Timestamp(end))
    ]["mean_load_mw"].mean()
    prior = daily[
        (daily["country_code"] == country)
        & (daily["local_date"] >= pd.Timestamp(start) - pd.DateOffset(years=1))
        & (daily["local_date"] <= pd.Timestamp(end) - pd.DateOffset(years=1))
    ]["mean_load_mw"].mean()
    return float(this_year / prior - 1.0)
