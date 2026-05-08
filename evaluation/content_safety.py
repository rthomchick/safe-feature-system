"""
evaluation/content_safety.py

Deterministic (non-LLM) safety checks for generated SAFe Feature Specs.

These are cheap, fast regex/keyword scans that run before the grounding checker.
They catch obvious violations — PII leaks, fabricated numbers, out-of-scope topics —
without making any LLM calls.

Checks:
  pii              — emails, phone numbers, SSNs, internal URLs not from PM inputs
  fabricated_metrics — numeric claims in the spec not traceable to PM inputs
  scope_creep      — major topics in spec sections absent from PM inputs

Usage:
  from evaluation.content_safety import run_all_safety_checks
  result = run_all_safety_checks(spec_text, pm_inputs)

Smoke test:
  python -m evaluation.content_safety
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    check:       str            # check name
    severity:    str            # HIGH | MEDIUM | LOW
    text:        str            # the flagged text or value
    location:    str            # section heading or "global"
    explanation: str            # why it was flagged
    confidence:  str = "HIGH"   # HIGH | MEDIUM — applies to heuristic checks


@dataclass
class CheckResult:
    name:     str
    passed:   bool
    findings: list[Finding] = field(default_factory=list)
    note:     str = ""          # optional summary note


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Identify ## section the match falls under
def _section_of(text: str, match_start: int) -> str:
    """Return the closest ## heading before match_start, or 'global'."""
    preceding = text[:match_start]
    headings  = list(re.finditer(r"^##\s+(.+)$", preceding, re.MULTILINE))
    return headings[-1].group(1).strip() if headings else "global"


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Check 1 — PII / internal URLs
# ---------------------------------------------------------------------------

# Patterns that should never appear in a generated spec
_PII_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, label, severity)
    (
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "email address",
        "HIGH",
    ),
    (
        # North American phone: (xxx) xxx-xxxx, xxx-xxx-xxxx, +1-xxx-xxx-xxxx, etc.
        r"(?<!\d)(?:\+1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}(?!\d)",
        "phone number",
        "HIGH",
    ),
    (
        # SSN: xxx-xx-xxxx
        r"\b\d{3}-\d{2}-\d{4}\b",
        "SSN",
        "HIGH",
    ),
    (
        # Internal subdomains: anything.internal.*, *.corp.*, *.internal/*
        r"https?://[^\s\"'>]*\.(?:internal|corp|intranet|local)(?:[/\s\"'>]|$)",
        "internal URL",
        "MEDIUM",
    ),
    (
        # servicenow internal paths: *.servicenow.com/sys_*, /nav_to.do, /api/now/
        # (servicenow.com alone is legitimate in PM inputs; internal admin paths are not)
        r"https?://[^\s\"'>]*\.?servicenow\.com/(?:sys_|nav_to\.do|api/now/)[^\s\"'>]*",
        "ServiceNow internal path",
        "MEDIUM",
    ),
]


def check_no_pii(spec_text: str, pm_inputs: str = "") -> CheckResult:
    """Regex scan for PII and internal URLs not originating from PM inputs.

    pm_inputs is used to suppress false positives: if the pattern match also
    appears verbatim in pm_inputs, the PM owns it and we skip it.
    """
    findings: list[Finding] = []

    for pattern, label, severity in _PII_PATTERNS:
        for m in re.finditer(pattern, spec_text, re.IGNORECASE):
            matched = m.group(0).strip()
            # Suppress if the exact match appears in PM inputs (PM-owned data)
            if pm_inputs and matched in pm_inputs:
                continue
            findings.append(Finding(
                check="pii",
                severity=severity,
                text=matched,
                location=_section_of(spec_text, m.start()),
                explanation=f"Detected {label} not present in PM inputs.",
            ))

    return CheckResult(
        name="pii",
        passed=len(findings) == 0,
        findings=findings,
        note=f"{len(findings)} PII/internal-URL finding(s)",
    )


# ---------------------------------------------------------------------------
# Check 2 — fabricated metrics
# ---------------------------------------------------------------------------

# Numeric claim patterns we want to trace back to PM inputs.
# Each pattern captures the full claim token for comparison.
_METRIC_PATTERNS: list[tuple[str, str]] = [
    # Named patterns with their category label
    (r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?%?",           "large number (comma-formatted)"),
    (r"\b\d+(?:\.\d+)?%",                             "percentage"),
    (r"\$\s*\d+(?:[.,]\d+)*(?:\s*[KkMmBb])?",        "dollar amount"),
    (r"\b(?:PI|Sprint|Q[1-4])\s*\d+\b",               "PI/Sprint/Quarter reference"),
    (r"\b\d{4}-\d{2}-\d{2}\b",                        "ISO date"),
    (r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\b",
                                                       "month/year date"),
    (r"≤\s*\d+\s*ms|\b\d+\s*ms\b",                   "millisecond latency"),
    (r"\b\d+(?:\.\d+)?\s*(?:seconds?|hours?|days?|weeks?|months?)\b",
                                                       "duration"),
    (r"\b\d+\s*(?:story\s*points?|SP)\b",             "story points"),
    (r"\b(?:P[0-4])\b",                               "priority tag"),   # P0-P4 are SAFe boilerplate
]

# Tokens that are always valid SAFe/Gherkin boilerplate regardless of PM inputs
_METRIC_ALLOWLIST: list[str] = [
    # Standard SAFe priority levels
    "P0", "P1", "P2", "P3", "P4",
    # Common story-point scales
    "1", "2", "3", "5", "8", "13",
]

# Patterns whose matches are always allowlisted (boilerplate)
_ALWAYS_ALLOWED_PATTERNS: list[str] = [
    r"^P[0-4]$",                # priority tags
    r"^\d{1,2}$",               # small integers (story points, etc.)
    r"^\d+\s*story\s*points?$", # story point expressions are SAFe boilerplate
    r"^[SMLXL]+$",              # T-shirt size estimates
]


def _extract_numeric_claims(text: str) -> list[tuple[str, int, str]]:
    """Return list of (matched_text, start_pos, category) for all numeric claims."""
    seen: set[str] = set()
    results: list[tuple[str, int, str]] = []
    for pattern, category in _METRIC_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            token = _normalize_whitespace(m.group(0))
            key   = (token.lower(), m.start())
            if key not in seen:
                seen.add(key)
                results.append((token, m.start(), category))
    return results


def _is_allowlisted(token: str) -> bool:
    if token in _METRIC_ALLOWLIST:
        return True
    for pat in _ALWAYS_ALLOWED_PATTERNS:
        if re.fullmatch(pat, token, re.IGNORECASE):
            return True
    return False


def _token_in_inputs(token: str, pm_inputs: str) -> bool:
    """Check whether the numeric token appears in PM inputs.

    Also checks a stripped version — e.g. '≤200ms' matches if '200ms' is in inputs,
    since the PM may have written the number without the comparison operator.
    """
    # Direct match
    escaped = re.escape(token)
    if re.search(escaped, pm_inputs, re.IGNORECASE):
        return True
    # Strip leading comparison operators (≤, ≥, <, >, ±, ~, ≈) and re-check
    stripped = re.sub(r"^[≤≥<>±~≈\s]+", "", token).strip()
    if stripped and stripped != token:
        return bool(re.search(re.escape(stripped), pm_inputs, re.IGNORECASE))
    return False


def check_no_fabricated_metrics(spec_text: str, pm_inputs: str) -> CheckResult:
    """Extract numeric claims from spec and flag those absent from PM inputs.

    Suppressions:
    - Allowlisted values (story-point scales, P0-P4)
    - Tokens that appear verbatim in pm_inputs
    - Numbers inside [NEEDS INPUT: ...] placeholders (they're flagged, not invented)
    """
    # Remove [NEEDS INPUT: ...] blocks before scanning — placeholders aren't claims
    spec_clean = re.sub(r"\[NEEDS INPUT:[^\]]*\]", "", spec_text)

    claims     = _extract_numeric_claims(spec_clean)
    findings:  list[Finding] = []
    seen_flags: set[str] = set()

    for token, start, category in claims:
        if _is_allowlisted(token):
            continue
        if _token_in_inputs(token, pm_inputs):
            continue
        if token.lower() in seen_flags:
            continue
        seen_flags.add(token.lower())

        findings.append(Finding(
            check="fabricated_metrics",
            severity="MEDIUM",
            text=token,
            location=_section_of(spec_clean, start),
            explanation=(
                f"{category} '{token}' appears in the spec but not in PM inputs. "
                "Verify this is not an invented figure."
            ),
        ))

    return CheckResult(
        name="fabricated_metrics",
        passed=len(findings) == 0,
        findings=findings,
        note=f"{len(findings)} untraced numeric claim(s)",
    )


# ---------------------------------------------------------------------------
# Check 3 — scope creep (heuristic keyword extraction)
# ---------------------------------------------------------------------------

# SAFe/spec structural boilerplate that is always valid to include, even if
# not mentioned in PM inputs — the generator is expected to add these.
_BOILERPLATE_TOPICS: frozenset[str] = frozenset([
    "user story", "user stories", "acceptance criteria", "gherkin", "given when then",
    "given", "when", "then", "invest", "traceability", "priority", "effort estimate",
    "story points", "p0", "p1", "p2", "p3", "p4", "feature title", "description",
    "out of scope", "in-scope", "dependencies", "solution approach",
    "definition of done", "non-functional", "performance", "accessibility",
    "wcag", "stakeholder", "feature owner", "tech lead", "pm", "epic",
    # Standard system nouns that appear in any enterprise spec
    "api", "ui", "ux", "seo", "analytics", "qa", "testing", "staging",
    "rollback", "feature flag", "monitoring", "dashboard", "launch",
    "deployment", "rollout", "publish", "publishing",
])

# Words too common to be meaningful topic signals
_STOPWORDS: frozenset[str] = frozenset([
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "will", "would", "can", "could", "should", "may",
    "might", "this", "that", "these", "those", "it", "its", "as", "not",
    "no", "if", "all", "any", "each", "more", "also", "new", "into", "per",
    "their", "they", "we", "our", "which", "who", "when", "where", "how",
    "what", "i", "you", "he", "she", "us", "them", "so", "do", "does",
    "did", "than", "then", "about", "up", "out", "over", "after", "before",
    "both", "just", "only", "such", "other", "some", "within", "without",
    "across", "between", "through", "during", "must", "need", "needs",
    "required", "requires", "include", "includes", "provide", "provides",
    "ensure", "ensures", "support", "supports", "use", "used", "using",
])

# Minimum token length to consider as a topic signal
_MIN_TOPIC_LEN = 4

# Number of top keywords to extract from pm_inputs as the "allowed topic set"
_TOP_PM_KEYWORDS  = 60
_TOP_SPEC_KEYWORDS = 40

# Fraction of spec keywords that must be in pm_keywords to pass
_OVERLAP_WARN_THRESHOLD = 0.60   # below this → WARN finding


def _extract_keywords(text: str, top_n: int) -> dict[str, int]:
    """Return top_n most-frequent meaningful tokens from text."""
    tokens = re.findall(r"[a-z][a-z0-9\-]{%d,}" % (_MIN_TOPIC_LEN - 1), text.lower())
    counts: dict[str, int] = {}
    for tok in tokens:
        if tok not in _STOPWORDS:
            counts[tok] = counts.get(tok, 0) + 1
    # Sort by frequency, return top_n
    return dict(sorted(counts.items(), key=lambda x: -x[1])[:top_n])


def _is_boilerplate(term: str) -> bool:
    term_l = term.lower()
    if term_l in _BOILERPLATE_TOPICS:
        return True
    # Partial match against multi-word boilerplate phrases
    return any(bp in term_l or term_l in bp for bp in _BOILERPLATE_TOPICS)


def check_no_scope_creep(spec_text: str, pm_inputs: str) -> CheckResult:
    """Keyword-based heuristic: flag spec topics not present in PM inputs.

    Approach:
      1. Extract top keyword sets from pm_inputs and spec_text.
      2. Terms in spec but not in pm — minus boilerplate — are candidate anomalies.
      3. Compute per-section overlap to surface which sections diverge most.
      4. Flag the overall keyword overlap rate when it falls below the threshold.

    Confidence is MEDIUM because keyword overlap is a heuristic, not semantic
    analysis. False positives are expected for SAFe boilerplate (suppressed) and
    for synonyms. Use grounding_checker for semantic depth.
    """
    pm_keywords   = _extract_keywords(pm_inputs,  _TOP_PM_KEYWORDS)
    spec_keywords = _extract_keywords(spec_text,   _TOP_SPEC_KEYWORDS)

    pm_terms   = set(pm_keywords)
    spec_terms = set(spec_keywords)

    # Terms in spec not in pm, excluding boilerplate
    novel_terms = {
        t for t in spec_terms
        if t not in pm_terms and not _is_boilerplate(t)
    }

    # Overlap metric: fraction of spec keywords covered by pm keywords
    covered     = spec_terms - novel_terms
    overlap_pct = len(covered) / len(spec_terms) * 100 if spec_terms else 100.0

    findings: list[Finding] = []

    # Per-section analysis: find the section with the most novel terms
    section_novel: dict[str, list[str]] = {}
    for m in re.finditer(r"^##\s+(.+)$", spec_text, re.MULTILINE):
        sec_name  = m.group(1).strip()
        sec_start = m.end()
        next_sec  = re.search(r"^##\s+", spec_text[sec_start:], re.MULTILINE)
        sec_end   = sec_start + next_sec.start() if next_sec else len(spec_text)
        sec_text  = spec_text[sec_start:sec_end]

        sec_kw    = _extract_keywords(sec_text, 20)
        sec_novel = [
            t for t in sec_kw
            if t not in pm_terms and not _is_boilerplate(t)
        ]
        if sec_novel:
            section_novel[sec_name] = sec_novel

    # Emit a finding only when overlap is below threshold or a section has many novel terms
    if overlap_pct < _OVERLAP_WARN_THRESHOLD * 100:
        findings.append(Finding(
            check="scope_creep",
            severity="LOW",
            text=f"{overlap_pct:.1f}% keyword overlap",
            location="global",
            explanation=(
                f"Only {overlap_pct:.1f}% of spec keywords appear in PM inputs "
                f"(threshold: {int(_OVERLAP_WARN_THRESHOLD * 100)}%). "
                f"Novel terms: {', '.join(sorted(novel_terms)[:10])}."
            ),
            confidence="MEDIUM",
        ))

    # Flag individual sections where > 3 novel terms appear together
    for sec_name, novel in section_novel.items():
        if len(novel) > 3:
            findings.append(Finding(
                check="scope_creep",
                severity="LOW",
                text=f"{len(novel)} novel terms in section",
                location=sec_name,
                explanation=(
                    f"Section '{sec_name}' contains {len(novel)} keywords not found "
                    f"in PM inputs: {', '.join(novel[:8])}."
                ),
                confidence="MEDIUM",
            ))

    return CheckResult(
        name="scope_creep",
        passed=len(findings) == 0,
        findings=findings,
        note=(
            f"keyword overlap={overlap_pct:.1f}%  "
            f"novel_terms={len(novel_terms)}  "
            f"(heuristic — MEDIUM confidence)"
        ),
    )


# ---------------------------------------------------------------------------
# SAFETY_CHECKS registry
# ---------------------------------------------------------------------------

@dataclass
class SafetyCheckDef:
    name:        str
    description: str
    fn:          Callable   # (spec_text, pm_inputs) -> CheckResult


SAFETY_CHECKS: list[SafetyCheckDef] = [
    SafetyCheckDef(
        name="pii",
        description=(
            "Scan for email addresses, phone numbers, SSNs, and internal/admin URLs "
            "that were not present in PM inputs."
        ),
        fn=lambda spec, pm: check_no_pii(spec, pm),
    ),
    SafetyCheckDef(
        name="fabricated_metrics",
        description=(
            "Extract numeric claims (percentages, dollar amounts, dates, latencies, "
            "sprint references) from the spec and flag any that cannot be traced to "
            "PM inputs."
        ),
        fn=lambda spec, pm: check_no_fabricated_metrics(spec, pm),
    ),
    SafetyCheckDef(
        name="scope_creep",
        description=(
            "Keyword-overlap heuristic: identify major topics in the spec that have "
            "no basis in PM inputs. Heuristic — MEDIUM confidence. Use grounding_checker "
            "for semantic depth."
        ),
        fn=lambda spec, pm: check_no_scope_creep(spec, pm),
    ),
]


# ---------------------------------------------------------------------------
# run_all_safety_checks
# ---------------------------------------------------------------------------

def run_all_safety_checks(
    spec_text: str,
    pm_inputs: str,
) -> dict[str, Any]:
    """Run all deterministic safety checks and aggregate results.

    Args:
        spec_text:  Full generated SAFe Feature spec as markdown string.
        pm_inputs:  PM's section_answers rendered as a single string (same
                    format passed to check_grounding and the generator).

    Returns:
        {
            "passed":        bool,   # True only if ALL checks pass
            "findings":      [...],  # flat list of all Finding objects
            "check_results": {name: CheckResult},
            "summary": {
                "total_findings": int,
                "by_severity":    {"HIGH": int, "MEDIUM": int, "LOW": int},
                "by_check":       {name: int},
            },
        }
    """
    all_findings: list[Finding] = []
    check_results: dict[str, CheckResult] = {}

    for check_def in SAFETY_CHECKS:
        result = check_def.fn(spec_text, pm_inputs)
        check_results[check_def.name] = result
        all_findings.extend(result.findings)

    by_severity: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_check:    dict[str, int] = {}
    for f in all_findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_check[f.check]       = by_check.get(f.check, 0) + 1

    overall_passed = all(r.passed for r in check_results.values())

    return {
        "passed":        overall_passed,
        "findings":      all_findings,
        "check_results": check_results,
        "summary": {
            "total_findings": len(all_findings),
            "by_severity":    by_severity,
            "by_check":       by_check,
        },
    }


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_WIDTH = 72
_SEV_ICONS = {"HIGH": "[!]", "MEDIUM": "[~]", "LOW": "[-]"}


def _print_results(result: dict[str, Any], verbose: bool = True) -> None:
    print("=" * _WIDTH)
    print("  CONTENT SAFETY CHECKS")
    print("=" * _WIDTH)

    for name, cr in result["check_results"].items():
        status = "PASS" if cr.passed else "FAIL"
        print(f"\n  [{status}] {name.upper():<22}  {cr.note}")
        if verbose and cr.findings:
            for f in cr.findings:
                icon    = _SEV_ICONS.get(f.severity, "   ")
                conf    = f"  (confidence: {f.confidence})" if f.confidence != "HIGH" else ""
                print(f"    {icon} [{f.severity}]{conf}")
                print(f"         text:     {f.text[:80]}")
                print(f"         location: {f.location}")
                exp = textwrap.fill(
                    f.explanation, width=_WIDTH - 16,
                    initial_indent="         why:      ",
                    subsequent_indent="                   ",
                )
                print(exp)

    s = result["summary"]
    print(f"\n{'=' * _WIDTH}")
    overall = "PASS" if result["passed"] else "FAIL"
    print(
        f"  Overall: {overall}  —  "
        f"{s['total_findings']} finding(s)  "
        f"[HIGH={s['by_severity']['HIGH']}  "
        f"MEDIUM={s['by_severity']['MEDIUM']}  "
        f"LOW={s['by_severity']['LOW']}]"
    )
    print("=" * _WIDTH)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

_MOCK_PM_INPUTS = """\
## Strategy & Purpose
We need a buying group classification engine.
Tealium CDP, Adobe Target, and Marketo are our core systems.
TAL accounts: 48,000 priority accounts.
Classification confidence score: 0-100 per role.
Target: 80% TAL account coverage within 90 days.
Performance target: classification within 200ms for real-time Adobe Target use.
Q3 PI target. No hard deadline confirmed.

## Engineering & Technical Requirements
Architecture decision pending: real-time vs. 24-hour batch.
Confidence threshold: ≥60 for targeting activation.
"""

_MOCK_SPEC_CLEAN = """\
## Feature Title
Buying Group Identification Engine

## Description
This capability classifies web visitors into buying group roles.

## Solution Approach
The classification engine runs within Tealium CDP using configured signal rules.
Target Account List (TAL) accounts (48,000 accounts) receive priority scoring.
Confidence scores (0-100) per role are stored as visitor profile attributes.
Classification latency target: ≤200ms for real-time Adobe Target evaluation.

## Acceptance Criteria
- As a Marketing Ops user, I want classification events to fire via Tealium CDP
  Given a TAL account visitor arrives on servicenow.com
  When behavioral signals exceed the confidence threshold (≥60)
  Then the highest-confidence role is written to the Tealium visitor profile
  Priority: P1  Effort: M (5 story points)

## Dependencies
- Tealium CDP, Adobe Target, Marketo, AEM
- Q3 PI target with soft launch on limited TAL segment

## Out of Scope
- Real-time UI rendering
- WCAG accessibility requirements (backend capability)
"""

# Spec with deliberately planted PII and fabricated metrics
_MOCK_SPEC_WITH_VIOLATIONS = """\
## Feature Title
Buying Group Identification Engine

## Description
This capability classifies web visitors into buying group roles.
Contact the feature owner at john.smith@servicenow.com for questions.
Internal admin console: https://admin.internal/nav_to.do?sys_id=12345

## Solution Approach
The engine achieves 94.7% accuracy (industry-leading).
Budget allocated: $2,500,000 for implementation.
Target completion: 2026-09-30.
Classification latency target: ≤500ms (NOT from PM inputs — PM said 200ms).

## Engineering
Phone escalation line: (415) 555-1234
SSN for contractor vetting: 123-45-6789

## Acceptance Criteria
- Priority: P1  Effort: M (5 story points)

## Out of Scope
- Blockchain integration for immutable audit trail
- Machine learning retraining pipeline using PyTorch and MLflow
"""


def _smoke_test() -> None:
    failures: list[str] = []

    print("=" * _WIDTH)
    print("  CONTENT SAFETY — smoke test")
    print("=" * _WIDTH)

    # ── Test A: clean spec should pass all checks ─────────────────────────────
    print("\n[A] Clean spec (no violations expected)")
    result_clean = run_all_safety_checks(_MOCK_SPEC_CLEAN, _MOCK_PM_INPUTS)

    pii_clean = result_clean["check_results"]["pii"]
    ok = pii_clean.passed
    print(f"  [{'PASS' if ok else 'FAIL'}] pii check passes on clean spec")
    if not ok:
        failures.append(f"pii false-positive on clean spec: {[f.text for f in pii_clean.findings]}")

    met_clean = result_clean["check_results"]["fabricated_metrics"]
    # P1, 5, 60, 200ms, 48000, 0-100, Q3 all from PM inputs or boilerplate
    untraced = [f.text for f in met_clean.findings]
    # "90" appears in PM as "90 days" context; "80" in "80% TAL coverage"
    # Allow up to 1 untraced metric (story points like "5" should be allowlisted)
    ok = len(untraced) <= 1
    print(f"  [{'PASS' if ok else 'FAIL'}] fabricated_metrics: {len(untraced)} untraced (expected ≤1): {untraced}")
    if not ok:
        failures.append(f"fabricated_metrics false-positives: {untraced}")

    # ── Test B: spec with violations must catch all planted issues ─────────────
    print("\n[B] Spec with planted violations")
    result_viol = run_all_safety_checks(_MOCK_SPEC_WITH_VIOLATIONS, _MOCK_PM_INPUTS)

    # B1 — email caught
    pii_findings = result_viol["check_results"]["pii"].findings
    email_caught = any("john.smith@servicenow.com" in f.text for f in pii_findings)
    ok = email_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] email address detected: john.smith@servicenow.com")
    if not ok:
        failures.append("email not caught")

    # B2 — internal URL caught
    url_caught = any("internal" in f.text.lower() or "nav_to" in f.text.lower()
                     for f in pii_findings)
    ok = url_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] internal URL detected")
    if not ok:
        failures.append("internal URL not caught")

    # B3 — phone caught
    phone_caught = any("415" in f.text for f in pii_findings)
    ok = phone_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] phone number detected: (415) 555-1234")
    if not ok:
        failures.append("phone not caught")

    # B4 — SSN caught
    ssn_caught = any("123-45-6789" in f.text for f in pii_findings)
    ok = ssn_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] SSN detected: 123-45-6789")
    if not ok:
        failures.append("SSN not caught")

    # B5 — fabricated dollar amount caught
    met_findings = result_viol["check_results"]["fabricated_metrics"].findings
    dollar_caught = any("$" in f.text or "2,500,000" in f.text for f in met_findings)
    ok = dollar_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] fabricated dollar amount detected: $2,500,000")
    if not ok:
        failures.append("fabricated dollar amount not caught")

    # B6 — fabricated percentage caught (94.7% not in PM inputs)
    pct_caught = any("94.7" in f.text or "94" in f.text for f in met_findings)
    ok = pct_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] fabricated percentage detected: 94.7%")
    if not ok:
        failures.append("fabricated percentage not caught")

    # B7 — fabricated date caught
    date_caught = any("2026-09-30" in f.text for f in met_findings)
    ok = date_caught
    print(f"  [{'PASS' if ok else 'FAIL'}] fabricated date detected: 2026-09-30")
    if not ok:
        failures.append("fabricated date not caught")

    # B8 — overall result is FAIL
    ok = not result_viol["passed"]
    print(f"  [{'PASS' if ok else 'FAIL'}] overall result is FAIL (has violations)")
    if not ok:
        failures.append("overall result should be FAIL but was PASS")

    # ── Print findings for visual inspection ──────────────────────────────────
    print("\n--- Violations spec findings ---")
    _print_results(result_viol, verbose=True)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * _WIDTH)
    if failures:
        print(f"  RESULT: {len(failures)} failure(s)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: all checks passed")
    print("=" * _WIDTH)

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    _smoke_test()
