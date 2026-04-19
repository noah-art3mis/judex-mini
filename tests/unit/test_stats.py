"""Unit tests for analysis._stats.

Covers Wilson CI (existing) and beta-binomial empirical Bayes shrinkage.
The EB path is the primary estimator for per-lawyer / per-minister grant
rates at STF-HC: 5–10 % base rate plus a long tail of 1–3-case lawyers
breaks Wilson CIs' calibration. Partial pooling fixes it.
"""

from __future__ import annotations

import pytest

from judex.analysis.stats import (
    beta_binomial_posterior,
    fit_beta_prior_mom,
    wilson_ci,
)


def test_wilson_ci_zero_n_returns_zeros():
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_ci_brackets_point_estimate():
    lo, hi = wilson_ci(5, 20)
    assert lo < 0.25 < hi


def test_posterior_with_no_data_returns_prior_mean():
    # n=0 → posterior is the prior. Prior mean α/(α+β) = 0.7/10 = 0.07.
    r = beta_binomial_posterior(0, 0, alpha_prior=0.7, beta_prior=9.3)
    assert r["shrunk_rate"] == pytest.approx(0.07)


def test_posterior_shrinks_small_n_toward_prior():
    # 1 win in 2 tries with prior Beta(0.7, 9.3): raw=0.5, posterior mean
    # (0.7+1) / (0.7+1 + 9.3+1) = 1.7/12 ≈ 0.1417. Strict shrinkage between
    # prior 0.07 and raw 0.5.
    r = beta_binomial_posterior(1, 2, alpha_prior=0.7, beta_prior=9.3)
    assert r["shrunk_rate"] == pytest.approx(1.7 / 12)
    assert 0.07 < r["shrunk_rate"] < 0.5


def test_posterior_large_n_converges_to_raw_rate():
    # n=1000 swamps a prior of pseudocount 10.
    r = beta_binomial_posterior(100, 1000, alpha_prior=0.7, beta_prior=9.3)
    assert r["shrunk_rate"] == pytest.approx(0.10, abs=0.005)


def test_posterior_credible_interval_brackets_mean():
    r = beta_binomial_posterior(5, 50, alpha_prior=0.7, beta_prior=9.3)
    assert r["ci_lo"] < r["shrunk_rate"] < r["ci_hi"]


def test_posterior_credible_interval_tightens_with_n():
    r_small = beta_binomial_posterior(2, 20, alpha_prior=0.7, beta_prior=9.3)
    r_big = beta_binomial_posterior(20, 200, alpha_prior=0.7, beta_prior=9.3)
    small_width = r_small["ci_hi"] - r_small["ci_lo"]
    big_width = r_big["ci_hi"] - r_big["ci_lo"]
    assert big_width < small_width


def test_fit_beta_prior_recovers_synthetic_mean():
    # Synthetic: 400 lawyers, true rates drawn from Beta(2, 18) (mean 0.1),
    # each with n=30 binomial observations. MoM adjusted for binomial
    # sampling noise should recover the mean close to 0.1.
    from scipy.stats import beta as _beta, binom

    rates = _beta.rvs(2.0, 18.0, size=400, random_state=0)
    observations = [
        (int(binom.rvs(30, p, random_state=i)), 30)
        for i, p in enumerate(rates)
    ]
    alpha, beta = fit_beta_prior_mom(observations)
    fitted_mean = alpha / (alpha + beta)
    assert fitted_mean == pytest.approx(0.10, abs=0.02)


def test_fit_beta_prior_rejects_empty_observations():
    with pytest.raises(ValueError):
        fit_beta_prior_mom([])


def test_fit_beta_prior_skips_zero_n_rows():
    # Zero-n observations carry no rate signal. They must be ignored
    # rather than raising a ZeroDivisionError.
    obs = [(0, 0), (0, 0), (1, 10), (2, 10), (0, 10), (1, 10)]
    alpha, beta = fit_beta_prior_mom(obs)
    assert alpha > 0
    assert beta > 0
