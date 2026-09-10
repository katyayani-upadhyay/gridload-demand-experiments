"""Generate the simulated peak-time-rebate experiment.

Nothing here is observed data. Households, their consumption and the treatment
effect are all drawn from a seeded generator so the analysis can be reproduced
and its estimators checked against the known truth.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

ARM_CONTROL = "control"
ARM_TREATMENT = "treatment"


@dataclass(frozen=True)
class SimulationConfig:
    n_households: int = 4000
    treatment_share: float = 0.5
    pre_days: int = 28
    post_days: int = 28
    peak_hours: tuple[int, ...] = (18, 19, 20, 21)
    median_daily_kwh: float = 9.0
    household_log_sd: float = 0.45
    peak_share: float = 0.32
    daily_noise_cv: float = 0.35
    true_peak_reduction_pct: float = 0.06
    effect_heterogeneity_sd: float = 0.03
    rebound_share: float = 0.40
    control_opt_out_rate: float = 0.010
    treatment_opt_out_rate: float = 0.030
    seed: int = 2024

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def simulate_households(config: SimulationConfig) -> pd.DataFrame:
    """One row per household with pre and post period means of each metric."""
    rng = np.random.default_rng(config.seed)
    n = config.n_households

    treated = rng.random(n) < config.treatment_share
    baseline_daily = config.median_daily_kwh * np.exp(rng.normal(0, config.household_log_sd, n))
    peak_mu = baseline_daily * config.peak_share
    offpeak_mu = baseline_daily - peak_mu

    effect_pct = rng.normal(config.true_peak_reduction_pct, config.effect_heterogeneity_sd, n)
    peak_reduction = np.where(treated, effect_pct * peak_mu, 0.0)
    offpeak_rebound = config.rebound_share * peak_reduction

    def period_mean(mu: np.ndarray, days: int) -> np.ndarray:
        sd = (mu * config.daily_noise_cv)[:, None]
        draws = rng.normal(mu[:, None], sd, size=(n, days))
        return np.clip(draws, 0.0, None).mean(axis=1)

    peak_pre = period_mean(peak_mu, config.pre_days)
    offpeak_pre = period_mean(offpeak_mu, config.pre_days)
    peak_post = period_mean(peak_mu - peak_reduction, config.post_days)
    offpeak_post = period_mean(offpeak_mu + offpeak_rebound, config.post_days)

    opt_out_rate = np.where(treated, config.treatment_opt_out_rate, config.control_opt_out_rate)
    opted_out = rng.random(n) < opt_out_rate

    return pd.DataFrame(
        {
            "household_id": np.arange(n),
            "arm": np.where(treated, ARM_TREATMENT, ARM_CONTROL),
            "peak_kwh_pre": peak_pre,
            "peak_kwh_post": peak_post,
            "offpeak_kwh_pre": offpeak_pre,
            "offpeak_kwh_post": offpeak_post,
            "total_kwh_pre": peak_pre + offpeak_pre,
            "total_kwh_post": peak_post + offpeak_post,
            "opted_out": opted_out,
        }
    )
