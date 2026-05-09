"""Replay test runner for DetectiveGameEngine v0.1."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine


REPLAY_PATH = PROJECT_ROOT / "scripts" / "playthroughs" / "tiny_detective_game_replay.json"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_replay(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise AssertionError(f"{context}: expected {expected!r}, got {actual!r}")


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


def run_replay(replay: dict[str, Any]) -> None:
    engine = DetectiveGameEngine(resolve_path(replay["schema_path"]))
    for index, step in enumerate(replay.get("steps", []), start=1):
        context = step.get("name") or f"step_{index}"
        result = engine.handle_command_result(step["command"])
        snapshot = engine.get_progress_snapshot()

        if "expect_code" in step:
            assert_equal(result.code, step["expect_code"], f"{context}/code")
        if "expect_ok" in step:
            assert_equal(result.ok, step["expect_ok"], f"{context}/ok")
        if "expect_phase" in step:
            assert_equal(result.phase_id, step["expect_phase"], f"{context}/phase")
            assert_equal(snapshot["current_phase_id"], step["expect_phase"], f"{context}/snapshot/current_phase_id")
        for field_name in ("new_evidence_ids", "new_truth_ids", "new_broken_lie_ids", "new_unlocked_scene_ids"):
            expected_key = f"expect_{field_name}"
            if expected_key in step:
                assert_equal(getattr(result, field_name), step[expected_key], f"{context}/{field_name}")
        assert_snapshot(snapshot, step.get("expect_snapshot", {}), context)
        assert_snapshot_contains(snapshot, step.get("expect_snapshot_contains", {}), context)
        assert_equal(snapshot["last_action_result"]["code"], result.code, f"{context}/last_action_result")
        print(f"[PASS] {context}")


def main() -> None:
    replay = load_replay(REPLAY_PATH)
    run_replay(replay)
    print("[PASS] DetectiveGameEngine replay suite")


if __name__ == "__main__":
    main()
