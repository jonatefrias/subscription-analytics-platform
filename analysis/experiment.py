"""Statistics for reading a two-arm experiment.

Everything the readout notebook reports is computed here, so it can be unit tested
(tests/test_experiment_stats.py) instead of living only inside notebook cells.

Conventions: `control` and `treatment` are 1-D arrays with one value per randomised unit;
effects are treatment minus control; intervals are two-sided at level 1 - alpha.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class Effect:
    """Difference in means between two arms with its uncertainty."""

    control_mean: float
    treatment_mean: float
    diff: float
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    rel_diff: float
    rel_ci_low: float
    rel_ci_high: float
    n_control: int
    n_treatment: int

    @property
    def significant(self) -> bool:
        return not (self.ci_low <= 0.0 <= self.ci_high)


def srm_test(n_control: int, n_treatment: int, expected_treatment_share: float = 0.5) -> float:
    """Sample ratio mismatch: p-value of a chi-square test of the observed split against the design.

    A very small p-value (the usual alarm is < 0.001) means the arms did not receive the traffic
    the design intended, and no effect estimate should be trusted until that is explained.
    """
    total = n_control + n_treatment
    expected = [total * (1 - expected_treatment_share), total * expected_treatment_share]
    return float(stats.chisquare([n_control, n_treatment], f_exp=expected).pvalue)


def difference_in_means(control, treatment, alpha: float = 0.05) -> Effect:
    """Welch difference in means with a normal-approximation interval.

    Works for conversion rates (0/1 values) and for revenue per user. The relative lift uses the
    delta method, because the control mean in the denominator is itself an estimate.
    """
    control = np.asarray(control, dtype=float)
    treatment = np.asarray(treatment, dtype=float)
    n_c, n_t = len(control), len(treatment)
    mean_c, mean_t = control.mean(), treatment.mean()
    var_c, var_t = control.var(ddof=1) / n_c, treatment.var(ddof=1) / n_t

    diff = mean_t - mean_c
    se = float(np.sqrt(var_c + var_t))
    z = stats.norm.ppf(1 - alpha / 2)
    p_value = float(2 * stats.norm.sf(abs(diff) / se)) if se > 0 else 1.0

    rel = diff / mean_c
    rel_se = float(np.sqrt(var_t / mean_c**2 + var_c * mean_t**2 / mean_c**4))
    return Effect(
        control_mean=float(mean_c),
        treatment_mean=float(mean_t),
        diff=float(diff),
        se=se,
        ci_low=float(diff - z * se),
        ci_high=float(diff + z * se),
        p_value=p_value,
        rel_diff=float(rel),
        rel_ci_low=float(rel - z * rel_se),
        rel_ci_high=float(rel + z * rel_se),
        n_control=n_c,
        n_treatment=n_t,
    )


def bootstrap_diff_ci(control, treatment, n_boot: int = 5000, alpha: float = 0.05, seed: int = 0):
    """Percentile bootstrap interval for the difference in means.

    Used as a check on the normal approximation for skewed metrics such as revenue.
    """
    rng = np.random.default_rng(seed)
    control = np.asarray(control, dtype=float)
    treatment = np.asarray(treatment, dtype=float)
    boot_c = control[rng.integers(0, len(control), size=(n_boot, len(control)))].mean(axis=1)
    boot_t = treatment[rng.integers(0, len(treatment), size=(n_boot, len(treatment)))].mean(axis=1)
    low, high = np.quantile(boot_t - boot_c, [alpha / 2, 1 - alpha / 2])
    return float(low), float(high)


def minimum_detectable_effect(sd: float, n_per_arm: float, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest true absolute difference a two-sided test detects with the given power."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * sd * np.sqrt(2 / n_per_arm))


def required_sample_size(sd: float, effect: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Units per arm needed to detect an absolute difference `effect`."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return int(np.ceil(2 * (z * sd / effect) ** 2))


def achieved_power(sd: float, n_per_arm: float, effect: float, alpha: float = 0.05) -> float:
    """Probability that a two-sided test rejects when the true absolute difference is `effect`."""
    se = sd * np.sqrt(2 / n_per_arm)
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    shift = abs(effect) / se
    return float(stats.norm.sf(z_alpha - shift) + stats.norm.cdf(-z_alpha - shift))


def cuped_adjust(y, covariate):
    """CUPED: remove from `y` the part explained by a pre-assignment covariate.

    Returns the adjusted metric, theta and the share of variance removed (the squared correlation).
    Theta is estimated on both arms pooled, and the covariate must not be affected by the
    treatment; under those two conditions the adjusted difference in means stays unbiased.
    """
    y = np.asarray(y, dtype=float)
    covariate = np.asarray(covariate, dtype=float)
    var_x = covariate.var(ddof=1)
    if var_x == 0:
        return y.copy(), 0.0, 0.0
    theta = float(np.cov(y, covariate, ddof=1)[0, 1] / var_x)
    adjusted = y - theta * (covariate - covariate.mean())
    variance_reduction = float(np.corrcoef(y, covariate)[0, 1] ** 2)
    return adjusted, theta, variance_reduction
