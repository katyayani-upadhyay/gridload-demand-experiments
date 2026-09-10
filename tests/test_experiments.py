from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gridload.experiments.analyze import analyse
from gridload.experiments.simulate import (
    ARM_CONTROL,
    ARM_TREATMENT,
    SimulationConfig,
    simulate_households,
)
from gridload.experiments.stats import (
    cuped_adjust,
    minimum_detectable_effect,
    power_for_effect,
    proportion_difference,
    sample_ratio_mismatch,
    welch_difference,
)


def test_power_matches_cohen_reference_value() -> None:
    """Cohen's tables: d = 0.2 needs 394 per group for 80 percent power at alpha 0.05."""
    assert power_for_effect(effect=0.2, sd=1.0, n_per_arm=394) == pytest.approx(0.80, abs=0.005)
    assert minimum_detectable_effect(sd=1.0, n_per_arm=394) == pytest.approx(0.2, abs=0.002)


def test_mde_shrinks_with_sample_size() -> None:
    assert minimum_detectable_effect(1.0, 400) > minimum_detectable_effect(1.0, 1600)
    ratio = minimum_detectable_effect(1.0, 400) / minimum_detectable_effect(1.0, 1600)
    assert ratio == pytest.approx(2.0, rel=0.02)


def test_srm_passes_on_balanced_split_and_fails_on_skewed() -> None:
    assert sample_ratio_mismatch(5000, 5050, 0.5).passed
    skewed = sample_ratio_mismatch(5000, 5600, 0.5)
    assert not skewed.passed
    assert skewed.p_value < 0.001


def test_srm_respects_unequal_design_split() -> None:
    assert sample_ratio_mismatch(7000, 3000, 0.3).passed
    assert not sample_ratio_mismatch(5000, 5000, 0.3).passed


def test_cuped_reduces_variance_when_covariate_is_predictive() -> None:
    rng = np.random.default_rng(1)
    covariate = pd.Series(rng.normal(10, 2, 5000), name="pre")
    outcome = pd.Series(0.8 * covariate + rng.normal(0, 1, 5000), name="post")
    adjusted, reduction = cuped_adjust(outcome, covariate)
    assert reduction > 0.5
    assert adjusted.var() < outcome.var()
    assert adjusted.mean() == pytest.approx(outcome.mean())


def test_cuped_leaves_treatment_effect_unbiased() -> None:
    config = SimulationConfig(n_households=20000, seed=7)
    households = simulate_households(config)
    control = households["arm"] == ARM_CONTROL
    adjusted, _ = cuped_adjust(households["peak_kwh_post"], households["peak_kwh_pre"])
    raw = welch_difference(
        households.loc[control, "peak_kwh_post"], households.loc[~control, "peak_kwh_post"], "raw"
    )
    cuped = welch_difference(adjusted[control], adjusted[~control], "cuped")
    assert cuped.difference == pytest.approx(raw.difference, abs=0.02)
    assert (cuped.ci_high - cuped.ci_low) < (raw.ci_high - raw.ci_low)


def test_welch_difference_recovers_known_shift() -> None:
    rng = np.random.default_rng(3)
    control = rng.normal(0, 1, 20000)
    treatment = rng.normal(0.5, 1, 20000)
    est = welch_difference(control, treatment, "x")
    assert est.difference == pytest.approx(0.5, abs=0.05)
    assert est.ci_low < 0.5 < est.ci_high
    assert est.p_value < 1e-6


def test_proportion_difference_detects_higher_opt_out() -> None:
    est = proportion_difference(20, 2000, 60, 2000, "opt_out")
    assert est.difference == pytest.approx(0.02)
    assert est.p_value < 0.01
    assert est.ci_low > 0


def test_simulation_is_reproducible_and_effect_is_recovered() -> None:
    config = SimulationConfig(n_households=6000, seed=11)
    first = simulate_households(config)
    second = simulate_households(config)
    pd.testing.assert_frame_equal(first, second)

    results = analyse(first, config)
    truth = (
        -config.true_peak_reduction_pct
        * first.loc[first["arm"] == ARM_CONTROL, "peak_kwh_post"].mean()
    )
    assert results.primary_cuped.ci_low < truth < results.primary_cuped.ci_high
    assert results.srm.passed
    assert first["arm"].isin([ARM_CONTROL, ARM_TREATMENT]).all()


def test_null_effect_does_not_ship() -> None:
    config = SimulationConfig(
        n_households=6000, true_peak_reduction_pct=0.0, effect_heterogeneity_sd=0.0, seed=5
    )
    results = analyse(simulate_households(config), config)
    assert not results.ship
