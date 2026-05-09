"""Smoke tests for GameSchema v0.1 validation."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game_schema import GAME_SCHEMA_VERSION, load_game_schema, validate_game_schema


EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "tiny_detective_case_v0_1.json"
MEDIUM_EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "medium_detective_case_v0_1.json"
JSON_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "game_schema_v0_1.schema.json"


def _load_example() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_json_schema_parses() -> None:
    payload = json.loads(JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert_true(payload["properties"]["schema_version"]["const"] == GAME_SCHEMA_VERSION, "schema const mismatch")
    print("[PASS] game schema json parses")


def test_tiny_example_validates() -> None:
    payload = load_game_schema(EXAMPLE_PATH)
    assert_true(payload["schema_version"] == GAME_SCHEMA_VERSION, "loaded wrong schema version")
    assert_true(payload["game_info"]["mode"] == "single_player_detective", "wrong game mode")
    print("[PASS] tiny detective example validates")


def test_medium_example_validates() -> None:
    payload = load_game_schema(MEDIUM_EXAMPLE_PATH)
    assert_true(payload["schema_version"] == GAME_SCHEMA_VERSION, "loaded wrong schema version")
    assert_true(len(payload["npc_characters"]) == 4, "medium case should have four NPCs")
    assert_true(len(payload["evidence"]) == 12, "medium case should have twelve evidence items")
    print("[PASS] medium detective example validates")


def test_unknown_reference_fails() -> None:
    payload = _load_example()
    payload["evidence"][0]["scene_id"] = "missing_scene"
    errors = validate_game_schema(payload)
    assert_true(any("missing_scene" in error for error in errors), "unknown scene reference was not reported")
    print("[PASS] unknown reference rejected")


def test_duplicate_ids_fail() -> None:
    payload = _load_example()
    payload["npc_characters"][1] = copy.deepcopy(payload["npc_characters"][0])
    errors = validate_game_schema(payload)
    assert_true(any("duplicates id" in error for error in errors), "duplicate character id was not reported")
    print("[PASS] duplicate ids rejected")


def test_required_accusation_fields_fail() -> None:
    payload = _load_example()
    payload["accusation_rules"]["required_fields"] = ["culprit", "method", "evidence_chain"]
    errors = validate_game_schema(payload)
    assert_true(any("motive" in error for error in errors), "missing motive required field was not reported")
    print("[PASS] accusation required fields checked")


def main() -> None:
    test_json_schema_parses()
    test_tiny_example_validates()
    test_medium_example_validates()
    test_unknown_reference_fails()
    test_duplicate_ids_fail()
    test_required_accusation_fields_fail()
    print("[PASS] GameSchema v0.1 smoke test suite")


if __name__ == "__main__":
    main()
