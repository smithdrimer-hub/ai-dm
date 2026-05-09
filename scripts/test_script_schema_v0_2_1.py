r"""Basic ScriptSchema v0.2.1 validation tests.

Run with:
    python -B .\scripts\test_script_schema_v0_2_1.py

These tests deliberately use only stdlib and assert statements so they can run
on a clean local checkout without API keys or pytest.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from script_schema import SchemaValidationError, load_script_schema, validate_script_schema  # noqa: E402


SCHEMA_FILE = ROOT / "schemas" / "script_schema_v0_2_1.schema.json"
FIXED_EXAMPLE = ROOT / "scripts" / "schema_examples" / "fixed_truth_minimal.json"
EMERGENT_EXAMPLE = ROOT / "scripts" / "schema_examples" / "emergent_resolution_minimal.json"
MONSTERS_DEMO = ROOT / "stories" / "Monsters Halloween Night_China" / "script_schema_v0_2_1.json"
SECOND_SAMPLE = ROOT / "stories" / "second_sample" / "script_schema_v0_2_1.json"


def pass_msg(name: str) -> None:
    print(f"[PASS] {name}")


def assert_valid(path: Path) -> dict:
    try:
        data = load_script_schema(path)
    except SchemaValidationError as exc:
        raise AssertionError(f"{path} should validate, got:\n" + "\n".join(exc.errors)) from exc
    assert data["schema_version"] == "0.2.1", f"{path} schema_version mismatch"
    return data


def assert_invalid(data: dict, expected_fragment: str) -> None:
    errors = validate_script_schema(data)
    assert errors, "document should be invalid"
    joined = "\n".join(errors)
    assert expected_fragment in joined, f"expected {expected_fragment!r} in errors:\n{joined}"


def test_schema_file_is_json() -> None:
    with SCHEMA_FILE.open("r", encoding="utf-8") as handle:
        schema_doc = json.load(handle)
    assert schema_doc["$id"].endswith("script_schema_v0_2_1.schema.json")
    assert schema_doc["properties"]["schema_version"]["const"] == "0.2.1"
    pass_msg("schema json parses")


def test_examples_validate() -> tuple[dict, dict]:
    fixed = assert_valid(FIXED_EXAMPLE)
    emergent = assert_valid(EMERGENT_EXAMPLE)
    assert fixed["script_info"]["game_mode"] == "fixed_truth"
    assert emergent["script_info"]["game_mode"] == "emergent_resolution"
    assert "final_reveal_sequence" not in fixed["truth_model"]
    assert "final_reveal_sequence" in fixed["ending_rules"]
    pass_msg("minimal examples validate")
    return fixed, emergent


def test_emergent_action_rules_are_expressive(emergent: dict) -> None:
    action_rules = emergent["action_rules"]
    assert action_rules["enabled"] is True
    assert action_rules["resolution_order"].index("GUARD") < action_rules["resolution_order"].index("MURDER")
    guard_blocks = [
        rule for rule in action_rules["blocking_rules"]
        if rule["blocked_action_type"] == "MURDER" and rule["blocked_by_action_type"] == "GUARD"
    ]
    assert guard_blocks, "emergent mock should express GUARD blocking MURDER"
    assert guard_blocks[0]["minimum_block_count"] == 2
    assert any(action["changes_voting_eligibility"] for action in action_rules["action_types"])
    pass_msg("emergent action skeleton validates")


def test_monsters_demo_migration() -> dict:
    data = assert_valid(MONSTERS_DEMO)
    assert data["script_info"]["id"] == "monsters_halloween_night_cn"
    assert data["script_info"]["game_mode"] == "fixed_truth"
    assert data["player_config"]["mode"] == "all_role_players"
    assert {slot["character_id"] for slot in data["player_config"]["role_player_slots"]} == {
        "wolf",
        "witch",
        "vampire",
        "mummy",
    }
    assert "final_reveal_sequence" not in data["truth_model"]
    assert len(data["ending_rules"]["final_reveal_sequence"]) >= 3
    clue_2 = next(clue for clue in data["clues"] if clue["clue_id"] == "clue_2")
    assert clue_2["asset_refs"] == ["asset_clue_2"]
    key_spoiler = next(item for item in data["forbidden_spoilers"] if item["spoiler_id"] == "spoiler_key_before_clue_2")
    assert key_spoiler["allowed_after_reveal_rule"] == "reveal_clue_2"
    pass_msg("monsters demo migration validates")
    return data


def test_second_sample_schema() -> dict:
    data = assert_valid(SECOND_SAMPLE)
    assert data["script_info"]["id"] == "second_sample"
    assert data["script_info"]["title"] == "The Business of Murder"
    assert len(data["clues"]) >= 4
    assert data["clues"][0]["asset_refs"] == ["asset_clue_1"]
    assert "final_reveal_sequence" not in data["truth_model"]
    assert data["ending_rules"]["final_reveal_sequence"]
    pass_msg("second sample schema validates")
    return data


def test_negative_validation_cases(fixed: dict) -> None:
    with_truth_sequence = copy.deepcopy(fixed)
    with_truth_sequence["truth_model"]["final_reveal_sequence"] = []
    assert_invalid(with_truth_sequence, "$.truth_model.final_reveal_sequence is not allowed")

    wrong_truth_type = copy.deepcopy(fixed)
    wrong_truth_type["truth_model"]["truth_type"] = "emergent"
    assert_invalid(wrong_truth_type, "$.truth_model.truth_type must be 'fixed'")

    missing_group_recipients = copy.deepcopy(fixed)
    missing_group_recipients["role_packets"][0]["visibility"] = "group_limited"
    missing_group_recipients["role_packets"][0]["recipients"] = []
    assert_invalid(missing_group_recipients, "recipients is required for group_limited")

    bad_asset_ref = copy.deepcopy(fixed)
    bad_asset_ref["clues"][0]["asset_refs"] = ["missing_asset"]
    assert_invalid(bad_asset_ref, "asset_refs references unknown asset")

    pass_msg("negative validator cases")


def main() -> None:
    test_schema_file_is_json()
    fixed, emergent = test_examples_validate()
    test_emergent_action_rules_are_expressive(emergent)
    test_monsters_demo_migration()
    test_second_sample_schema()
    test_negative_validation_cases(fixed)
    print("[PASS] ScriptSchema v0.2.1 basic test suite")


if __name__ == "__main__":
    main()
