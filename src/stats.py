"""Small statistical helpers used by the HC deep-dive analysis.

Two families:
- `wilson_ci` / `grant_rate_table` — Wilson score intervals, legible to
  lay readers, used for the headline per-actor bar charts.
- `fit_beta_prior_mom` / `beta_binomial_posterior` — empirical Bayes
  shrinkage on the pooled grant rate, used for the "adjusted for
  small-sample bias" panel. Recommended by
  `docs/hc-who-wins-lit-review.md` § 3.

Tests: `tests/unit/test_stats.py`.
"""

from __future__ import annotations

import math
from typing import Iterable

from scipy.stats import beta as _beta_dist

Z_95 = 1.959963984540054  # two-sided normal quantile at 95 %


def wilson_ci(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score confidence interval for a Bernoulli rate.

    Returns (low, high). Safe when n == 0 (returns (0.0, 0.0)).
    """
    if n <= 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, center - half), min(1.0, center + half)


def grant_rate_table(outcomes: Iterable[str | None], *, win_labels: set[str]):
    """Aggregate an iterable of outcomes into (n, wins, rate, ci_lo, ci_hi).

    `win_labels` defines which outcome strings count as a win (for HC:
    {"concedido", "concedido_parcial"}).
    """
    outs = list(outcomes)
    n = len(outs)
    wins = sum(1 for o in outs if o in win_labels)
    rate = wins / n if n else 0.0
    lo, hi = wilson_ci(wins, n)
    return {"n": n, "wins": wins, "rate": rate, "ci_lo": lo, "ci_hi": hi}


def beta_binomial_posterior(
    wins: int,
    n: int,
    *,
    alpha_prior: float,
    beta_prior: float,
    conf: float = 0.95,
) -> dict[str, float]:
    """Posterior Beta(α+wins, β+n-wins) summary: shrunk mean + equal-tailed CI.

    Inputs are the per-actor counts; the prior is the pooled Beta fit by
    `fit_beta_prior_mom`. n=0 returns the prior mean and prior CI.
    """
    alpha_post = alpha_prior + wins
    beta_post = beta_prior + (n - wins)
    mean = alpha_post / (alpha_post + beta_post)
    lo, hi = _beta_dist.interval(conf, alpha_post, beta_post)
    return {"shrunk_rate": float(mean), "ci_lo": float(lo), "ci_hi": float(hi)}


def fit_beta_prior_mom(
    observations: Iterable[tuple[int, int]],
) -> tuple[float, float]:
    """Method-of-moments Beta(α, β) fit to (wins, n) pairs.

    Adjusts for binomial within-observation variance per Robinson
    (2017), "Introduction to Empirical Bayes", ch. 3 — raw rate variance
    contains binomial noise that, if not subtracted, under-disperses the
    fitted prior and over-shrinks small-n actors.

    Observations with n=0 are dropped. Raises ValueError when every
    observation is empty.
    """
    data = [(w, n) for w, n in observations if n > 0]
    if not data:
        raise ValueError("fit_beta_prior_mom: no observations with n > 0")
    rates = [w / n for w, n in data]
    ns = [n for _, n in data]
    k = len(data)
    mean = sum(rates) / k
    raw_var = sum((r - mean) ** 2 for r in rates) / k
    binom_var = sum(mean * (1 - mean) / n for n in ns) / k
    # adjusted variance can go non-positive when the pool is homogeneous;
    # floor it so the MoM solve stays well-defined.
    adj_var = max(raw_var - binom_var, 1e-6)
    concentration = mean * (1 - mean) / adj_var - 1
    if concentration <= 0:
        concentration = 1.0
    alpha = mean * concentration
    beta = (1 - mean) * concentration
    return alpha, beta
