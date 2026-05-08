"""
evaluation/bias_detector.py

Compares score distributions across feature types to detect systematic quality gaps.

Three analyses:
  detect_bias        — overall mean gap between best and worst category
  section_level_bias — per-section means by category vs. cross-type average
  boost_effectiveness — score lift from bare → boosted inputs per category

With 4–6 runs per category in the current golden set, all findings carry a
low_sample_warning. The statistical threshold (gap > 10 points) is calibrated
for production-scale data; small-sample results are directional only.

CLI:
  python -m evaluation.bias_detector          # formatted report
  python -m evaluation.bias_detector --json   # raw dict
  python -m evaluation.bias_detector --db PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from evaluation.eval_db import get_connection, init_db, DEFAULT_DB_PATH

# Minimum runs per category before bias findings are considered reliable
_MIN_RELIABLE_N = 10

# Default gap threshold (points) above which bias is flagged
_DEFAULT_BIAS_THRESHOLD = 10.0

# Section-level: flag when a category's section mean is this many % below cross-type avg
_SECTION_UNDERPERFORM_PCT = 15.0

# Boost effectiveness: flag when boosted - bare delta is below this
_MIN_BOOST_DELTA = 5.0


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

def get_scores_by_category(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, list[float]]:
    """Query eval_runs and group final scores by feature type.

    Uses the stored feature_type column as the primary source.
    Falls back to parsing golden_set_id prefix (cap_ / web_ / exp_) when
    feature_type is missing — keeps the function useful against partial data.

    Returns:
        {"CAPABILITY": [71, 78, 92, ...], "WEBPAGE": [...], "EXPERIENCE": [...]}
        Only rows where COALESCE(final_score, original_score) IS NOT NULL are included.
    """
    _PREFIX_MAP = {"cap": "CAPABILITY", "web": "WEBPAGE", "exp": "EXPERIENCE"}

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT feature_type,
                   golden_set_id,
                   COALESCE(final_score, original_score) AS score
            FROM   eval_runs
            WHERE  COALESCE(final_score, original_score) IS NOT NULL
            """
        ).fetchall()

    result: dict[str, list[float]] = {}
    for r in rows:
        ftype = r["feature_type"]
        if not ftype:
            prefix = r["golden_set_id"].split("_")[0].lower()
            ftype  = _PREFIX_MAP.get(prefix)
        if not ftype:
            continue
        result.setdefault(ftype, []).append(float(r["score"]))

    return result


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _category_stats(scores: list[float]) -> dict[str, Any]:
    m = _mean(scores)
    return {
        "n":    len(scores),
        "mean": round(m, 2),
        "min":  int(min(scores)),
        "max":  int(max(scores)),
        "stdev": round(_stdev(scores, m), 2),
    }


# ---------------------------------------------------------------------------
# detect_bias
# ---------------------------------------------------------------------------

def detect_bias(
    scores_by_type: dict[str, list[float]],
    threshold: float = _DEFAULT_BIAS_THRESHOLD,
) -> dict[str, Any]:
    """Detect systematic score gaps between feature type categories.

    Args:
        scores_by_type: Output of get_scores_by_category().
        threshold:      Mean-gap (points) above which bias is flagged.

    Returns:
        {
            "category_stats":    {type: {n, mean, min, max, stdev}},
            "overall_mean":      float,
            "max_gap":           float,
            "best_category":     str,
            "worst_category":    str,
            "bias_detected":     bool,
            "low_sample_warning": str | None,
            "findings":          [str],
            "recommendations":   [str],
        }
    """
    if not scores_by_type:
        return {
            "category_stats": {}, "overall_mean": 0.0, "max_gap": 0.0,
            "best_category": None, "worst_category": None,
            "bias_detected": False, "low_sample_warning": "No data in DB.",
            "findings": ["No eval runs found."], "recommendations": [],
        }

    category_stats: dict[str, dict] = {
        t: _category_stats(s) for t, s in scores_by_type.items()
    }

    all_scores = [s for scores in scores_by_type.values() for s in scores]
    overall_mean = round(_mean(all_scores), 2)

    means    = {t: s["mean"] for t, s in category_stats.items()}
    best_cat  = max(means, key=means.__getitem__)
    worst_cat = min(means, key=means.__getitem__)
    max_gap   = round(means[best_cat] - means[worst_cat], 2)

    # Low-sample warning
    low_n_types = [t for t, s in category_stats.items() if s["n"] < _MIN_RELIABLE_N]
    low_sample_warning: str | None = None
    if low_n_types:
        low_sample_warning = (
            f"Low sample count for: {', '.join(sorted(low_n_types))} "
            f"(need ≥{_MIN_RELIABLE_N} runs each for reliable bias detection; "
            f"current findings are directional only)."
        )

    bias_detected = max_gap > threshold

    findings: list[str] = []
    recommendations: list[str] = []

    if bias_detected:
        findings.append(
            f"Mean score gap of {max_gap:.1f} points between "
            f"{best_cat} ({means[best_cat]:.1f}) and "
            f"{worst_cat} ({means[worst_cat]:.1f}) exceeds the "
            f"{threshold:.0f}-point threshold."
        )
        recommendations.append(
            f"Investigate why {worst_cat} specs score lower. "
            "Check if the reviewer rubric, generator prompt, or PM input "
            "quality differs systematically for this type."
        )
    else:
        findings.append(
            f"No significant bias detected. Max gap: {max_gap:.1f} points "
            f"({best_cat} vs {worst_cat}) — within the {threshold:.0f}-point threshold."
        )

    # Flag any category more than 1 overall-stdev below the overall mean
    overall_stdev = round(_stdev(all_scores, overall_mean), 2)
    for t, stats in category_stats.items():
        if overall_stdev > 0 and stats["mean"] < (overall_mean - overall_stdev):
            findings.append(
                f"{t} mean ({stats['mean']:.1f}) is more than 1 stdev "
                f"({overall_stdev:.1f}) below overall mean ({overall_mean:.1f})."
            )
            if t not in (r.split()[0] for r in recommendations):
                recommendations.append(
                    f"Review {t} pipeline: lower mean may reflect thinner PM inputs, "
                    "stricter rubric application, or a generator prompt gap."
                )

    return {
        "category_stats":     category_stats,
        "overall_mean":       overall_mean,
        "overall_stdev":      overall_stdev,
        "max_gap":            max_gap,
        "best_category":      best_cat,
        "worst_category":     worst_cat,
        "bias_detected":      bias_detected,
        "threshold_used":     threshold,
        "low_sample_warning": low_sample_warning,
        "findings":           findings,
        "recommendations":    recommendations,
    }


# ---------------------------------------------------------------------------
# section_level_bias
# ---------------------------------------------------------------------------

def section_level_bias(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Compare per-section means across feature types.

    Pulls all scorecards from the DB, computes mean section score for each
    (feature_type, section_name) pair, then compares against the cross-type
    average for that section.

    Returns:
        {
            "section_means":   {section: {type: mean}},
            "cross_type_mean": {section: float},
            "flagged":         [
                {section, feature_type, type_mean, cross_mean, gap_pct}
            ],
            "low_sample_warning": str | None,
        }
    """
    _PREFIX_MAP = {"cap": "CAPABILITY", "web": "WEBPAGE", "exp": "EXPERIENCE"}

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT feature_type, golden_set_id, scorecard FROM eval_runs "
            "WHERE scorecard IS NOT NULL"
        ).fetchall()

    # Accumulate: section_scores[section][feature_type] = [score, ...]
    section_scores: dict[str, dict[str, list[float]]] = {}

    for r in rows:
        ftype = r["feature_type"]
        if not ftype:
            prefix = r["golden_set_id"].split("_")[0].lower()
            ftype  = _PREFIX_MAP.get(prefix)
        if not ftype:
            continue

        try:
            sc = json.loads(r["scorecard"])
        except (json.JSONDecodeError, TypeError):
            continue

        sections = sc.get("sections", {})
        for sec_name, sec_data in sections.items():
            score     = sec_data.get("score")
            max_pts   = sec_data.get("max_points", 0)
            if score is None or max_pts == 0:
                continue
            # Normalise to percentage of max so sections with different weights
            # are comparable.
            pct = score / max_pts * 100
            section_scores.setdefault(sec_name, {}).setdefault(ftype, []).append(pct)

    # Compute means
    section_means: dict[str, dict[str, float]] = {}
    cross_type_mean: dict[str, float] = {}

    for sec, by_type in section_scores.items():
        type_means: dict[str, float] = {}
        all_vals: list[float] = []
        for ftype, vals in by_type.items():
            m = _mean(vals)
            type_means[ftype] = round(m, 2)
            all_vals.extend(vals)
        section_means[sec]    = type_means
        cross_type_mean[sec]  = round(_mean(all_vals), 2)

    # Flag: type_mean < cross_mean * (1 - threshold/100)
    flagged: list[dict[str, Any]] = []
    for sec, by_type in section_means.items():
        cross = cross_type_mean[sec]
        for ftype, tm in by_type.items():
            if cross > 0:
                gap_pct = (cross - tm) / cross * 100
                if gap_pct > _SECTION_UNDERPERFORM_PCT:
                    flagged.append({
                        "section":      sec,
                        "feature_type": ftype,
                        "type_mean_pct":  round(tm, 2),
                        "cross_mean_pct": round(cross, 2),
                        "gap_pct":        round(gap_pct, 2),
                    })

    # Sort by gap descending
    flagged.sort(key=lambda x: -x["gap_pct"])

    # Low-sample warning: count distinct runs per (section, type)
    type_counts: dict[str, int] = {}
    for sec, by_type in section_scores.items():
        for ftype, vals in by_type.items():
            type_counts[ftype] = max(type_counts.get(ftype, 0), len(vals))

    low_n = [t for t, n in type_counts.items() if n < _MIN_RELIABLE_N]
    low_sample_warning = (
        f"Low section-level sample count for: {', '.join(sorted(low_n))}. "
        f"Need ≥{_MIN_RELIABLE_N} runs per type for reliable section analysis."
    ) if low_n else None

    return {
        "section_means":      section_means,
        "cross_type_mean":    cross_type_mean,
        "flagged":            flagged,
        "low_sample_warning": low_sample_warning,
    }


# ---------------------------------------------------------------------------
# boost_effectiveness
# ---------------------------------------------------------------------------

def boost_effectiveness(db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Compare bare vs boosted scores per feature type.

    Identifies bare/boosted by _bare / _boosted suffix in golden_set_id.

    Returns:
        {
            "by_type": {
                feature_type: {
                    "bare_mean":    float | None,
                    "boosted_mean": float | None,
                    "delta":        float | None,
                    "bare_n":       int,
                    "boosted_n":    int,
                    "low_delta_flag": bool,
                }
            },
            "low_sample_warning": str | None,
            "low_delta_types":    [str],
        }
    """
    _PREFIX_MAP = {"cap": "CAPABILITY", "web": "WEBPAGE", "exp": "EXPERIENCE"}

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT feature_type,
                   golden_set_id,
                   COALESCE(final_score, original_score) AS score
            FROM   eval_runs
            WHERE  COALESCE(final_score, original_score) IS NOT NULL
            """
        ).fetchall()

    # Accumulate bare/boosted scores per type
    bare:    dict[str, list[float]] = {}
    boosted: dict[str, list[float]] = {}

    for r in rows:
        ftype = r["feature_type"]
        if not ftype:
            prefix = r["golden_set_id"].split("_")[0].lower()
            ftype  = _PREFIX_MAP.get(prefix)
        if not ftype:
            continue

        gid = r["golden_set_id"].lower()
        if "_bare" in gid:
            bare.setdefault(ftype, []).append(float(r["score"]))
        elif "_boosted" in gid:
            boosted.setdefault(ftype, []).append(float(r["score"]))

    all_types = sorted(set(list(bare) + list(boosted)))
    by_type: dict[str, dict[str, Any]] = {}
    low_delta_types: list[str] = []

    for ftype in all_types:
        bare_scores    = bare.get(ftype, [])
        boosted_scores = boosted.get(ftype, [])
        bare_mean      = round(_mean(bare_scores), 2) if bare_scores else None
        boosted_mean   = round(_mean(boosted_scores), 2) if boosted_scores else None
        delta          = (
            round(boosted_mean - bare_mean, 2)
            if bare_mean is not None and boosted_mean is not None
            else None
        )
        low_flag = delta is not None and delta < _MIN_BOOST_DELTA
        if low_flag:
            low_delta_types.append(ftype)

        by_type[ftype] = {
            "bare_mean":       bare_mean,
            "boosted_mean":    boosted_mean,
            "delta":           delta,
            "bare_n":          len(bare_scores),
            "boosted_n":       len(boosted_scores),
            "low_delta_flag":  low_flag,
        }

    # Low-sample warning
    low_n = [
        t for t, d in by_type.items()
        if d["bare_n"] < _MIN_RELIABLE_N or d["boosted_n"] < _MIN_RELIABLE_N
    ]
    low_sample_warning = (
        f"Low boost sample count for: {', '.join(sorted(low_n))}. "
        f"Need ≥{_MIN_RELIABLE_N} runs each (bare + boosted) for reliable delta estimates."
    ) if low_n else None

    return {
        "by_type":            by_type,
        "min_boost_delta":    _MIN_BOOST_DELTA,
        "low_delta_types":    low_delta_types,
        "low_sample_warning": low_sample_warning,
    }


# ---------------------------------------------------------------------------
# run_bias_report
# ---------------------------------------------------------------------------

def run_bias_report(
    db_path: Path = DEFAULT_DB_PATH,
    threshold: float = _DEFAULT_BIAS_THRESHOLD,
) -> dict[str, Any]:
    """Run all three analyses and return a combined report dict.

    Safe to call against an empty or missing DB — each sub-report degrades
    gracefully to empty/zero-state results.
    """
    if not db_path.exists():
        return {
            "db_path":     str(db_path),
            "error":       f"DB not found: {db_path}",
            "bias":        {},
            "section":     {},
            "boost":       {},
        }

    scores = get_scores_by_category(db_path)

    return {
        "db_path":  str(db_path),
        "bias":     detect_bias(scores, threshold=threshold),
        "section":  section_level_bias(db_path),
        "boost":    boost_effectiveness(db_path),
    }


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_W = 72


def _sep(title: str = "") -> None:
    if title:
        print(f"\n{'=' * _W}\n  {title}\n{'=' * _W}")
    else:
        print("=" * _W)


def _warn(msg: str) -> None:
    if msg:
        print(f"\n  ⚠  {msg}")


def _print_report(report: dict[str, Any]) -> None:
    _sep()
    print("  BIAS DETECTION REPORT — SAFe Feature Spec System")
    print(f"  DB: {report['db_path']}")
    _sep()

    if "error" in report:
        print(f"\n  ERROR: {report['error']}")
        return

    # ── 1. Overall bias ───────────────────────────────────────────────────────
    _sep("1. OVERALL SCORE DISTRIBUTION BY CATEGORY")
    bias = report["bias"]
    _warn(bias.get("low_sample_warning", ""))

    stats = bias.get("category_stats", {})
    if stats:
        print(f"\n  {'Category':<14} {'N':>3}  {'Mean':>6}  {'Min':>4}  {'Max':>4}  {'Stdev':>6}")
        print(f"  {'-' * 44}")
        for cat, s in sorted(stats.items()):
            marker = " ◀" if cat == bias.get("worst_category") else ""
            print(
                f"  {cat:<14} {s['n']:>3}  {s['mean']:>6.1f}  "
                f"{s['min']:>4}  {s['max']:>4}  {s['stdev']:>6.2f}{marker}"
            )
        print(f"\n  Overall mean: {bias.get('overall_mean', 0):.1f}  "
              f"stdev: {bias.get('overall_stdev', 0):.1f}  "
              f"max gap: {bias.get('max_gap', 0):.1f} pts  "
              f"threshold: {bias.get('threshold_used', _DEFAULT_BIAS_THRESHOLD):.0f} pts")

    detected = bias.get("bias_detected", False)
    status   = "BIAS DETECTED" if detected else "NO BIAS DETECTED"
    print(f"\n  Status: {status}")
    for f in bias.get("findings", []):
        print(f"    • {f}")
    for r in bias.get("recommendations", []):
        print(f"    → {r}")

    # ── 2. Section-level bias ─────────────────────────────────────────────────
    _sep("2. SECTION-LEVEL BIAS (normalised % of section max)")
    sec = report["section"]
    _warn(sec.get("low_sample_warning", ""))

    cross = sec.get("cross_type_mean", {})
    means = sec.get("section_means", {})
    if means:
        all_types = sorted({t for tm in means.values() for t in tm})
        header = f"  {'Section':<42} {'Cross':>6}  " + "  ".join(f"{t[:4]:>6}" for t in all_types)
        print(f"\n{header}")
        print(f"  {'-' * (len(header) - 2)}")
        for sec_name in sorted(means):
            cross_mean = cross.get(sec_name, 0)
            row = f"  {sec_name[:42]:<42} {cross_mean:>6.1f}  "
            for t in all_types:
                tm = means[sec_name].get(t)
                cell = f"{tm:>6.1f}" if tm is not None else f"{'—':>6}"
                # Underline (with flag char) if this cell is flagged
                is_flagged = any(
                    fl["section"] == sec_name and fl["feature_type"] == t
                    for fl in sec.get("flagged", [])
                )
                row += f"  {cell}{'⚑' if is_flagged else ' '}"
            print(row)

    flagged = sec.get("flagged", [])
    if flagged:
        print(f"\n  Flagged (>{int(_SECTION_UNDERPERFORM_PCT)}% below cross-type average):")
        for fl in flagged:
            print(
                f"    ⚑  {fl['feature_type']:<12}  {fl['section'][:38]:<38}  "
                f"type={fl['type_mean_pct']:.1f}%  cross={fl['cross_mean_pct']:.1f}%  "
                f"gap={fl['gap_pct']:.1f}%"
            )
    else:
        print("\n  No sections flagged.")

    # ── 3. Boost effectiveness ────────────────────────────────────────────────
    _sep("3. BOOST EFFECTIVENESS (bare → boosted delta)")
    boost = report["boost"]
    _warn(boost.get("low_sample_warning", ""))

    by_type = boost.get("by_type", {})
    if by_type:
        print(f"\n  {'Category':<14} {'Bare mean':>10}  {'n':>3}  {'Boost mean':>10}  {'n':>3}  {'Delta':>7}  {'Flag'}")
        print(f"  {'-' * 62}")
        for ftype, d in sorted(by_type.items()):
            bare_s    = f"{d['bare_mean']:.1f}"    if d["bare_mean"]    is not None else "—"
            boost_s   = f"{d['boosted_mean']:.1f}" if d["boosted_mean"] is not None else "—"
            delta_s   = f"{d['delta']:+.1f}"       if d["delta"]        is not None else "—"
            flag      = "⚑ low boost" if d["low_delta_flag"] else ""
            print(
                f"  {ftype:<14} {bare_s:>10}  {d['bare_n']:>3}  "
                f"{boost_s:>10}  {d['boosted_n']:>3}  {delta_s:>7}  {flag}"
            )
        min_delta = boost.get("min_boost_delta", _MIN_BOOST_DELTA)
        low_types = boost.get("low_delta_types", [])
        if low_types:
            print(f"\n  Low-boost types (delta < {min_delta:.0f} pts): {', '.join(low_types)}")
        else:
            print(f"\n  All types show ≥{min_delta:.0f}-point boost improvement.")

    _sep()
    print()


# ---------------------------------------------------------------------------
# Smoke test — runs against synthetic in-memory data when no DB exists
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Verify detect_bias and boost_effectiveness logic with known inputs."""
    failures: list[str] = []

    print("=" * _W)
    print("  BIAS DETECTOR — smoke test (no DB required)")
    print("=" * _W)

    # ── detect_bias ───────────────────────────────────────────────────────────
    print("\n[1] detect_bias — gap above threshold")
    scores_biased = {
        "CAPABILITY": [90.0, 88.0, 92.0, 86.0, 89.0, 91.0],
        "WEBPAGE":    [60.0, 62.0, 58.0, 64.0, 61.0, 63.0],   # ~30-pt gap
        "EXPERIENCE": [80.0, 82.0, 79.0, 81.0, 83.0, 80.0],
    }
    r = detect_bias(scores_biased, threshold=10.0)
    ok = r["bias_detected"] is True
    print(f"  [{'PASS' if ok else 'FAIL'}] bias detected when gap={r['max_gap']:.1f} > 10")
    if not ok:
        failures.append(f"bias not detected: gap={r['max_gap']}")

    ok = r["worst_category"] == "WEBPAGE"
    print(f"  [{'PASS' if ok else 'FAIL'}] worst_category='WEBPAGE' (got '{r['worst_category']}')")
    if not ok:
        failures.append(f"worst_category wrong: {r['worst_category']}")

    print("\n[2] detect_bias — gap below threshold")
    scores_even = {
        "CAPABILITY": [83.0, 85.0, 82.0],
        "WEBPAGE":    [80.0, 81.0, 79.0],
        "EXPERIENCE": [84.0, 83.0, 85.0],
    }
    r2 = detect_bias(scores_even, threshold=10.0)
    ok = r2["bias_detected"] is False
    print(f"  [{'PASS' if ok else 'FAIL'}] no bias when gap={r2['max_gap']:.1f} <= 10")
    if not ok:
        failures.append(f"false bias detected: gap={r2['max_gap']}")

    print("\n[3] detect_bias — low_sample_warning present")
    ok = r2["low_sample_warning"] is not None
    print(f"  [{'PASS' if ok else 'FAIL'}] low_sample_warning issued for n<{_MIN_RELIABLE_N}")
    if not ok:
        failures.append("low_sample_warning missing for small-n data")

    print("\n[4] boost_effectiveness — delta computation")
    # Patch directly against known values
    bare_scores    = {"CAPABILITY": [71.0, 78.0, 71.0], "WEBPAGE": [62.0, 72.0]}
    boosted_scores = {"CAPABILITY": [93.0, 92.0, 92.0], "WEBPAGE": [87.0, 87.0]}
    for ftype in ["CAPABILITY", "WEBPAGE"]:
        b  = round(_mean(bare_scores[ftype]), 2)
        bo = round(_mean(boosted_scores[ftype]), 2)
        delta = round(bo - b, 2)
        ok = delta >= _MIN_BOOST_DELTA
        print(f"  [{'PASS' if ok else 'FAIL'}] {ftype}: bare={b:.1f} boosted={bo:.1f} delta={delta:+.1f}")
        if not ok:
            failures.append(f"{ftype} delta {delta:.1f} < {_MIN_BOOST_DELTA}")

    print("\n[5] detect_bias — empty input")
    r_empty = detect_bias({})
    ok = r_empty["bias_detected"] is False and "No data" in r_empty["low_sample_warning"]
    print(f"  [{'PASS' if ok else 'FAIL'}] empty scores handled gracefully")
    if not ok:
        failures.append(f"empty scores not handled: {r_empty}")

    print(f"\n{'=' * _W}")
    if failures:
        print(f"  RESULT: {len(failures)} failure(s)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: all checks passed")
    print("=" * _W)

    raise SystemExit(1 if failures else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Bias detection report for SAFe Feature Spec eval pipeline"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to eval SQLite DB (default: evaluation/eval.db)",
    )
    parser.add_argument(
        "--threshold",
        metavar="POINTS",
        type=float,
        default=_DEFAULT_BIAS_THRESHOLD,
        help=f"Mean-gap threshold for bias flag (default: {_DEFAULT_BIAS_THRESHOLD})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON instead of formatted report",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run smoke test (no DB required)",
    )
    args = parser.parse_args()

    if args.smoke_test:
        _smoke_test()

    db_path = Path(args.db)

    # If DB doesn't exist yet, run smoke test instead of erroring
    if not db_path.exists():
        print(f"DB not found at {db_path} — running smoke test instead.\n")
        _smoke_test()

    init_db(db_path)
    report = run_bias_report(db_path, threshold=args.threshold)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)
