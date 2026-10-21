"""Depth-pass coverage tripwire.

Acceptance gate between Stage 2c (main-agent depth pass) and Stage 3
(synthesis). Returns / exits non-zero when ``verification.jsonl`` covers
less than a threshold fraction of the planned reads in
``_depth_plan.jsonl``.

Empirical anchor: ``relatorio-advogado`` run on Toron HC (2026-05-15)
terminated with 12 of 29 planned reads verified (0 of 13 non-concedido
losses). The narrative misattributed at least one case to the wrong
argumentative register — a mistake primary-text reading would have
caught. The tripwire converts the "≥ 95 % coverage" norm into a
deterministic gate.

Usage as CLI::

    uv run python -m judex.skills.actor_profile.tripwire \\
        --internal data/derived/reports/<slug>/internal/

Usage as library::

    from judex.skills.actor_profile.tripwire import verify_depth_coverage
    result = verify_depth_coverage(Path("…/internal"))
    if not result.ok:
        # missing SHAs in result.missing, per-tier breakdown in
        # result.missing_by_tier
        ...
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field

DEFAULT_THRESHOLD = 0.95


@dataclass(frozen=True)
class CoverageResult:
    ok: bool
    coverage: float
    threshold: float
    n_plan: int
    n_verified_in_plan: int
    missing: list[str]
    extra: list[str]
    missing_by_tier: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "coverage": round(self.coverage, 4),
            "threshold": self.threshold,
            "n_plan": self.n_plan,
            "n_verified_in_plan": self.n_verified_in_plan,
            "n_missing": len(self.missing),
            "n_extra": len(self.extra),
            "missing_by_tier": dict(sorted(self.missing_by_tier.items())),
            "missing": self.missing,
            "extra": self.extra,
        }


def _load_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _shas(rows: list[dict]) -> set[str]:
    return {r["sha"] for r in rows if "sha" in r}


def verify_depth_coverage(
    internal: pathlib.Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> CoverageResult:
    """Compute depth-coverage against the plan in ``internal/``.

    Raises ``FileNotFoundError`` if ``_depth_plan.jsonl`` is missing
    (Stage 2c was never staged). An empty ``verification.jsonl`` is
    treated as 0 % coverage rather than an error — the gate's job is to
    surface the gap, not to demand the file exist.
    """
    plan_rows = _load_jsonl(internal / "_depth_plan.jsonl")
    if not plan_rows:
        raise FileNotFoundError(
            f"no _depth_plan.jsonl in {internal}; Stage 2c not staged"
        )
    verif_rows = _load_jsonl(internal / "verification.jsonl")

    plan_shas = _shas(plan_rows)
    verif_shas = _shas(verif_rows)
    n_plan = len(plan_shas)
    n_hit = len(verif_shas & plan_shas)
    coverage = n_hit / n_plan if n_plan else 0.0
    missing = sorted(plan_shas - verif_shas)
    extra = sorted(verif_shas - plan_shas)

    plan_idx = {p["sha"]: p for p in plan_rows}
    miss_by_tier: dict[str, int] = {}
    for sha in missing:
        tier = plan_idx.get(sha, {}).get("tier", "?")
        miss_by_tier[tier] = miss_by_tier.get(tier, 0) + 1

    return CoverageResult(
        ok=coverage >= threshold,
        coverage=coverage,
        threshold=threshold,
        n_plan=n_plan,
        n_verified_in_plan=n_hit,
        missing=missing,
        extra=extra,
        missing_by_tier=miss_by_tier,
    )


def _format_prose(result: CoverageResult, internal: pathlib.Path) -> str:
    plan_idx = {
        p["sha"]: p
        for p in _load_jsonl(internal / "_depth_plan.jsonl")
    }
    mfst_idx = {
        m["sha"]: m
        for m in _load_jsonl(internal / "manifest.jsonl")
    }

    bar = "✓" if result.ok else "✗"
    out = [
        f"{bar} depth coverage: {result.n_verified_in_plan}/{result.n_plan} "
        f"= {result.coverage:.1%} (threshold {result.threshold:.0%})"
    ]
    if result.missing_by_tier:
        out.append("")
        out.append("missing by tier:")
        for tier, n in sorted(result.missing_by_tier.items()):
            out.append(f"  {tier}: {n}")
    if result.missing:
        out.append("")
        out.append(f"{len(result.missing)} planned read(s) not in verification.jsonl:")
        for sha in result.missing[:30]:
            p = plan_idx.get(sha, {})
            m = mfst_idx.get(sha, {})
            case = p.get("case") or m.get("case") or "?"
            dt = p.get("doc_type") or m.get("doc_type") or "?"
            tier = p.get("tier", "?")
            cr = p.get("chars_read", "?")
            out.append(
                f"  - [{tier}] {case:<12} {dt:<28} chars_read={cr}  {sha}"
            )
        if len(result.missing) > 30:
            out.append(f"  ... and {len(result.missing) - 30} more")
    if result.extra:
        out.append("")
        out.append(
            f"{len(result.extra)} verification row(s) not in plan "
            f"(unsolicited reads — informational):"
        )
        for sha in result.extra[:10]:
            out.append(f"  - {sha}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Depth-pass coverage tripwire (≥ 95 % of plan)."
    )
    ap.add_argument(
        "--internal", type=pathlib.Path, required=True,
        help="path to the report's internal/ directory",
    )
    ap.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help=f"min coverage ratio (default {DEFAULT_THRESHOLD})",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON result",
    )
    args = ap.parse_args(argv)

    try:
        result = verify_depth_coverage(
            args.internal, threshold=args.threshold,
        )
    except FileNotFoundError as e:
        if args.json:
            print(json.dumps(
                {"ok": False, "reason": "no_plan", "internal": str(args.internal)}
            ))
        else:
            print(str(e), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok else 2

    print(_format_prose(result, args.internal))
    if not result.ok:
        print(
            "\n→ Action: read the missing peças via Read tool on the staged "
            "paths in _depth_staged/<sha>.txt and append entries to "
            "verification.jsonl before proceeding to Stage 3.",
            file=sys.stderr,
        )
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
