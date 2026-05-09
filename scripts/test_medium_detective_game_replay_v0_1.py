"""Replay tests for the medium DetectiveGameEngine v0.1 case."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine


REPLAY_PATH = PROJECT_ROOT / "scripts" / "playthroughs" / "medium_detective_game_replay.json"


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


def load_replay(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def assert_npc_events(result, expected_items: list[str], context: str) -> None:
    event_text = "\n".join(event.get("text", "") for event in result.data.get("npc_events", []))
    for expected in expected_items:
        assert_true(expected in event_text, f"{context}/npc_events: missing {expected!r} from {event_text!r}")


def assert_npc_runtime(snapshot: dict[str, Any], expected: dict[str, dict[str, Any]], context: str) -> None:
    runtime = snapshot.get("npc_runtime_state", {})
    assert_true(isinstance(runtime, dict), f"{context}/npc_runtime_state: expected dict")
    for character_id, fields in expected.items():
        state = runtime.get(character_id)
        assert_true(isinstance(state, dict), f"{context}/npc_runtime_state/{character_id}: missing state")
        for key, expected_value in fields.items():
            assert_equal(state.get(key), expected_value, f"{context}/npc_runtime_state/{character_id}/{key}")


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
        assert_npc_events(result, step.get("expect_npc_event_text_contains", []), context)
        assert_npc_runtime(snapshot, step.get("expect_npc_runtime", {}), context)
        if "expect_accusation" in step:
            assert_accusation(snapshot, step["expect_accusation"], context)
        assert_equal(snapshot["last_action_result"]["code"], result.code, f"{context}/last_action_result")
        print(f"[PASS] {context}")


def run_replay(replay: dict[str, Any]) -> None:
    sessions = replay.get("sessions", [])
    assert_true(isinstance(sessions, list) and sessions, "replay must contain sessions")
    for session in sessions:
        run_session(session)


def main() -> None:
    run_replay(load_replay(REPLAY_PATH))
    print("[PASS] Medium DetectiveGameEngine replay suite")


if __name__ == "__main__":
    main()
