#!/usr/bin/env python3
# intake_copilot/run_scenario.py
# Development tool: run an interactive copilot conversation for a test scenario.
#
# Usage:
#   python intake_copilot/run_scenario.py --scenario se
#   python intake_copilot/run_scenario.py --scenario pmm
#   python intake_copilot/run_scenario.py --scenario eng
#
# Special commands during the conversation:
#   idk       — send "I don't know" as the stakeholder response
#   done      — trigger the summary step
#   status    — print full IntakeRecord state
#   recommend — print PM recommendation from ReadinessScorer
#   compare   — side-by-side diff vs. case input ground truth
#   quit      — exit

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

# Ensure the project root is on sys.path when the script is run directly
# (i.e. `python intake_copilot/run_scenario.py`) instead of as a module.
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from intake_copilot.agent import IntakeCopilot
from intake_copilot.models import ConversationState, FieldStatus, IntakeRecord
from intake_copilot.test_scenarios import SCENARIOS

# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_RED    = "\033[31m"
_BLUE   = "\033[34m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + _RESET


def _wrap(text: str, width: int = 80, indent: str = "  ") -> str:
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if line.strip() == "":
            wrapped.append("")
        else:
            wrapped.extend(
                textwrap.wrap(line, width=width, subsequent_indent=indent)
            )
    return "\n".join(wrapped)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_MAX_SCORE = 24   # 4 core×3 + 4 context×2 + 4 detail×1


def _status_bar(copilot: IntakeCopilot) -> str:
    record  = copilot.get_intake_record()
    manager = copilot._manager
    score   = record.readiness_score()
    state   = manager.state.value
    next_a  = manager.next_action(record)
    idk     = manager.consecutive_idk_count

    score_str = f"{score}/{_MAX_SCORE}"
    color = _GREEN if score >= 16 else (_YELLOW if score >= 10 else _RED)
    return (
        _c("[", _DIM)
        + "Readiness: "
        + _c(score_str, color, _BOLD)
        + " | State: "
        + _c(state, _CYAN)
        + " | Next: "
        + _c(next_a, _YELLOW)
        + " | IDK streak: "
        + _c(str(idk), _RED if idk >= 2 else _DIM)
        + _c("]", _DIM)
    )


def _print_copilot(text: str) -> None:
    print()
    print(_c("Copilot:", _BOLD, _BLUE))
    print(_wrap(text))
    print()


def _print_user(text: str) -> None:
    print(_c(f"  You: {text}", _DIM))


def _print_section(title: str) -> None:
    width = 60
    print()
    print(_c("─" * width, _DIM))
    print(_c(f"  {title}", _BOLD, _CYAN))
    print(_c("─" * width, _DIM))


def _print_status(copilot: IntakeCopilot) -> None:
    record  = copilot.get_intake_record()
    manager = copilot._manager

    _print_section("IntakeRecord Status")

    print(f"  Readiness score : {_c(record.readiness_score(), _BOLD)}/{_MAX_SCORE}")
    print(f"  Conv. state     : {_c(manager.state.value, _CYAN)}")
    print(f"  Next action     : {_c(manager.next_action(record), _YELLOW)}")
    print(f"  IDK streak      : {record.consecutive_idk_count if hasattr(record, 'consecutive_idk_count') else manager.consecutive_idk_count}")
    print(f"  Asked fields    : {sorted(manager.asked_fields) or '(none)'}")
    print()

    ft_val  = record.feature_type.value or "(unknown)"
    ft_conf = record.feature_type_confidence
    conf_color = _GREEN if ft_conf >= 0.7 else (_YELLOW if ft_conf >= 0.4 else _RED)
    print(f"  Feature type    : {_c(ft_val, _BOLD)}  confidence={_c(f'{ft_conf:.0%}', conf_color)}")
    print()

    print(_c("  Populated fields:", _BOLD))
    for f in record._all_fields():
        if f.is_populated():
            tier_tag = _c(f"[{f.tier}]", _DIM)
            print(f"    {_c('✓', _GREEN)} {f.name:<22} {tier_tag}  {f.value}")

    print()
    print(_c("  Gaps:", _BOLD))
    gaps = record.gap_inventory()
    for tier in ("core", "context", "detail"):
        for name in gaps[tier]:
            f = getattr(record, name)
            status_tag = (
                _c("[IDK]", _RED)
                if f.status == FieldStatus.UNKNOWN
                else _c("[unasked]", _DIM)
            )
            print(f"    {_c('✗', _RED)} {name:<22} {_c(f'[{tier}]', _DIM)}  {status_tag}")

    kb = record.knowledge_boundary()
    if kb:
        print()
        print(_c("  Knowledge boundary (stakeholder said IDK):", _BOLD))
        for name in kb:
            print(f"    {_c('?', _YELLOW)} {name}")
    print()


def _print_recommend(copilot: IntakeCopilot) -> None:
    rec = copilot.get_recommendation()
    _print_section("PM Recommendation")
    action_color = (
        _GREEN if rec["action"] == "accept"
        else _YELLOW if rec["action"] == "accept_with_caveats"
        else _RED
    )
    print(f"  Action   : {_c(rec['action'].upper(), action_color, _BOLD)}")
    print(f"  Rationale: {_wrap(rec['rationale'], indent='             ')}")
    if rec["gaps"]:
        print(f"  Gaps     : {', '.join(rec['gaps'])}")
    if rec["knowledge_boundary"]:
        print(f"  IDK      : {', '.join(rec['knowledge_boundary'])}")
    print()


def _parse_case_input(case_input: str) -> dict[str, str]:
    """
    Extract a rough field map from the structured CASE_INPUT text.
    Used only for the compare command.
    """
    section_map = {
        "feature description": "problem_statement",
        "target user":         "target_audience",
        "business justification": "business_objective",
        "success metrics":     "success_metrics",
        "constraints":         "dependencies",
        "scope boundaries":    "scope_exclusions",
    }
    result: dict[str, str] = {}

    # Feature type line
    m = re.search(r"Feature type:\s*(\w+)", case_input, re.IGNORECASE)
    if m:
        result["feature_type"] = m.group(1).strip()

    # Section blocks — each starts with a labelled paragraph
    blocks = re.split(r"\n(?=[A-Z][a-z])", case_input)
    for block in blocks:
        first_line, _, rest = block.partition("\n")
        label = first_line.rstrip(":").strip().lower()
        content = (first_line + "\n" + rest).strip()
        if ":" in first_line:
            content = first_line.split(":", 1)[1].strip() + (" " + rest.strip() if rest.strip() else "")

        for key, field_name in section_map.items():
            if key in label:
                result[field_name] = content.strip()
                break

    return result


def _print_compare(copilot: IntakeCopilot, case_input: str) -> None:
    _print_section("Field Comparison: Copilot vs. Ground Truth")

    record      = copilot.get_intake_record()
    ground_truth = _parse_case_input(case_input)

    all_fields = record._all_fields()
    col_w = 26

    header = (
        _c(f"  {'FIELD':<22}", _BOLD)
        + _c(f"  {'COPILOT':<{col_w}}", _BOLD, _CYAN)
        + _c(f"  {'GROUND TRUTH':<{col_w}}", _BOLD, _GREEN)
        + _c("  MATCH?", _BOLD)
    )
    print(header)
    print(_c("  " + "─" * (22 + col_w * 2 + 20), _DIM))

    for f in all_fields:
        copilot_val = (f.value or "(IDK)") if f.is_populated() else (
            "(IDK)" if f.status == FieldStatus.UNKNOWN else "(missing)"
        )
        gt_val = ground_truth.get(f.name, "(not in case)")

        # Truncate for display
        def _trunc(s: str, n: int = col_w - 2) -> str:
            return (s[:n] + "…") if len(s) > n else s

        copilot_display = _trunc(copilot_val)
        gt_display      = _trunc(gt_val)

        populated = f.is_populated()
        in_gt     = f.name in ground_truth

        if populated and in_gt:
            match = _c("✓ captured", _GREEN)
        elif not populated and in_gt:
            match = _c("✗ missed", _RED)
        elif populated and not in_gt:
            match = _c("+ extra", _YELLOW)
        else:
            match = _c("– n/a", _DIM)

        tier_badge = _c(f"[{f.tier[0]}]", _DIM)
        print(
            f"  {f.name:<22}"
            f"  {_c(copilot_display, _CYAN):<{col_w + len(_CYAN) + len(_RESET)}}"
            f"  {_c(gt_display, _GREEN):<{col_w + len(_GREEN) + len(_RESET)}}"
            f"  {tier_badge} {match}"
        )

    # Summary counts
    captured = sum(
        1 for f in all_fields
        if f.is_populated() and f.name in ground_truth
    )
    total_gt = len(ground_truth)
    print()
    print(f"  Captured {_c(captured, _GREEN, _BOLD)} of {_c(total_gt, _BOLD)} ground-truth fields")
    print()


def _print_summary(copilot: IntakeCopilot) -> None:
    summary = copilot.get_summary()
    _print_section("Intake Summary (plain language)")
    for key, val in summary.items():
        if key == "knowledge_boundary":
            if val:
                print(f"  {'Product team to determine':<28}: {', '.join(val)}")
        else:
            label = key.replace("_", " ").title()
            print(f"  {label:<28}: {_wrap(val, width=60, indent=' ' * 32)}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive intake copilot test runner"
    )
    parser.add_argument(
        "--scenario", "-s",
        choices=["se", "pmm", "eng"],
        required=True,
        help="Which test scenario to load (se, pmm, eng)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print raw API messages and response blocks each turn",
    )
    args = parser.parse_args()

    scenario_map = {"se": 0, "pmm": 1, "eng": 2}
    scenario = SCENARIOS[scenario_map[args.scenario]]

    print()
    print(_c("═" * 60, _DIM))
    print(_c(f"  Intake Copilot — {scenario['name']}", _BOLD))
    print(_c(f"  Persona: {scenario['persona']}  |  Expected type: {scenario['expected_type']}", _DIM))
    print(_c("═" * 60, _DIM))
    print()
    print(_c("  Commands: idk · done · status · recommend · compare · quit", _DIM))
    print()

    copilot = IntakeCopilot(debug=args.debug)

    # Greeting
    greeting = copilot.greeting()
    _print_copilot(greeting)
    print(_status_bar(copilot))

    # First turn: feed the raw input automatically
    print()
    print(_c("  [Auto-feeding raw input as first stakeholder message]", _DIM))
    _print_user(scenario["raw_input"])
    print()

    try:
        response = copilot.process_turn(scenario["raw_input"])
    except Exception as exc:
        print(_c(f"  [API error on first turn: {exc}]", _RED))
        sys.exit(1)

    _print_copilot(response)
    print(_status_bar(copilot))

    # Interactive loop
    while True:
        print()
        try:
            raw = input(_c("  Stakeholder> ", _BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_c("  [Exiting]", _DIM))
            break

        if not raw:
            continue

        # Special commands
        if raw.lower() == "quit":
            print(_c("  [Exiting]", _DIM))
            break

        if raw.lower() == "idk":
            user_message = "I don't know"
            _print_user(user_message)
        elif raw.lower() == "done":
            _print_summary(copilot)
            _print_recommend(copilot)
            continue
        elif raw.lower() == "status":
            _print_status(copilot)
            continue
        elif raw.lower() == "recommend":
            _print_recommend(copilot)
            continue
        elif raw.lower() == "compare":
            _print_compare(copilot, scenario["case_input"])
            continue
        else:
            user_message = raw
            _print_user(user_message)

        print()
        try:
            response = copilot.process_turn(user_message)
        except Exception as exc:
            print(_c(f"  [API error: {exc}]", _RED))
            continue

        _print_copilot(response)
        print(_status_bar(copilot))

        # Auto-prompt summary when the manager moves to summarizing state
        if copilot._manager.state == ConversationState.SUMMARIZING:
            print()
            print(_c("  [Conversation manager reached SUMMARIZING state — type 'done' to see the full summary]", _DIM))


if __name__ == "__main__":
    main()
