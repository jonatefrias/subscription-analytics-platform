"""Known-answer and simulation tests for the experiment statistics used in the readout notebook."""

import numpy as np
import pytest

from analysis.experiment import (
    achieved_power,
    bootstrap_diff_ci,
    cuped_adjust,
    difference_in_means,
    minimum_detectable_effect,
    required_sample_size,
    srm_test,
)


def test_srm_accepts_a_balanced_split_and_flags_a_broken_one():
    assert srm_test(5000, 5000) == pytest.approx(1.0)
    assert srm_test(5000, 5100) > 0.001
    assert srm_test(5000, 5600) < 0.001


def test_difference_in_means_matches_the_textbook_two_proportion_interval():
    control = np.r_[np.ones(200), np.zeros(800)]  # 20%
    treatment = np.r_[np.ones(260), np.zeros(740)]  # 26%
    effect = difference_in_means(control, treatment)

    se = np.sqrt(0.2 * 0.8 / 999 + 0.26 * 0.74 / 999)  # sample variance uses n - 1
    assert effect.diff == pytest.approx(0.06)
    assert effect.se == pytest.approx(se)
    assert effect.ci_low == pytest.approx(0.06 - 1.959964 * se, abs=1e-6)
    assert effect.rel_diff == pytest.approx(0.30)
    assert effect.rel_ci_low < effect.rel_diff < effect.rel_ci_high
    assert effect.significant


def test_interval_covers_the_true_effect_at_the_nominal_rate():
    rng = np.random.default_rng(1)
    covered = 0
    for _ in range(400):
        control = rng.exponential(10.0, 500)
        treatment = rng.exponential(10.0, 500) + 1.0
        effect = difference_in_means(control, treatment)
        covered += effect.ci_low <= 1.0 <= effect.ci_high
    assert 0.92 <= covered / 400 <= 0.98


def test_bootstrap_agrees_with_the_normal_approximation_on_large_samples():
    rng = np.random.default_rng(2)
    control, treatment = rng.exponential(10.0, 4000), rng.exponential(11.0, 4000)
    effect = difference_in_means(control, treatment)
    low, high = bootstrap_diff_ci(control, treatment, n_boot=2000)
    assert low == pytest.approx(effect.ci_low, abs=0.1)
    assert high == pytest.approx(effect.ci_high, abs=0.1)


def test_power_functions_are_consistent_with_each_other():
    sd, n = 0.4, 1700
    mde = minimum_detectable_effect(sd, n)
    assert achieved_power(sd, n, mde) == pytest.approx(0.8, abs=1e-3)
    assert required_sample_size(sd, mde) == pytest.approx(n, abs=1)
    assert achieved_power(sd, n, 0.0) == pytest.approx(0.05, abs=1e-6)
    # the classic rule of thumb: n per arm = 16 * sd^2 / effect^2
    assert required_sample_size(1.0, 0.1) == pytest.approx(1600, rel=0.02)


def test_cuped_keeps_the_effect_and_removes_the_explained_variance():
    rng = np.random.default_rng(3)
    n = 20_000
    covariate = rng.normal(50, 10, n)
    treated = rng.random(n) < 0.5
    y = 0.8 * covariate + rng.normal(0, 6, n) + 2.0 * treated

    adjusted, theta, reduction = cuped_adjust(y, covariate)
    raw = difference_in_means(y[~treated], y[treated])
    cuped = difference_in_means(adjusted[~treated], adjusted[treated])

    assert theta == pytest.approx(0.8, abs=0.05)
    assert reduction == pytest.approx(64 / (64 + 36), abs=0.02)
    assert cuped.diff == pytest.approx(2.0, abs=0.3)
    assert cuped.se == pytest.approx(raw.se * np.sqrt(1 - reduction), rel=0.03)


def test_cuped_with_a_constant_covariate_changes_nothing():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    adjusted, theta, reduction = cuped_adjust(y, np.ones(4))
    assert np.array_equal(adjusted, y)
    assert (theta, reduction) == (0.0, 0.0)
