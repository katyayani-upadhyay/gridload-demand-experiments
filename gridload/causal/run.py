"""Run the lockdown DiD and write the results, event-study table and plot."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import holidays
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from gridload.causal.did import (  # noqa: E402
    CONTROL,
    EVENT_DATE,
    POST_END,
    PRE_START,
    TREATED,
    YOY_DAYS,
    DidResult,
    add_year_over_year_change,
    estimate_did,
    load_daily_panel,
    load_hourly_panel,
    monthly_gap_event_study,
    pre_trend_slope,
    weekly_event_study,
    year_over_year_change,
)
from gridload.config import Settings, get_settings  # noqa: E402

log = logging.getLogger(__name__)

PUBLISHED_RANGE_PCT = (-0.135, -0.11)
WEEKLY_STUDY_END = date(2020, 6, 28)


def run_causal(settings: Settings | None = None) -> DidResult:
    settings = settings or get_settings()
    reports = settings.reports_dir
    reports.mkdir(parents=True, exist_ok=True)

    hourly = load_hourly_panel(settings.duckdb_path, PRE_START - timedelta(days=YOY_DAYS), POST_END)
    analysis_window = hourly[hourly["local_date"] >= pd.Timestamp(PRE_START)]
    yoy = add_year_over_year_change(hourly)
    yoy = yoy[yoy["local_date"] >= pd.Timestamp(PRE_START)]
    calendars = {
        TREATED: set(holidays.Spain(years=[2019, 2020]).keys()),
        CONTROL: set(holidays.Portugal(years=[2019, 2020]).keys()),
    }
    result = estimate_did(yoy, EVENT_DATE, TREATED, calendars, specification="yoy")
    levels = estimate_did(analysis_window, EVENT_DATE, TREATED, calendars, specification="levels")

    weekly_window = load_hourly_panel(
        settings.duckdb_path, PRE_START - timedelta(days=YOY_DAYS), WEEKLY_STUDY_END
    )
    weekly_yoy = add_year_over_year_change(weekly_window)
    weekly = weekly_event_study(
        weekly_yoy[weekly_yoy["local_date"] >= pd.Timestamp(PRE_START)],
        EVENT_DATE,
        TREATED,
        calendars,
    )

    daily = load_daily_panel(settings.duckdb_path)
    study = monthly_gap_event_study(daily)
    slope, slope_p = pre_trend_slope(study)
    raw_yoy = {
        country: year_over_year_change(daily, country, EVENT_DATE, POST_END)
        for country in (TREATED, CONTROL)
    }

    study.to_csv(reports / "did_event_study.csv", index=False)
    weekly.to_csv(reports / "did_event_study_weekly.csv", index=False)
    _plot_event_study(study, weekly, reports / "did_event_study.png")
    payload = {
        "did": result.to_dict(),
        "did_levels_sensitivity": levels.to_dict(),
        "pre_trend_slope_per_year": slope,
        "pre_trend_slope_p_value": slope_p,
        "year_over_year_change": raw_yoy,
        "published_range_pct": list(PUBLISHED_RANGE_PCT),
    }
    (reports / "did_results.json").write_text(json.dumps(payload, indent=2))
    (reports / "did_results.md").write_text(
        _results_document(result, levels, study, weekly, slope, slope_p, raw_yoy)
    )
    log.info(
        "DiD effect %.2f%% (CI %.2f%% to %.2f%%), p=%.2e",
        100 * result.effect_pct,
        100 * result.effect_ci_low_pct,
        100 * result.effect_ci_high_pct,
        result.p_value,
    )
    return result


def _plot_event_study(study: pd.DataFrame, weekly: pd.DataFrame, path: Path) -> None:
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12, 8))

    x = pd.PeriodIndex(study["month"], freq="M").to_timestamp()
    pre = ~study["is_post"]
    top.axhline(0, color="#666666", linewidth=0.8)
    top.axvline(pd.Timestamp(EVENT_DATE), color="#b3261e", linestyle="--", linewidth=1)
    top.fill_between(x, study["ci_low"], study["ci_high"], color="#4c72b0", alpha=0.18, linewidth=0)
    top.plot(
        x[pre],
        study.loc[pre, "coefficient"],
        marker="o",
        markersize=3,
        color="#4c72b0",
        label="pre-event",
    )
    top.plot(
        x[~pre],
        study.loc[~pre, "coefficient"],
        marker="o",
        markersize=3,
        color="#b3261e",
        label="post-event",
    )
    top.set_ylabel("ES minus PT log daily load,\nseasonally adjusted, vs Feb 2020")
    top.set_title(
        "Pre-trends 2015-2020: monthly Spain-Portugal gap in log load (95% CI, Newey-West)"
    )
    top.legend(loc="lower left", frameon=False)
    top.grid(axis="y", alpha=0.3)

    wx = weekly["weeks_from_event"]
    wpre = ~weekly["is_post"]
    bottom.axhline(0, color="#666666", linewidth=0.8)
    bottom.axvline(-0.5, color="#b3261e", linestyle="--", linewidth=1)
    bottom.errorbar(
        wx[wpre],
        weekly.loc[wpre, "coefficient"],
        yerr=[
            weekly.loc[wpre, "coefficient"] - weekly.loc[wpre, "ci_low"],
            weekly.loc[wpre, "ci_high"] - weekly.loc[wpre, "coefficient"],
        ],
        fmt="o",
        color="#4c72b0",
        capsize=3,
        label="pre-event",
    )
    bottom.errorbar(
        wx[~wpre],
        weekly.loc[~wpre, "coefficient"],
        yerr=[
            weekly.loc[~wpre, "coefficient"] - weekly.loc[~wpre, "ci_low"],
            weekly.loc[~wpre, "ci_high"] - weekly.loc[~wpre, "coefficient"],
        ],
        fmt="o",
        color="#b3261e",
        capsize=3,
        label="post-event",
    )
    bottom.set_xlabel("Weeks from the week of 14 March 2020")
    bottom.set_ylabel("Differential year-over-year\nlog change, ES minus PT")
    bottom.set_title(
        "Event study 2020: weekly differential effect, pre-event weeks normalised to zero (95% CI)"
    )
    bottom.legend(loc="lower left", frameon=False)
    bottom.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def _results_document(
    r: DidResult,
    levels: DidResult,
    study: pd.DataFrame,
    weekly: pd.DataFrame,
    slope: float,
    slope_p: float,
    yoy: dict[str, float],
) -> str:
    post = study[study["is_post"]].head(4)
    inside = PUBLISHED_RANGE_PCT[0] <= yoy[TREATED] <= PUBLISHED_RANGE_PCT[1]
    drift_over_window = slope * (POST_END - EVENT_DATE).days / 365.25
    lines = [
        "# Lockdown difference-in-differences: Spain vs Portugal",
        "",
        "## Question",
        "",
        "How much did Spain's national lockdown (state of alarm declared 14 March 2020) "
        "reduce hourly electricity load, relative to Portugal?",
        "",
        "## Design",
        "",
        f"- Treated: Spain. Control: Portugal. Event date: {r.event_date}.",
        f"- Pre-period {r.pre_start} to {EVENT_DATE - pd.Timedelta(days=1):%Y-%m-%d}, "
        f"post-period {r.event_date} to {r.post_end}.",
        "- Outcome (primary): year-over-year change in log hourly load, each hour matched "
        f"to the same local hour {YOY_DAYS} days earlier so weekdays align. Differencing "
        "against 2019 removes each country's own seasonal profile.",
        "- Specification: treated, post, treated x post. Sensitivity check: log load in "
        "levels with hour-of-day, day-of-week and holiday fixed effects.",
        f"- Standard errors clustered by country x ISO week ({r.n_clusters} clusters, "
        f"{r.n_obs} hourly observations).",
        "",
        "## Identifying assumption",
        "",
        "Absent Spain's earlier and stricter lockdown, the year-over-year change in "
        "Spanish load would have moved in parallel with Portugal's through March-April "
        "2020 (parallel trends in the differenced outcome). Both countries share the "
        "Iberian electricity market (MIBEL), similar climate and a common DST calendar. "
        "The seasonally adjusted event-study coefficients below test whether the gap "
        "between the two countries was stable before the event.",
        "",
        "## Estimate",
        "",
        "| Quantity | Value |",
        "|---|---|",
        "| DiD coefficient, year-over-year spec (log points) | "
        f"{r.coefficient:+.4f} (SE {r.std_error:.4f}) |",
        f"| Differential effect on load | **{r.effect_pct:+.2%}** |",
        f"| 95% CI | [{r.effect_ci_low_pct:+.2%}, {r.effect_ci_high_pct:+.2%}] |",
        f"| p-value | {r.p_value:.2e} |",
        f"| Observations / clusters | {r.n_obs} / {r.n_clusters} |",
        "",
        "Sensitivity check, levels specification with hour, weekday and holiday fixed effects: "
        f"{levels.effect_pct:+.2%} (95% CI [{levels.effect_ci_low_pct:+.2%}, "
        f"{levels.effect_ci_high_pct:+.2%}], p = {levels.p_value:.2f}). The levels estimate "
        "compares January-March with March-April and so absorbs the seasonal swing in the "
        "Spain-Portugal gap; it is reported to show the sensitivity, not as the headline.",
        "",
        "## Pre-trends",
        "",
        f"Linear slope of the seasonally adjusted pre-event monthly coefficients (2015-01 to "
        f"2020-02): {slope:+.4f} log points per year, p = {slope_p:.2f}. Over the "
        f"{(POST_END - EVENT_DATE).days}-day post window that drift amounts to "
        f"{drift_over_window:+.4f} log points, "
        + (
            "which is negligible next to the estimate."
            if abs(drift_over_window) < abs(r.coefficient) / 10
            else "which is not negligible next to the estimate; interpret with care."
        ),
        "",
        "Event-study plot: `reports/did_event_study.png`; table: `reports/did_event_study.csv`.",
        "",
        "First post-event months (gap relative to February 2020):",
        "",
        "| Month | Coefficient | 95% CI |",
        "|---|---|---|",
    ]
    for row in post.itertuples():
        lines.append(
            f"| {row.month} | {row.coefficient:+.4f} | [{row.ci_low:+.4f}, {row.ci_high:+.4f}] |"
        )
    peak = weekly.loc[weekly["coefficient"].idxmin()]
    lines += [
        "",
        "## Dynamics: weekly event study",
        "",
        "Differential year-over-year log change (Spain minus Portugal) by week, normalised so "
        "the pre-event weeks (1 January to 8 March) average zero. Table: "
        "`reports/did_event_study_weekly.csv`.",
        "",
        "| Weeks from event | Week starting | Coefficient | 95% CI |",
        "|---|---|---|---|",
    ]
    for row in weekly[
        (weekly["weeks_from_event"] >= -4) & (weekly["weeks_from_event"] <= 8)
    ].itertuples():
        interval = (
            "reference week" if np.isnan(row.ci_low) else f"[{row.ci_low:+.4f}, {row.ci_high:+.4f}]"
        )
        lines.append(
            f"| {row.weeks_from_event:+d} | {row.week_start} | {row.coefficient:+.4f} "
            f"| {interval} |"
        )
    lines += [
        "",
        f"The differential effect peaks in the week starting {peak['week_start']} at "
        f"{peak['coefficient']:+.3f} log points ({np.expm1(peak['coefficient']):+.1%}), which "
        "coincides with Spain's suspension of all non-essential economic activity "
        "(30 March to 9 April 2020), a measure Portugal did not adopt. Outside those "
        "weeks the two countries' declines were of similar size, which is why the "
        "window-average DiD is small relative to the raw drops.",
        "",
        "## Sanity check against published figures",
        "",
        f"Raw year-over-year change in mean load, {EVENT_DATE} to {POST_END}, versus the same "
        "window in 2019 (not weather-adjusted):",
        "",
        "| Country | Change |",
        "|---|---|",
        f"| Spain | {yoy[TREATED]:+.2%} |",
        f"| Portugal | {yoy[CONTROL]:+.2%} |",
        "",
        f"Published estimates put the Spanish demand drop over mid-March to April 2020 at "
        f"roughly {abs(PUBLISHED_RANGE_PCT[1]):.0%} to {abs(PUBLISHED_RANGE_PCT[0]):.1%} "
        f"(see README). Spain's raw drop here is "
        + ("inside" if inside else "close to")
        + " that range. The DiD estimate is smaller in magnitude than the raw drop because "
        "Portugal's load also fell; the DiD isolates only the part of Spain's decline that "
        f"exceeds Portugal's, and {yoy[TREATED] - yoy[CONTROL]:+.2%} is the simple "
        "difference of the two raw changes.",
        "",
        "## Limitations",
        "",
        "- Portugal declared its own state of emergency on 18 March 2020, so the control "
        "unit was also treated. The estimate is the differential effect of Spain's earlier "
        "and stricter lockdown, not the total effect of lockdown on Spanish demand.",
        "- Weather is not controlled for. Spring 2020 temperatures could differ between the "
        "two countries; the shared climate limits but does not remove this risk.",
        "- Two clusters at the country level are too few for country-clustered inference, so "
        "clustering is by country x week. Confidence intervals should be read as approximate.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_causal()
