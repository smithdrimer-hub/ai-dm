"""Tests for the DetectiveGameEngine v0.1 offline auto-evaluator."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_detective_game_v0_1 import (
    MEDIUM_CASE_PATH,
    TINY_CASE_PATH,
    evaluate_case,
    lint_action_profiles,
)


EXPECTED_MEDIUM_RULES = {
    "arden_kai:arden_redirect_after_security_search",
    "arden_kai:arden_withdraw_after_rooftop_confront",
    "mira_sun:mira_stressed_after_security_search",
    "liam_chen:liam_irritated_after_fiber_found",
    "nova_park:nova_stressed_after_drone_found",
    "nova_park:nova_cooperative_after_drone_confront",
}
FORBIDDEN_REPORT_MARKERS = (
    "private_profile",
    "culprit_character_id",
    "action_profile",
    "directive",
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_no_report_leak(report: dict[str, Any], context: str) -> None:
    blob = json.dumps(report, ensure_ascii=False, sort_keys=True)
    for marker in FORBIDDEN_REPORT_MARKERS:
        assert_true(marker not in blob, f"{context}: report leaked marker {marker!r}")


def test_tiny_completion() -> None:
    report = evaluate_case(TINY_CASE_PATH, policy="completion")

    assert_true(report["summary"]["passed"], "tiny completion should pass")
    assert_true(report["summary"]["won"], "tiny completion should win")
    assert_equal(report["summary"]["score"], 10, "tiny completion should earn full score")
    assert_equal(report["summary"]["max_score"], 10, "tiny completion max score mismatch")
    assert_equal(report["npc_action_report"]["lint_errors"], [], "tiny lint errors mismatch")
    assert_no_report_leak(report, "tiny completion")
    print("[PASS] tiny completion auto eval")


def test_medium_completion() -> None:
    report = evaluate_case(MEDIUM_CASE_PATH, policy="completion")
    coverage = report["coverage"]
    fired_rules = set(report["npc_action_report"]["fired_rules"])

    assert_true(report["summary"]["passed"], "medium completion should pass")
    assert_true(report["summary"]["won"], "medium completion should win")
    assert_equal(report["summary"]["score"], 10, "medium completion should earn full score")
    assert_equal(report["summary"]["max_score"], 10, "medium completion max score mismatch")
    assert_true("evidence_rooftop_keycard" in coverage["evidence"]["covered_ids"], "medium should cover rooftop keycard")
    assert_true("truth_combo_access_route" in coverage["truth"]["covered_ids"], "medium should cover combo route truth")
    assert_true("lie_arden_no_rooftop" in coverage["lies"]["covered_ids"], "medium should break Arden lie")
    assert_true("clue_lifecycle" in coverage, "medium coverage should include clue lifecycle")
    assert_true("discoverable" in coverage["clue_lifecycle"]["covered_states"], "medium lifecycle should cover discoverable clues")
    assert_true("revealed" in coverage["clue_lifecycle"]["covered_states"], "medium lifecycle should cover revealed clues")
    assert_equal(report["npc_action_report"]["dead_rules"], [], "medium completion should cover NPC rules")
    assert_equal(report["npc_action_report"]["repeated_rules"], [], "medium completion repeated rules mismatch")
    assert_equal(report["npc_action_report"]["invalid_locations"], [], "medium completion invalid locations mismatch")
    assert_equal(fired_rules, EXPECTED_MEDIUM_RULES, "medium completion fired rules mismatch")
    assert_true(all(turn.get("snapshot_hash_after") for turn in report["turns"]), "turns should include snapshot hashes")
    assert_true(any("clue_state_changes" in turn["snapshot_delta"] for turn in report["turns"]), "turn deltas should include clue state changes")
    assert_true(any("new_npc_action_rules" in turn["snapshot_delta"] for turn in report["turns"]), "turn deltas should include NPC fired rules")
    assert_no_report_leak(report, "medium completion")
    print("[PASS] medium completion auto eval")


def test_medium_misled() -> None:
    report = evaluate_case(MEDIUM_CASE_PATH, policy="misled")

    assert_true(report["summary"]["passed"], "medium misled path should pass")
    assert_true(report["summary"]["game_over"], "misled path should end game")
    assert_true(not report["summary"]["won"], "misled path should lose")
    assert_equal(report["summary"]["wrong_accusations"], 1, "misled path wrong accusation count mismatch")
    assert_equal(report["summary"]["score"], 0, "misled path should score zero")
    assert_true(report["risk_flags"] == [] or all(flag.startswith("dead_npc_rule:") for flag in report["risk_flags"]), "misled risk flags should not block wrong path")
    assert_no_report_leak(report, "medium misled")
    print("[PASS] medium misled auto eval")


def test_medium_npc_autonomy() -> None:
    report = evaluate_case(MEDIUM_CASE_PATH, policy="npc-autonomy")
    fired_rules = set(report["npc_action_report"]["fired_rules"])
    runtime = report["npc_action_report"]["runtime_final_state"]

    assert_true(report["summary"]["passed"], "medium npc autonomy should pass")
    assert_equal(fired_rules, EXPECTED_MEDIUM_RULES, "medium npc autonomy fired rules mismatch")
    assert_equal(report["npc_action_report"]["dead_rules"], [], "medium npc autonomy dead rules mismatch")
    assert_equal(runtime["arden_kai"]["stance"], "cornered", "Arden final stance mismatch")
    assert_equal(runtime["nova_park"]["stance"], "cooperative", "Nova final stance mismatch")
    assert_true(report["npc_action_report"]["visible_events"], "NPC autonomy should produce visible events")
    assert_true(
        all("failed_conditions" in item for item in report["npc_action_report"]["action_history"]),
        "NPC action history should include failed_conditions for explanation",
    )
    assert_true(
        all("selected priority" in item.get("reason", "") for item in report["npc_action_report"]["action_history"]),
        "NPC action history should explain why rules were selected",
    )
    assert_no_report_leak(report, "medium npc-autonomy")
    print("[PASS] medium npc autonomy auto eval")


def test_action_profile_lint_for_medium() -> None:
    schema = json.loads(MEDIUM_CASE_PATH.read_text(encoding="utf-8"))
    errors = lint_action_profiles(schema)
    assert_equal(errors, [], "medium action profile lint should be clean")
    print("[PASS] medium action profile lint")


def main() -> None:
    test_tiny_completion()
    test_medium_completion()
    test_medium_misled()
    test_medium_npc_autonomy()
    test_action_profile_lint_for_medium()
    print("[PASS] DetectiveGameEngine auto-eval test suite")


if __name__ == "__main__":
    main()
