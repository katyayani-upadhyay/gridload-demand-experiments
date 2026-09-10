from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from gridload.causal.did import (
    add_year_over_year_change,
    estimate_did,
    monthly_gap_event_study,
    pre_trend_slope,
    weekly_event_study,
    year_over_year_change,
)


def _synthetic_hourly(
    effect_log: float, seed: int = 0, country_seasonality: float = 0.0
) -> pd.DataFrame:
    """Two countries, hourly, from 2019 so the year-over-year outcome exists.

    `country_seasonality` adds an annual cycle to Spain only, which biases a
    levels DiD but cancels in the year-over-year specification."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("2019-01-01", "2020-04-30 23:00", freq="h")
    hours = np.arange(len(index))
    common = 0.15 * np.sin(2 * np.pi * (hours % 24) / 24) - 0.0005 * hours / 24
    annual = np.cos(2 * np.pi * index.dayofyear / 365.25)
    frames = []
    for country, level in (("ES", np.log(28000)), ("PT", np.log(5500))):
        post = (index >= pd.Timestamp("2020-03-14")).astype(float)
        treated_shift = effect_log * post if country == "ES" else 0.0
        own_season = country_seasonality * annual if country == "ES" else 0.0
        log_load = level + common + own_season + treated_shift + rng.normal(0, 0.02, len(index))
        frames.append(
            pd.DataFrame(
                {
                    "country_code": country,
                    "utc_timestamp": index,
                    "local_timestamp": index,
                    "local_date": index.normalize(),
                    "local_hour": index.hour,
                    "day_of_week": index.dayofweek,
                    "is_weekend": index.dayofweek >= 5,
                    "load_mw": np.exp(log_load),
                    "is_imputed": False,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _synthetic_daily(trend_gap_per_year: float = 0.0, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", "2020-09-30", freq="D")
    years = (dates - dates[0]).days / 365.25
    season = 0.08 * np.cos(2 * np.pi * dates.dayofyear / 365.25)
    frames = []
    for country, level in (("ES", np.log(28000)), ("PT", np.log(5500))):
        drift = trend_gap_per_year * years if country == "ES" else 0.0
        drop = np.where((dates >= "2020-03-14") & (country == "ES"), -0.10, 0.0)
        log_load = level + season + drift + drop + rng.normal(0, 0.03, len(dates))
        frames.append(
            pd.DataFrame(
                {
                    "country_code": country,
                    "local_date": dates,
                    "mean_load_mw": np.exp(log_load),
                    "total_mwh": np.exp(log_load) * 24,
                    "is_weekend": dates.dayofweek >= 5,
                    "n_imputed_hours": 0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _analysis_window(hourly: pd.DataFrame) -> pd.DataFrame:
    return hourly[hourly["local_date"] >= "2020-01-01"]


@pytest.mark.parametrize("specification", ["yoy", "levels"])
def test_did_recovers_known_effect(specification: str) -> None:
    truth = -0.12
    hourly = _synthetic_hourly(truth)
    frame = add_year_over_year_change(hourly) if specification == "yoy" else hourly
    result = estimate_did(_analysis_window(frame), date(2020, 3, 14), specification=specification)
    assert result.specification == specification
    assert result.coefficient == pytest.approx(truth, abs=0.01)
    assert result.ci_low < truth < result.ci_high
    assert result.effect_pct == pytest.approx(np.expm1(truth), abs=0.01)
    assert result.p_value < 1e-6


def test_did_finds_nothing_when_there_is_no_effect() -> None:
    frame = add_year_over_year_change(_synthetic_hourly(0.0, seed=3))
    result = estimate_did(_analysis_window(frame), date(2020, 3, 14))
    assert abs(result.coefficient) < 0.01
    assert result.ci_low < 0 < result.ci_high


def test_year_over_year_spec_removes_country_specific_seasonality() -> None:
    truth = -0.10
    hourly = _synthetic_hourly(truth, seed=8, country_seasonality=0.08)
    levels = estimate_did(_analysis_window(hourly), date(2020, 3, 14), specification="levels")
    yoy = estimate_did(
        _analysis_window(add_year_over_year_change(hourly)), date(2020, 3, 14), specification="yoy"
    )
    assert abs(levels.coefficient - truth) > 0.02
    assert yoy.coefficient == pytest.approx(truth, abs=0.01)


def test_weekly_event_study_is_flat_before_and_shifted_after() -> None:
    truth = -0.12
    yoy = _analysis_window(add_year_over_year_change(_synthetic_hourly(truth, seed=2)))
    study = weekly_event_study(yoy, date(2020, 3, 14))
    pre = study[study["weeks_from_event"] < 0]
    post = study[study["weeks_from_event"] >= 1]
    assert pre["coefficient"].abs().max() < 0.02
    assert post["coefficient"].mean() == pytest.approx(truth, abs=0.02)
    assert (post["ci_high"] < 0).all()
    assert pre["coefficient"].mean() == pytest.approx(0.0, abs=1e-9)
    assert study["ci_low"].isna().sum() == 1


def test_holiday_controls_only_enter_when_they_vary() -> None:
    hourly = _analysis_window(_synthetic_hourly(-0.05))
    calendars = {"ES": {date(2020, 4, 10)}, "PT": {date(2020, 4, 10)}}
    with_holidays = estimate_did(hourly, date(2020, 3, 14), holiday_calendars=calendars, specification="levels")
    without = estimate_did(hourly, date(2020, 3, 14), specification="levels")
    assert with_holidays.coefficient == pytest.approx(without.coefficient, abs=0.01)


def test_year_over_year_change_aligns_weekdays() -> None:
    hourly = _synthetic_hourly(0.0)
    merged = add_year_over_year_change(hourly)
    sample = merged.iloc[1000]
    prior = hourly[
        (hourly["country_code"] == sample["country_code"])
        & (hourly["local_timestamp"] == sample["local_timestamp"] - pd.Timedelta(days=364))
    ]
    assert prior["local_timestamp"].dt.dayofweek.item() == sample["local_timestamp"].dayofweek
    assert sample["load_prior_year_mw"] == pytest.approx(prior["load_mw"].item())


def test_event_study_is_flat_before_event_and_negative_after() -> None:
    study = monthly_gap_event_study(_synthetic_daily())
    pre = study[~study["is_post"]]
    post = study[study["is_post"] & (study["month"] >= "2020-04")]
    assert pre["coefficient"].abs().max() < 0.04
    assert (post["coefficient"] < -0.06).all()
    assert study.loc[study["month"] == "2020-02", "coefficient"].item() == 0.0
    slope, _ = pre_trend_slope(study)
    assert abs(slope) < 0.01


def test_pre_trend_slope_detects_drift() -> None:
    study = monthly_gap_event_study(_synthetic_daily(trend_gap_per_year=0.05))
    slope, p_value = pre_trend_slope(study)
    assert slope == pytest.approx(0.05, abs=0.01)
    assert p_value < 0.01


def test_year_over_year_change_on_constructed_drop() -> None:
    daily = _synthetic_daily(seed=4)
    change = year_over_year_change(daily, "ES", date(2020, 3, 14), date(2020, 4, 30))
    assert change == pytest.approx(np.expm1(-0.10), abs=0.02)
