"""Tests for src.sweeps.shared.CliffDetector.

The detector classifies the sweep's operating regime from a rolling
window of per-process (status, wall_s) observations. See
docs/rate-limits.md § Wall taxonomy and severity timeline for the
regime definitions.
"""

from __future__ import annotations

from judex.sweeps.shared import CliffDetector


def _feed(det: CliffDetector, statuses: list[str], wall_s: float = 1.0) -> None:
    for s in statuses:
        det.observe(s, wall_s)


def test_regime_warming_below_min_observations():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 5)
    assert det.regime().label == "warming"


def test_regime_warming_exactly_at_min_minus_one():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * (CliffDetector.MIN_OBS - 1))
    assert det.regime().label == "warming"


def test_regime_under_utilising_all_ok_fast():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 30, wall_s=1.0)
    assert det.regime().label == "under_utilising"


def test_regime_healthy_small_fail_tail():
    # 2 WAF-shaped fails in 30 records → 6.7 % fail_rate → healthy band
    det = CliffDetector(window=50)
    for _ in range(28):
        det.observe("ok", 1.0)
    for _ in range(2):
        det.observe("fail", 1.0, http_status=403)
    assert det.regime().label == "healthy"


def test_regime_l2_engaged_from_fail_rate():
    # Fails must look WAF-shaped (slow OR http 403/429/5xx OR retries fired)
    # to count toward the fail-rate regime. Fast NoIncidente fails do not.
    det = CliffDetector(window=50)
    for _ in range(44):
        det.observe("ok", 1.0)
    for _ in range(6):  # 12% WAF-shaped fails
        det.observe("fail", 1.0, http_status=403)
    assert det.regime().label == "l2_engaged"


def test_regime_l2_engaged_from_p95_latency_alone():
    det = CliffDetector(window=50)
    # all ok, but the worst 3 processes took 20s — p95 > 15 triggers
    _feed(det, ["ok"] * 47, wall_s=1.0)
    for _ in range(3):
        det.observe("ok", 20.0)
    assert det.regime().label == "l2_engaged"


def test_regime_approaching_collapse_from_fail_rate():
    det = CliffDetector(window=50)
    for _ in range(38):
        det.observe("ok", 1.0)
    for _ in range(12):
        det.observe("fail", 1.0, http_status=403)  # 24% WAF-shaped
    assert det.regime().label == "approaching_collapse"


def test_regime_approaching_collapse_from_p95():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 45, wall_s=1.0)
    for _ in range(5):  # p95 at 40s
        det.observe("ok", 40.0)
    assert det.regime().label == "approaching_collapse"


def test_regime_collapse_from_fail_rate():
    det = CliffDetector(window=50)
    for _ in range(30):
        det.observe("ok", 1.0)
    for _ in range(20):
        det.observe("fail", 1.0, http_status=403)  # 40% WAF-shaped
    assert det.regime().label == "collapse"


def test_regime_collapse_from_p95_adaptive_block_signature():
    det = CliffDetector(window=50)
    # V's cycle 8: 403×32 over 185s. p95 > 60 is the signature.
    _feed(det, ["ok"] * 45, wall_s=1.0)
    for _ in range(5):
        det.observe("ok", 180.0)
    assert det.regime().label == "collapse"


def test_regime_either_axis_can_trip_collapse():
    # Verify fail_rate axis can trip collapse given WAF-shaped fails.
    det = CliffDetector(window=50)
    for _ in range(20):
        det.observe("fail", 0.5, http_status=403)  # 66% WAF fails, fast
    for _ in range(10):
        det.observe("ok", 0.5)
    assert det.regime().label == "collapse"


def test_p95_axis_dormant_until_window_full():
    """A single slow record at the MIN_OBS=20 boundary must not trip
    collapse via axis B.

    At n=20 with window=50, `int(0.95 * n) = 19`, so p95 indexes to the
    maximum element — one slow outlier in the first 20 records drives
    p95 > 60s and fires collapse without any actual WAF signal. Arm B's
    shard-o cliffed at 20/899 after a single 66.67s record (retries=0,
    status=ok — just a slow HTTP call), losing 879 pids to a detector
    false positive. Fix: gate axis B on window fullness so p95's known-
    unreliable small-window behavior can't tip state.
    """
    det = CliffDetector(window=50)
    for _ in range(19):
        det.observe("ok", 1.0)
    det.observe("ok", 80.0)  # single slow record; no retries, no fail
    # With only 20 of 50 window filled, axis B must not contribute.
    # (Axis A: 0 fails → fail_rate=0 → under_utilising by fail-rate.)
    assert det.regime().label == "under_utilising"


def test_axis_a_still_fires_early_when_window_not_full():
    """The window-full gate is only for axis B (p95 wall). Axis A
    (WAF-shaped fail rate) must still catch catastrophic fail spikes
    at n=MIN_OBS, even though the window isn't full — otherwise V-style
    collapse that fires in the first 25 records would be missed."""
    det = CliffDetector(window=50)
    for _ in range(20):
        det.observe("fail", 1.0, http_status=403)
    # n=20 (below window=50), 100% WAF-shaped fails.
    # Axis A: fail_rate=1.0 > 0.30 → collapse (axis A not gated).
    assert det.regime().label == "collapse"


def test_window_slides_old_observations_drop():
    det = CliffDetector(window=20)
    for _ in range(20):
        det.observe("fail", 1.0, http_status=403)
    assert det.regime().label == "collapse"
    # Flush with good data
    for _ in range(20):
        det.observe("ok", 1.0)
    assert det.regime().label == "under_utilising"


def test_error_status_counts_as_fail_when_waf_shaped():
    # "error" with a 403 HTTP status is a WAF signal
    det = CliffDetector(window=50)
    for _ in range(30):
        det.observe("ok", 1.0)
    for _ in range(20):
        det.observe("error", 1.0, http_status=403)
    assert det.regime().label == "collapse"


# ----- Data sparsity does NOT trip the detector ------------------------------
# The canary bug: HCs that don't exist in STF return fast NoIncidente fails
# (status=fail, wall_s < 2s, http_status=None, retries={}). These aren't WAF
# signals — they're corpus gaps. The detector must ignore them in fail_rate.


def test_fast_fail_without_waf_signal_does_not_count():
    # 31 % fast NoIncidente-style fails — would trip collapse under the
    # naive rule. Under WAF-shape rule, stays under_utilising.
    det = CliffDetector(window=50)
    for _ in range(34):
        det.observe("ok", 1.8)
    for _ in range(16):
        det.observe("fail", 1.8)  # no http_status, no retries, fast
    assert det.regime().label == "under_utilising"


def test_fail_with_retries_counts_as_waf_shape():
    # Retry-403 fired (success absorbed via tenacity) — still WAF pressure.
    det = CliffDetector(window=50)
    for _ in range(38):
        det.observe("ok", 1.0)
    for _ in range(12):
        det.observe("fail", 2.0, retries={"403": 5})
    assert det.regime().label == "approaching_collapse"


def test_fail_with_slow_wall_counts_as_waf_shape():
    # Slow fail (retry-403 exhausted after 60+ s of tenacity) = WAF.
    det = CliffDetector(window=50)
    for _ in range(38):
        det.observe("ok", 1.0)
    for _ in range(12):
        det.observe("fail", 20.0)  # slow — must count
    assert det.regime().label == "approaching_collapse"


def test_fail_with_http_429_counts_as_waf_shape():
    det = CliffDetector(window=50)
    for _ in range(30):
        det.observe("ok", 1.0)
    for _ in range(20):
        det.observe("fail", 1.0, http_status=429)
    assert det.regime().label == "collapse"


def test_slow_ok_counts_via_p95_axis():
    # Successful-but-slow records (retry-403 absorbed) still signal WAF
    # pressure through the p95 wall_s axis — no status change needed.
    det = CliffDetector(window=50)
    for _ in range(45):
        det.observe("ok", 1.0)
    for _ in range(5):
        det.observe("ok", 70.0)  # p95 > 60 → collapse
    assert det.regime().label == "collapse"


def test_default_window_is_fifty():
    det = CliffDetector()
    _feed(det, ["ok"] * 60, wall_s=1.0)
    # If window weren't 50, we'd have more than 50 entries now and
    # the p95 calculation would be over a different N. Assert len directly.
    assert len(det._statuses) == 50


# ----- observe() surfaces the WAF-shape verdict to callers -------------------
# Motivation: the sweep log record embeds filter_skip so a human auditing
# sweep.log.jsonl can tell which non-ok attempts the detector chose to ignore
# (fast NoIncidente) vs. count (slow, 403, 429, 5xx, retries). Without a
# return value the caller has to re-implement the predicate.


def test_observe_returns_false_for_ok():
    det = CliffDetector(window=50)
    assert det.observe("ok", 1.0) is False
    assert det.observe("ok", 70.0) is False  # slow OK still not "bad" in detector's fail-rate sense


def test_observe_returns_false_for_fast_noincidente_fail():
    det = CliffDetector(window=50)
    # fail, no http_status, no retries, fast — the NoIncidente shape
    assert det.observe("fail", 1.8) is False


def test_observe_returns_true_for_waf_shaped_fail():
    det = CliffDetector(window=50)
    assert det.observe("fail", 1.0, http_status=403) is True
    assert det.observe("fail", 1.0, http_status=429) is True
    assert det.observe("fail", 1.0, http_status=502) is True
    assert det.observe("fail", 20.0) is True  # slow — retry-403 exhausted
    assert det.observe("fail", 1.0, retries={"403": 2}) is True


def test_observe_returns_true_for_error_status_with_403():
    det = CliffDetector(window=50)
    assert det.observe("error", 1.0, http_status=403) is True


# ----- regime() returns a RegimeReading with diagnostic fields ---------------


def test_regime_reading_warming_diagnostics():
    det = CliffDetector(window=50)
    det.observe("ok", 1.0)
    reading = det.regime()
    assert reading.label == "warming"
    assert reading.promoted_by == "warming"
    assert reading.fail_rate == 0.0
    assert reading.p95_wall_s == 0.0


def test_regime_reading_under_utilising_promoted_by_default():
    det = CliffDetector(window=50)
    _feed(det, ["ok"] * 50, wall_s=1.0)
    reading = det.regime()
    assert reading.label == "under_utilising"
    assert reading.promoted_by == "default"
    assert reading.fail_rate == 0.0
    assert reading.p95_wall_s == 1.0


def test_regime_reading_axis_a_promoted_at_approaching_collapse():
    det = CliffDetector(window=50)
    for _ in range(38):
        det.observe("ok", 1.0)
    for _ in range(12):
        det.observe("fail", 1.0, http_status=403)  # 24% WAF-shaped
    reading = det.regime()
    assert reading.label == "approaching_collapse"
    assert reading.promoted_by == "axis_a"
    assert reading.fail_rate == 12 / 50
    assert reading.p95_wall_s == 1.0


def test_regime_reading_axis_b_promoted_by_p95_alone():
    det = CliffDetector(window=50)
    for _ in range(45):
        det.observe("ok", 1.0)
    for _ in range(5):
        det.observe("ok", 40.0)  # p95 ~ 40s, fail_rate = 0
    reading = det.regime()
    assert reading.label == "approaching_collapse"
    assert reading.promoted_by == "axis_b"
    assert reading.fail_rate == 0.0
    assert reading.p95_wall_s == 40.0


def test_regime_reading_both_axes_promoted_at_collapse():
    det = CliffDetector(window=50)
    # Simultaneous: 40 % WAF-shaped fails AND p95 > 60s.
    for _ in range(30):
        det.observe("ok", 1.0)
    for _ in range(20):
        det.observe("fail", 70.0, http_status=403)  # slow + 403 → axis A and B both
    reading = det.regime()
    assert reading.label == "collapse"
    assert reading.promoted_by == "both"


def test_regime_reading_healthy_promoted_by_axis_a():
    det = CliffDetector(window=50)
    for _ in range(45):
        det.observe("ok", 1.0)
    for _ in range(5):  # 10 % WAF-shaped → boundary just into healthy band
        det.observe("fail", 1.0, http_status=403)
    reading = det.regime()
    assert reading.label == "healthy"
    assert reading.promoted_by == "axis_a"
