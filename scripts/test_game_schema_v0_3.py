"""Smoke tests for GameSchema v0.3 validation."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game_schema_v0_3 import (
    GAME_SCHEMA_VERSION,
    build_npc_author_questions,
    load_game_schema_v0_3,
    validate_game_schema_v0_3,
)


EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "medium_detective_case_v0_3.json"
JSON_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "game_schema_v0_3.schema.json"


def _load_example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_has_error(errors: list[str], fragment: str, context: str) -> None:
    if not any(fragment in error for error in errors):
        raise AssertionError(f"{context}: expected error containing {fragment!r}, got {errors!r}")


def test_json_schema_parses() -> None:
    payload = json.loads(JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert_true(payload["properties"]["schema_version"]["const"] == GAME_SCHEMA_VERSION, "schema const mismatch")
    assert_true("author_questions" in payload["properties"]["review"]["required"], "review.author_questions missing")
    print("[PASS] game schema v0.3 json parses")


def test_medium_v0_3_example_validates() -> None:
    payload = load_game_schema_v0_3(EXAMPLE_PATH)
    assert_true(payload["schema_version"] == GAME_SCHEMA_VERSION, "loaded wrong schema version")
    assert_true(payload["game_info"]["id"] == "medium_detective_case_v0_3", "wrong medium v0.3 id")
    assert_true("ending_rules" in payload, "v0.3 must include ending_rules")
    assert_true(payload["review"]["author_questions"] == [], "complete medium fixture should not ask author questions")
    print("[PASS] medium v0.3 detective example validates")


def test_dangling_reference_fails() -> None:
    payload = _load_example()
    payload["evidence"][0]["lifecycle"]["discoverable_when"] = {"discovered_evidence_ids_all": ["missing_evidence"]}
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "missing_evidence", "dangling reference")
    print("[PASS] v0.3 dangling reference rejected")


def test_critical_clue_unreachable_fails() -> None:
    payload = _load_example()
    dead_scene = copy.deepcopy(payload["scenes"][0])
    dead_scene.update(
        {
            "scene_id": "scene_dead_end",
            "title": "Dead End",
            "initially_unlocked": False,
            "evidence_ids": ["evidence_cup_residue"],
            "npc_ids": [],
            "entry_condition": {},
            "exit_condition": {},
        }
    )
    payload["scenes"].append(dead_scene)
    for item in payload["evidence"]:
        if item["evidence_id"] == "evidence_cup_residue":
            item["scene_id"] = "scene_dead_end"
            item["source_scene_id"] = "scene_dead_end"
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "critical clue unreachable", "critical clue reachability")
    print("[PASS] v0.3 critical clue reachability checked")


def test_phase_without_exit_fails() -> None:
    payload = _load_example()
    for phase in payload["phases"]:
        if phase["phase_id"] == "phase_investigation":
            phase["exit_condition"] = {}
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "exit_condition is required", "phase exit condition")
    print("[PASS] v0.3 phase exit checked")


def test_truth_node_without_evidence_fails() -> None:
    payload = _load_example()
    node = payload["truth_model"]["truth_nodes"][0]
    node["related_evidence_ids"] = []
    node["required_clue_ids"] = []
    node["revealed_by_default"] = False
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "truth_node lacks evidence", "truth evidence linkage")
    print("[PASS] v0.3 truth evidence linkage checked")


def test_incomplete_ending_rule_fails() -> None:
    payload = _load_example()
    for item in payload["ending_rules"]["scoring_items"]:
        if item["field_id"] == "evidence_chain":
            item["expected_truth_ids"] = []
            item["expected_evidence_ids"] = []
            item["expected_lie_ids"] = []
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "ending_rule incomplete", "ending rule completeness")
    print("[PASS] v0.3 ending rule completeness checked")


def test_spoiler_boundary_fails() -> None:
    payload = _load_example()
    payload["npc_characters"][0]["conversation_rules"]["forbidden_truth_ids"] = []
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "missing culprit spoiler truth ids", "NPC spoiler boundary")
    print("[PASS] v0.3 NPC spoiler boundary checked")


def test_npc_profile_gaps_require_author_questions() -> None:
    payload = _load_example()
    npc = payload["npc_characters"][0]
    npc["public_profile"] = "TBD"
    npc["private_profile"] = "needs manual review"
    npc["initial_attitude"] = ""
    npc["conversation_rules"]["fallback_style"] = ""
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "review.author_questions item 'npc:arden_kai:public_identity'", "NPC public identity gap")
    assert_has_error(errors, "review.author_questions item 'npc:arden_kai:private_pressure'", "NPC private pressure gap")
    assert_has_error(errors, "review.author_questions item 'npc:arden_kai:voice_and_attitude'", "NPC voice gap")

    questions = build_npc_author_questions(payload)
    payload["review"]["author_questions"] = questions
    errors = validate_game_schema_v0_3(payload)
    assert_true(
        not any("NPC profile incomplete" in error for error in errors),
        f"generated author questions should cover NPC profile gaps, got {errors!r}",
    )
    question_text = "\n".join(item["question"] for item in questions)
    assert_true("action_profile" not in question_text, "author question should not expose schema jargon")
    assert_true("字段" not in question_text, "author question should not sound like a form field request")
    assert_true("Arden Kai" in question_text, "author question should name the NPC clearly")
    print("[PASS] v0.3 NPC profile gaps generate friendly author questions")


def test_author_question_technical_wording_fails() -> None:
    payload = _load_example()
    payload["review"]["author_questions"] = [
        {
            "question_id": "npc:arden_kai:public_identity",
            "target_type": "npc_character",
            "target_id": "arden_kai",
            "topic": "public_identity",
            "question": "Please fill public_profile and action_profile for this NPC.",
            "why": "test technical wording",
            "blocking": True,
        }
    ]
    errors = validate_game_schema_v0_3(payload)
    assert_has_error(errors, "uses technical wording", "author question plain language")
    print("[PASS] v0.3 author questions reject technical wording")


def main() -> None:
    test_json_schema_parses()
    test_medium_v0_3_example_validates()
    test_dangling_reference_fails()
    test_critical_clue_unreachable_fails()
    test_phase_without_exit_fails()
    test_truth_node_without_evidence_fails()
    test_incomplete_ending_rule_fails()
    test_spoiler_boundary_fails()
    test_npc_profile_gaps_require_author_questions()
    test_author_question_technical_wording_fails()
    print("[PASS] GameSchema v0.3 smoke test suite")


if __name__ == "__main__":
    main()
