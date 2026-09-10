"""Analyse the simulated experiment and write the ship/no-ship decision."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from gridload.config import Settings, get_settings
from gridload.experiments.simulate import (
    ARM_CONTROL,
    ARM_TREATMENT,
    SimulationConfig,
    simulate_households,
)
from gridload.experiments.stats import (
    EffectEstimate,
    PowerAnalysis,
    SrmCheck,
    cuped_adjust,
    power_analysis,
    proportion_difference,
    sample_ratio_mismatch,
    welch_difference,
)

log = logging.getLogger(__name__)

ALPHA = 0.05
PLANNED_EFFECT_RELATIVE = 0.05
MAX_REBOUND_SHARE = 0.5
MAX_OPT_OUT_INCREASE = 0.03


@dataclass(frozen=True)
class GuardrailResult:
    name: str
    estimate: EffectEstimate
    rule: str
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "rule": self.rule,
            "passed": self.passed,
            **self.estimate.to_dict(),
        }


@dataclass(frozen=True)
class ExperimentResults:
    config: SimulationConfig
    srm: SrmCheck
    power: PowerAnalysis
    primary_unadjusted: EffectEstimate
    primary_cuped: EffectEstimate
    cuped_variance_reduction: float
    guardrails: list[GuardrailResult]
    ship: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "simulated": True,
            "config": self.config.to_dict(),
            "srm": self.srm.to_dict(),
            "power": self.power.to_dict(),
            "primary_unadjusted": self.primary_unadjusted.to_dict(),
            "primary_cuped": self.primary_cuped.to_dict(),
            "cuped_variance_reduction": self.cuped_variance_reduction,
            "guardrails": [g.to_dict() for g in self.guardrails],
            "ship": self.ship,
        }


def peak_hours_from_load(
    duckdb_path: Path, country_code: str = "ES", window_hours: int = 4, earliest_start: int = 17
) -> tuple[int, ...]:
    """The contiguous evening block of local hours with the highest mean system load.

    Spain has a midday peak driven by commercial and industrial demand and an
    evening peak driven by households. A residential rebate targets the latter,
    so only windows starting at or after `earliest_start` are considered."""
    query = """
        select local_hour, avg(load_mw) as mean_load
        from marts.fct_load_hourly
        where country_code = ? and local_date between '2019-01-01' and '2019-12-31'
        group by local_hour order by local_hour
    """
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        mean_by_hour = dict(con.execute(query, [country_code]).fetchall())
    candidates = range(earliest_start, 24 - window_hours + 1)
    best_start = max(
        candidates, key=lambda h: sum(mean_by_hour[k] for k in range(h, h + window_hours))
    )
    return tuple(range(best_start, best_start + window_hours))


def analyse(households: pd.DataFrame, config: SimulationConfig) -> ExperimentResults:
    control = households[households["arm"] == ARM_CONTROL]
    treatment = households[households["arm"] == ARM_TREATMENT]

    srm = sample_ratio_mismatch(len(control), len(treatment), config.treatment_share)
    power = power_analysis(
        control["peak_kwh_post"].to_numpy(),
        n_per_arm=min(len(control), len(treatment)),
        planned_effect_relative=PLANNED_EFFECT_RELATIVE,
        alpha=ALPHA,
    )

    primary = welch_difference(
        control["peak_kwh_post"], treatment["peak_kwh_post"], "peak_kwh_per_day", ALPHA
    )
    adjusted, variance_reduction = cuped_adjust(
        households["peak_kwh_post"], households["peak_kwh_pre"]
    )
    primary_cuped = welch_difference(
        adjusted[control.index], adjusted[treatment.index], "peak_kwh_per_day_cuped", ALPHA
    )

    total_adj, _ = cuped_adjust(households["total_kwh_post"], households["total_kwh_pre"])
    total = welch_difference(
        total_adj[control.index], total_adj[treatment.index], "total_kwh_per_day", ALPHA
    )
    offpeak_adj, _ = cuped_adjust(households["offpeak_kwh_post"], households["offpeak_kwh_pre"])
    offpeak = welch_difference(
        offpeak_adj[control.index], offpeak_adj[treatment.index], "offpeak_kwh_per_day", ALPHA
    )
    opt_out = proportion_difference(
        int(control["opted_out"].sum()),
        len(control),
        int(treatment["opted_out"].sum()),
        len(treatment),
        "opt_out_rate",
        ALPHA,
    )

    peak_reduction = -primary_cuped.difference
    rebound_share = offpeak.difference / peak_reduction if peak_reduction > 0 else float("inf")
    guardrails = [
        GuardrailResult(
            "conservation",
            total,
            "total daily kWh must not increase (CI upper bound <= 0)",
            total.ci_high <= 0,
        ),
        GuardrailResult(
            "off_peak_rebound",
            offpeak,
            f"off-peak increase must be under {MAX_REBOUND_SHARE:.0%} of the peak reduction",
            rebound_share < MAX_REBOUND_SHARE,
        ),
        GuardrailResult(
            "opt_out",
            opt_out,
            f"opt-out rate increase must be under {MAX_OPT_OUT_INCREASE:.1%} (CI upper bound)",
            opt_out.ci_high < MAX_OPT_OUT_INCREASE,
        ),
    ]

    ship = srm.passed and primary_cuped.ci_high < 0 and all(g.passed for g in guardrails)
    return ExperimentResults(
        config, srm, power, primary, primary_cuped, variance_reduction, guardrails, ship
    )


def run_experiment(settings: Settings | None = None) -> ExperimentResults:
    settings = settings or get_settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    config = SimulationConfig(peak_hours=peak_hours_from_load(settings.duckdb_path))
    households = simulate_households(config)
    results = analyse(households, config)
    (settings.reports_dir / "ab_results.json").write_text(json.dumps(results.to_dict(), indent=2))
    (settings.reports_dir / "ab_decision.md").write_text(decision_document(results))
    log.info(
        "primary effect %.3f kWh (%.1f%%), CI [%.3f, %.3f], ship=%s",
        results.primary_cuped.difference,
        100 * results.primary_cuped.relative_lift,
        results.primary_cuped.ci_low,
        results.primary_cuped.ci_high,
        results.ship,
    )
    return results


def decision_document(r: ExperimentResults) -> str:
    def row(e: EffectEstimate, label: str) -> str:
        return (
            f"| {label} | {e.control_mean:.3f} | {e.treatment_mean:.3f} | {e.difference:+.3f} "
            f"({e.relative_lift:+.1%}) | [{e.ci_low:+.3f}, {e.ci_high:+.3f}] | {e.p_value:.2e} |"
        )

    p = r.power
    hours = ", ".join(f"{h:02d}:00" for h in r.config.peak_hours)
    verdict = "SHIP" if r.ship else "DO NOT SHIP"
    lines = [
        "# Peak-time rebate experiment: ship / no-ship decision",
        "",
        "**This experiment is simulated.** Households, consumption and the treatment "
        "effect are generated by `gridload/experiments/simulate.py` with a fixed seed. "
        "The numbers below test the analysis pipeline, not a real programme.",
        "",
        f"## Decision: {verdict}",
        "",
        "## Design",
        "",
        f"- {r.config.n_households} synthetic households randomised "
        f"{1 - r.config.treatment_share:.0%}/{r.config.treatment_share:.0%} "
        "to control / treatment.",
        f"- Treatment: peak-time rebate plus smart-meter nudge during {hours} local time "
        "(the highest-load four-hour evening block of the Spanish system in 2019).",
        f"- Pre-period {r.config.pre_days} days, experiment period {r.config.post_days} days.",
        "- Primary metric: mean daily peak-window kWh per household. Unit of analysis is "
        "the household, matching the unit of randomisation.",
        "- Guardrails: total daily kWh (conservation, not just shifting), off-peak rebound, "
        "opt-out rate.",
        "",
        "## Sample ratio mismatch",
        "",
        f"Control {r.srm.n_control}, treatment {r.srm.n_treatment}, chi-square {r.srm.chi2:.3f}, "
        f"p = {r.srm.p_value:.3f}. **{'Passed' if r.srm.passed else 'FAILED'}** (alpha 0.001).",
        "",
        "## Power",
        "",
        f"- Control SD of the primary metric: {p.pooled_sd:.3f} kWh/day.",
        f"- With {p.n_per_arm} households per arm, alpha {p.alpha}, power {p.power:.0%}: "
        f"minimum detectable effect {p.mde_absolute:.3f} kWh/day ({p.mde_relative:.1%}).",
        f"- Power to detect the planned {p.planned_effect_relative:.0%} reduction: "
        f"{p.power_at_planned_effect:.1%}.",
        "",
        "## Primary metric",
        "",
        "| Estimator | Control | Treatment | Difference | 95% CI | p-value |",
        "|---|---|---|---|---|---|",
        row(r.primary_unadjusted, "Difference in means"),
        row(r.primary_cuped, "CUPED (pre-period peak kWh)"),
        "",
        f"CUPED reduced the variance of the primary metric by "
        f"**{r.cuped_variance_reduction:.1%}**, shrinking the confidence interval from "
        f"{r.primary_unadjusted.ci_high - r.primary_unadjusted.ci_low:.3f} to "
        f"{r.primary_cuped.ci_high - r.primary_cuped.ci_low:.3f} kWh/day.",
        "",
        "## Guardrails",
        "",
        "| Guardrail | Control | Treatment | Difference | 95% CI | p-value | Rule | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for g in r.guardrails:
        e = g.estimate
        lines.append(
            f"| {g.name} | {e.control_mean:.4f} | {e.treatment_mean:.4f} | {e.difference:+.4f} "
            f"({e.relative_lift:+.1%}) | [{e.ci_low:+.4f}, {e.ci_high:+.4f}] | {e.p_value:.2e} "
            f"| {g.rule} | {'pass' if g.passed else 'FAIL'} |"
        )
    lines += [
        "",
        "## Reasoning",
        "",
        "Ship requires: no sample ratio mismatch, the CUPED confidence interval for the "
        "peak reduction entirely below zero, and every guardrail passing. "
        + (
            "All conditions hold. The reduction is real conservation rather than pure "
            "load shifting because total daily kWh also falls, off-peak rebound absorbs "
            "less than half of the peak reduction, and the opt-out increase stays inside "
            "the tolerated band."
            if r.ship
            else "At least one condition fails; see the tables above."
        ),
        "",
        f"Known truth in the simulator: {r.config.true_peak_reduction_pct:.0%} mean peak reduction "
        f"with {r.config.rebound_share:.0%} rebound. The estimate should sit inside its "
        "confidence interval; if it does not, the estimator, not the programme, is wrong.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_experiment()
