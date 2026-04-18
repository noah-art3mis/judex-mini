"""Tests for src.sweeps.shared.CliffDetector.

The detector classifies the sweep's operating regime from a rolling
window of per-process (status, wall_s) observations. See
docs/rate-limits.md § Wall taxonomy and severity timeline for the
regime definitions.
"""

from __future__ import annotations

from src.sweeps.shared import CliffDetector


def _feed(det: CliffDetector, statuses: list[str], wall_s: float = 1.0) -> None:
    for s in statuses:
        det.observe(s, wall_s)


def test_regime_warming_below_min_observations():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 5)
    assert det.regime() == "warming"


def test_regime_warming_exactly_at_min_minus_one():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * (CliffDetector.MIN_OBS - 1))
    assert det.regime() == "warming"


def test_regime_under_utilising_all_ok_fast():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 30, wall_s=1.0)
    assert det.regime() == "under_utilising"


def test_regime_healthy_small_fail_tail():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 28 + ["fail"] * 2, wall_s=1.0)  # 2/30 ≈ 6.7%
    assert det.regime() == "healthy"


def test_regime_l2_engaged_from_fail_rate():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 45 + ["fail"] * 5, wall_s=1.0)  # 10% → just over threshold
    # 5/50 = 0.10, we want > 0.10 to go l2_engaged — use 6 fails
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 44 + ["fail"] * 6, wall_s=1.0)  # 12% → l2_engaged
    assert det.regime() == "l2_engaged"


def test_regime_l2_engaged_from_p95_latency_alone():
    det = CliffDetector(window=50)
    # all ok, but the worst 3 processes took 20s — p95 > 15 triggers
    _feed(det, ["ok"] * 47, wall_s=1.0)
    for _ in range(3):
        det.observe("ok", 20.0)
    assert det.regime() == "l2_engaged"


def test_regime_approaching_collapse_from_fail_rate():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 38 + ["fail"] * 12, wall_s=1.0)  # 24%
    assert det.regime() == "approaching_collapse"


def test_regime_approaching_collapse_from_p95():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 45, wall_s=1.0)
    for _ in range(5):  # p95 at 40s
        det.observe("ok", 40.0)
    assert det.regime() == "approaching_collapse"


def test_regime_collapse_from_fail_rate():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 30 + ["fail"] * 20, wall_s=1.0)  # 40%
    assert det.regime() == "collapse"


def test_regime_collapse_from_p95_adaptive_block_signature():
    det = CliffDetector(window=50)
    # V's cycle 8: 403×32 over 185s. p95 > 60 is the signature.
    _feed(det, ["ok"] * 45, wall_s=1.0)
    for _ in range(5):
        det.observe("ok", 180.0)
    assert det.regime() == "collapse"


def test_regime_either_axis_can_trip_collapse():
    # Verify fail_rate alone suffices even at low latency.
    det = CliffDetector(window=50)
    _feed(det, ["fail"] * 20 + ["ok"] * 10, wall_s=0.5)  # 66% fails, fast
    assert det.regime() == "collapse"


def test_window_slides_old_observations_drop():
    det = CliffDetector(window=20)
    # First fill with bad data, then flush with good data
    _feed(det, ["fail"] * 20, wall_s=1.0)
    assert det.regime() == "collapse"
    _feed(det, ["ok"] * 20, wall_s=1.0)
    assert det.regime() == "under_utilising"


def test_error_status_counts_as_fail():
    # "error" and "fail" both count as non-ok for the detector
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 30 + ["error"] * 20, wall_s=1.0)
    assert det.regime() == "collapse"


def test_default_window_is_fifty():
    det = CliffDetector()
    _feed(det, ["ok"] * 60, wall_s=1.0)
    # If window weren't 50, we'd have more than 50 entries now and
    # the p95 calculation would be over a different N. Assert len directly.
    assert len(det._statuses) == 50
