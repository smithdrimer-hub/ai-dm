"""Replay tests for the medium DetectiveGameEngine v0.3 case."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine
from scripts.evaluate_detective_game_v0_1 import evaluate_case


REPLAY_PATH = PROJECT_ROOT / "scripts" / "playthroughs" / "medium_detective_game_v0_3_replay.json"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def assert_contains(actual: list[Any], expected_items: list[Any], context: str) -> None:
    missing = [item for item in expected_items if item not in actual]
    if missing:
        raise AssertionError(f"{context}: missing {missing!r} from {actual!r}")


def assert_snapshot(snapshot: dict[str, Any], expected: dict[str, Any], context: str) -> None:
    for key, expected_value in expected.items():
        assert_equal(snapshot.get(key), expected_value, f"{context}/snapshot/{key}")


def assert_snapshot_contains(snapshot: dict[str, Any], expected: dict[str, list[Any]], context: str) -> None:
    for key, expected_items in expected.items():
        value = snapshot.get(key)
        assert_true(isinstance(value, list), f"{context}/snapshot/{key}: expected list, got {type(value).__name__}")
        assert_contains(value, expected_items, f"{context}/snapshot/{key}")


def assert_clue_states(snapshot: dict[str, Any], expected: dict[str, str], context: str) -> None:
    states = snapshot.get("clue_state_by_id", {})
    assert_true(isinstance(states, dict), f"{context}/clue_state_by_id: expected dict")
    for clue_id, expected_state in expected.items():
        assert_equal(states.get(clue_id), expected_state, f"{context}/clue_state_by_id/{clue_id}")


def assert_accusation(snapshot: dict[str, Any], expected: dict[str, Any], context: str) -> None:
    accusation = snapshot.get("latest_accusation_result")
    assert_true(isinstance(accusation, dict), f"{context}/accusation: missing accusation result")
    for key, expected_value in expected.items():
        assert_equal(accusation.get(key), expected_value, f"{context}/accusation/{key}")


def assert_result_lists(result, step: dict[str, Any], context: str) -> None:
    for field_name in ("new_evidence_ids", "new_truth_ids", "new_broken_lie_ids", "new_unlocked_scene_ids"):
        expected_key = f"expect_{field_name}"
        if expected_key in step:
            assert_equal(getattr(result, field_name), step[expected_key], f"{context}/{field_name}")


def run_session(session: dict[str, Any]) -> None:
    engine = DetectiveGameEngine(resolve_path(session["schema_path"]))
    session_name = session.get("name", "session")
    for index, step in enumerate(session.get("steps", []), start=1):
        context = f"{session_name}/{step.get('name') or f'step_{index}'}"
        result = engine.handle_command_result(step["command"])
        snapshot = engine.get_progress_snapshot()

        if "expect_code" in step:
            assert_equal(result.code, step["expect_code"], f"{context}/code")
        if "expect_ok" in step:
            assert_equal(result.ok, step["expect_ok"], f"{context}/ok")
        if "expect_phase" in step:
            assert_equal(result.phase_id, step["expect_phase"], f"{context}/phase")
            assert_equal(snapshot["current_phase_id"], step["expect_phase"], f"{context}/snapshot/current_phase_id")
        assert_result_lists(result, step, context)
        assert_snapshot(snapshot, step.get("expect_snapshot", {}), context)
        assert_snapshot_contains(snapshot, step.get("expect_snapshot_contains", {}), context)
        assert_clue_states(snapshot, step.get("expect_clue_state_by_id", {}), context)
        if "expect_accusation" in step:
            assert_accusation(snapshot, step["expect_accusation"], context)
        assert_equal(snapshot["last_action_result"]["code"], result.code, f"{context}/last_action_result")
        print(f"[PASS] {context}")


def test_replay() -> None:
    replay = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
    sessions = replay.get("sessions", [])
    assert_true(isinstance(sessions, list) and sessions, "replay must contain sessions")
    for session in sessions:
        run_session(session)
    print("[PASS] Medium DetectiveGameEngine v0.3 replay suite")


def test_auto_eval_completion() -> None:
    report = evaluate_case(PROJECT_ROOT / "scripts" / "schema_examples" / "medium_detective_case_v0_3.json", policy="completion")
    assert_true(report["summary"]["passed"], "v0.3 completion auto eval should pass")
    assert_equal(report["summary"]["score"], 10, "v0.3 completion score mismatch")
    assert_true("truth_culprit_arden" in report["coverage"]["truth"]["covered_ids"], "v0.3 should unlock culprit truth for full solution")
    assert_equal(report["npc_action_report"]["dead_rules"], [], "v0.3 completion should cover NPC rules")
    print("[PASS] Medium DetectiveGameEngine v0.3 auto eval")


def main() -> None:
    test_replay()
    test_auto_eval_completion()


if __name__ == "__main__":
    main()
