# Lockdown difference-in-differences: Spain vs Portugal

## Question

How much did Spain's national lockdown (state of alarm declared 14 March 2020) reduce hourly electricity load, relative to Portugal?

## Design

- Treated: Spain. Control: Portugal. Event date: 2020-03-14.
- Pre-period 2020-01-01 to 2020-03-13, post-period 2020-03-14 to 2020-04-30.
- Outcome (primary): year-over-year change in log hourly load, each hour matched to the same local hour 364 days earlier so weekdays align. Differencing against 2019 removes each country's own seasonal profile.
- Specification: treated, post, treated x post. Sensitivity check: log load in levels with hour-of-day, day-of-week and holiday fixed effects.
- Standard errors clustered by country x ISO week (36 clusters, 5806 hourly observations).

## Identifying assumption

Absent Spain's earlier and stricter lockdown, the year-over-year change in Spanish load would have moved in parallel with Portugal's through March-April 2020 (parallel trends in the differenced outcome). Both countries share the Iberian electricity market (MIBEL), similar climate and a common DST calendar. The seasonally adjusted event-study coefficients below test whether the gap between the two countries was stable before the event.

## Estimate

| Quantity | Value |
|---|---|
| DiD coefficient, year-over-year spec (log points) | -0.0219 (SE 0.0321) |
| Differential effect on load | **-2.17%** |
| 95% CI | [-8.12%, +4.18%] |
| p-value | 4.94e-01 |
| Observations / clusters | 5806 / 36 |

Sensitivity check, levels specification with hour, weekday and holiday fixed effects: -2.46% (95% CI [-9.06%, +4.61%], p = 0.49). The levels estimate compares January-March with March-April and so absorbs the seasonal swing in the Spain-Portugal gap; it is reported to show the sensitivity, not as the headline.

## Pre-trends

Linear slope of the seasonally adjusted pre-event monthly coefficients (2015-01 to 2020-02): -0.0063 log points per year, p = 0.00. Over the 47-day post window that drift amounts to -0.0008 log points, which is negligible next to the estimate.

Event-study plot: `reports/did_event_study.png`; table: `reports/did_event_study.csv`.

First post-event months (gap relative to February 2020):

| Month | Coefficient | 95% CI |
|---|---|---|
| 2020-03 | -0.0064 | [-0.0258, +0.0131] |
| 2020-04 | -0.0454 | [-0.0842, -0.0066] |
| 2020-05 | +0.0077 | [-0.0115, +0.0269] |
| 2020-06 | +0.0136 | [-0.0088, +0.0359] |

## Dynamics: weekly event study

Differential year-over-year log change (Spain minus Portugal) by week, normalised so the pre-event weeks (1 January to 8 March) average zero. Table: `reports/did_event_study_weekly.csv`.

| Weeks from event | Week starting | Coefficient | 95% CI |
|---|---|---|---|
| -4 | 2020-02-10 | -0.0113 | [-0.0695, +0.0469] |
| -3 | 2020-02-17 | +0.0117 | [-0.0462, +0.0695] |
| -2 | 2020-02-24 | +0.0138 | [-0.0656, +0.0932] |
| -1 | 2020-03-02 | -0.0235 | reference week |
| +0 | 2020-03-09 | +0.0147 | [-0.0445, +0.0739] |
| +1 | 2020-03-16 | -0.0213 | [-0.0952, +0.0526] |
| +2 | 2020-03-23 | +0.0177 | [-0.0410, +0.0764] |
| +3 | 2020-03-30 | -0.0881 | [-0.1568, -0.0194] |
| +4 | 2020-04-06 | -0.0864 | [-0.1573, -0.0154] |
| +5 | 2020-04-13 | +0.0536 | [-0.0327, +0.1398] |
| +6 | 2020-04-20 | -0.0024 | [-0.0852, +0.0805] |
| +7 | 2020-04-27 | +0.0071 | [-0.0546, +0.0689] |
| +8 | 2020-05-04 | +0.0298 | [-0.0294, +0.0891] |

The differential effect peaks in the week starting 2020-03-30 at -0.088 log points (-8.4%), which coincides with Spain's suspension of all non-essential economic activity (30 March to 9 April 2020), a measure Portugal did not adopt. Outside those weeks the two countries' declines were of similar size, which is why the window-average DiD is small relative to the raw drops.

## Sanity check against published figures

Raw year-over-year change in mean load, 2020-03-14 to 2020-04-30, versus the same window in 2019 (not weather-adjusted):

| Country | Change |
|---|---|
| Spain | -13.81% |
| Portugal | -9.36% |

Published estimates put the Spanish demand drop over mid-March to April 2020 at roughly 11% to 13.5% (see README). Spain's raw drop here is close to that range. The DiD estimate is smaller in magnitude than the raw drop because Portugal's load also fell; the DiD isolates only the part of Spain's decline that exceeds Portugal's, and -4.45% is the simple difference of the two raw changes.

## Limitations

- Portugal declared its own state of emergency on 18 March 2020, so the control unit was also treated. The estimate is the differential effect of Spain's earlier and stricter lockdown, not the total effect of lockdown on Spanish demand.
- Weather is not controlled for. Spring 2020 temperatures could differ between the two countries; the shared climate limits but does not remove this risk.
- Two clusters at the country level are too few for country-clustered inference, so clustering is by country x week. Confidence intervals should be read as approximate.
