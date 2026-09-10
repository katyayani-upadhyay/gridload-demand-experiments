"""Statistics for a two-arm randomized experiment analysed at the household level."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.power import TTestIndPower
from statsmodels.stats.proportion import proportions_ztest


@dataclass(frozen=True)
class EffectEstimate:
    metric: str
    control_mean: float
    treatment_mean: float
    difference: float
    relative_lift: float
    ci_low: float
    ci_high: float
    p_value: float
    n_control: int
    n_treatment: int

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class PowerAnalysis:
    alpha: float
    power: float
    n_per_arm: int
    pooled_sd: float
    mde_absolute: float
    mde_relative: float
    power_at_planned_effect: float
    planned_effect_relative: float

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class SrmCheck:
    n_control: int
    n_treatment: int
    expected_treatment_share: float
    chi2: float
    p_value: float
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def minimum_detectable_effect(
    sd: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Smallest absolute difference in means detectable with a two-sided test."""
    effect_size = TTestIndPower().solve_power(
        effect_size=None, nobs1=n_per_arm, alpha=alpha, power=power, ratio=1.0
    )
    return float(effect_size * sd)


def power_for_effect(
    effect: float, sd: float, n_per_arm: int, alpha: float = 0.05
) -> float:
    return float(
        TTestIndPower().power(effect_size=effect / sd, nobs1=n_per_arm, alpha=alpha, ratio=1.0)
    )


def power_analysis(
    control_values: np.ndarray,
    n_per_arm: int,
    planned_effect_relative: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> PowerAnalysis:
    sd = float(np.std(control_values, ddof=1))
    mean = float(np.mean(control_values))
    mde = minimum_detectable_effect(sd, n_per_arm, alpha, power)
    planned = planned_effect_relative * mean
    return PowerAnalysis(
        alpha=alpha,
        power=power,
        n_per_arm=n_per_arm,
        pooled_sd=sd,
        mde_absolute=mde,
        mde_relative=mde / mean,
        power_at_planned_effect=power_for_effect(planned, sd, n_per_arm, alpha),
        planned_effect_relative=planned_effect_relative,
    )


def sample_ratio_mismatch(
    n_control: int, n_treatment: int, expected_treatment_share: float, alpha: float = 0.001
) -> SrmCheck:
    """Chi-square goodness of fit of observed arm sizes against the design split.

    A strict alpha is deliberate: an SRM means the randomisation is broken and
    no downstream estimate can be trusted, so only strong evidence should stop
    the analysis."""
    total = n_control + n_treatment
    expected = np.array(
        [total * (1 - expected_treatment_share), total * expected_treatment_share]
    )
    chi2, p_value = stats.chisquare([n_control, n_treatment], expected)
    return SrmCheck(
        n_control=n_control,
        n_treatment=n_treatment,
        expected_treatment_share=expected_treatment_share,
        chi2=float(chi2),
        p_value=float(p_value),
        passed=bool(p_value >= alpha),
    )


def welch_difference(
    control: np.ndarray, treatment: np.ndarray, metric: str, alpha: float = 0.05
) -> EffectEstimate:
    """Treatment minus control mean with a Welch t-test and confidence interval."""
    control = np.asarray(control, dtype=float)
    treatment = np.asarray(treatment, dtype=float)
    result = stats.ttest_ind(treatment, control, equal_var=False)
    ci = result.confidence_interval(confidence_level=1 - alpha)
    control_mean = float(control.mean())
    treatment_mean = float(treatment.mean())
    return EffectEstimate(
        metric=metric,
        control_mean=control_mean,
        treatment_mean=treatment_mean,
        difference=treatment_mean - control_mean,
        relative_lift=(treatment_mean - control_mean) / control_mean,
        ci_low=float(ci.low),
        ci_high=float(ci.high),
        p_value=float(result.pvalue),
        n_control=int(len(control)),
        n_treatment=int(len(treatment)),
    )


def cuped_adjust(outcome: pd.Series, covariate: pd.Series) -> tuple[pd.Series, float]:
    """Return the CUPED-adjusted outcome and the variance reduction achieved.

    theta is estimated on the pooled sample, which is valid because the
    covariate is pre-treatment and therefore independent of assignment."""
    theta = np.cov(outcome, covariate, ddof=1)[0, 1] / covariate.var(ddof=1)
    adjusted = outcome - theta * (covariate - covariate.mean())
    variance_reduction = 1.0 - adjusted.var(ddof=1) / outcome.var(ddof=1)
    return adjusted.rename(f"{outcome.name}_cuped"), float(variance_reduction)


def proportion_difference(
    control_events: int,
    n_control: int,
    treatment_events: int,
    n_treatment: int,
    metric: str,
    alpha: float = 0.05,
) -> EffectEstimate:
    """Two-proportion z-test with a Wald confidence interval for the difference."""
    p_c = control_events / n_control
    p_t = treatment_events / n_treatment
    _, p_value = proportions_ztest([treatment_events, control_events], [n_treatment, n_control])
    se = np.sqrt(p_c * (1 - p_c) / n_control + p_t * (1 - p_t) / n_treatment)
    z = stats.norm.ppf(1 - alpha / 2)
    return EffectEstimate(
        metric=metric,
        control_mean=p_c,
        treatment_mean=p_t,
        difference=p_t - p_c,
        relative_lift=(p_t - p_c) / p_c if p_c else float("nan"),
        ci_low=float(p_t - p_c - z * se),
        ci_high=float(p_t - p_c + z * se),
        p_value=float(p_value),
        n_control=n_control,
        n_treatment=n_treatment,
    )
