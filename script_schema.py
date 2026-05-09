"""ScriptSchema v0.2.1 loader and lightweight validator.

This module intentionally avoids third-party JSON Schema dependencies. The
validator covers the references and safety invariants the DM runtime will need
before ScriptSchema is wired into game execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.2.1"

GAME_MODES = {"fixed_truth", "emergent_resolution", "hybrid"}
TRUTH_TYPES_BY_MODE = {
    "fixed_truth": "fixed",
    "emergent_resolution": "emergent",
    "hybrid": "hybrid",
}
PHASE_TYPES = {
    "intro",
    "free_discussion",
    "search",
    "discovery",
    "examination",
    "accusation",
    "resolution",
    "confession_chain",
    "recap",
}
VISIBILITIES = {"hidden", "private", "public", "dm_only", "role_private", "group_limited"}
PACKET_VISIBILITIES = {"private", "public", "dm_only", "group_limited"}
REVEAL_INSTRUCTIONS = {
    "keep_secret",
    "must_read_aloud",
    "reveal_only_when_challenged",
    "reveal_at_phase_start",
    "may_share",
}
CLUE_TYPES = {"text", "letter", "newspaper", "map", "object", "testimony", "rule_extract"}
ASSET_TYPES = {"image", "audio", "document", "handout", "map", "other"}
REVEAL_TARGET_TYPES = {"clue", "role_packet", "public_material", "asset", "truth_node", "form"}
REVEAL_TRIGGERS = {
    "phase_start",
    "phase_end",
    "timed",
    "dm_manual",
    "player_action",
    "form_submit",
    "challenge",
    "code_word",
}
FORM_TYPES = {
    "declaration_card",
    "accusation_sheet",
    "vote_card",
    "action_card",
    "resolution_card",
    "custom",
}
FIELD_TYPES = {"character_ref", "action_type", "free_text", "clue_ref", "choice", "boolean"}
ACTION_TYPES = {"MURDER", "GUARD", "INVESTIGATE", "DECLARE", "VOTE", "ACCUSE", "CUSTOM"}
HINT_LEVELS = {"L1", "L2", "L3"}
SPOILER_CHECK_MODES = {"strict", "phase_limited", "off"}

TOP_LEVEL_REQUIRED = (
    "schema_version",
    "script_info",
    "license_info",
    "public_materials",
    "player_config",
    "cast",
    "phases",
    "role_packets",
    "clues",
    "assets",
    "reveal_rules",
    "truth_model",
    "forbidden_spoilers",
    "action_rules",
    "forms",
    "ending_rules",
    "scoring_rules",
    "hint_rules",
)


class SchemaValidationError(ValueError):
    """Raised when a ScriptSchema document fails validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def load_script_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate a ScriptSchema JSON file."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    errors = validate_script_schema(data)
    if errors:
        raise SchemaValidationError(errors)
    return data


def validate_script_schema(data: Any) -> list[str]:
    """Return validation errors for a ScriptSchema v0.2.1 document."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["schema root must be an object"]

    _require_keys(data, TOP_LEVEL_REQUIRED, "$", errors)
    if errors:
        return errors

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {SCHEMA_VERSION!r}")

    script_info = _object(data, "script_info", "$", errors)
    game_mode = script_info.get("game_mode")
    _enum(game_mode, GAME_MODES, "$.script_info.game_mode", errors)

    cast = _list(data, "cast", "$", errors)
    phases = _list(data, "phases", "$", errors)
    role_packets = _list(data, "role_packets", "$", errors)
    clues = _list(data, "clues", "$", errors)
    assets = _list(data, "assets", "$", errors)
    reveal_rules = _list(data, "reveal_rules", "$", errors)
    forms = _list(data, "forms", "$", errors)

    character_ids = _validate_cast(cast, errors)
    phase_ids = _validate_phases(phases, errors)
    packet_ids = _validate_role_packets(role_packets, character_ids, phase_ids, errors)
    clue_ids = _validate_clues(clues, assets, character_ids, phase_ids, errors)
    asset_ids = _validate_assets(assets, clue_ids, errors)
    form_ids = _validate_forms(forms, phase_ids, errors)
    truth_node_ids = _validate_truth_model(data, game_mode, clue_ids, character_ids, errors)
    reveal_rule_ids = _validate_reveal_rules(
        reveal_rules,
        phase_ids,
        clue_ids,
        packet_ids,
        asset_ids,
        form_ids,
        truth_node_ids,
        errors,
    )
    _validate_player_config(data, character_ids, errors)
    _validate_forbidden_spoilers(data, reveal_rule_ids, phase_ids, errors)
    action_type_values = _validate_action_rules(data, form_ids, errors)
    _validate_ending_rules(data, truth_node_ids, clue_ids, packet_ids, asset_ids, errors)
    _validate_scoring_rules(data, character_ids, errors)
    _validate_hint_rules(data, phase_ids, clue_ids, truth_node_ids, errors)
    _validate_action_form_refs(action_type_values, forms, errors)

    return errors


def _validate_cast(cast: list[Any], errors: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(cast):
        path = f"$.cast[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("character_id", "display_name", "public_profile", "goals", "relationships", "secrets"), path, errors)
        character_id = item.get("character_id")
        if _nonempty_string(character_id, f"{path}.character_id", errors):
            _unique_add(ids, character_id, f"{path}.character_id", errors)
        for rel_index, rel in enumerate(item.get("relationships", [])):
            rel_path = f"{path}.relationships[{rel_index}]"
            if not isinstance(rel, dict):
                errors.append(f"{rel_path} must be an object")
                continue
            _require_keys(rel, ("target_id", "relation_type", "public_description", "private_description"), rel_path, errors)
    for index, item in enumerate(cast):
        if isinstance(item, dict):
            for rel_index, rel in enumerate(item.get("relationships", [])):
                if isinstance(rel, dict) and rel.get("target_id") not in ids:
                    errors.append(f"$.cast[{index}].relationships[{rel_index}].target_id references unknown character")
    return ids


def _validate_phases(phases: list[Any], errors: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(phases):
        path = f"$.phases[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("phase_id", "title", "phase_type", "order", "materials_to_release", "clues_to_reveal", "dm_instructions"), path, errors)
        if _nonempty_string(item.get("phase_id"), f"{path}.phase_id", errors):
            _unique_add(ids, item["phase_id"], f"{path}.phase_id", errors)
        _enum(item.get("phase_type"), PHASE_TYPES, f"{path}.phase_type", errors)
    return ids


def _validate_role_packets(
    packets: list[Any],
    character_ids: set[str],
    phase_ids: set[str],
    errors: list[str],
) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(packets):
        path = f"$.role_packets[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            item,
            (
                "packet_id",
                "character_id",
                "phase_id",
                "content",
                "content_ref",
                "visibility",
                "recipients",
                "after_reveal_visibility",
                "reveal_instruction",
            ),
            path,
            errors,
        )
        if _nonempty_string(item.get("packet_id"), f"{path}.packet_id", errors):
            _unique_add(ids, item["packet_id"], f"{path}.packet_id", errors)
        _ref(item.get("character_id"), character_ids, f"{path}.character_id", errors)
        _ref(item.get("phase_id"), phase_ids, f"{path}.phase_id", errors)
        _enum(item.get("visibility"), PACKET_VISIBILITIES, f"{path}.visibility", errors)
        _enum(item.get("after_reveal_visibility"), PACKET_VISIBILITIES, f"{path}.after_reveal_visibility", errors)
        _enum(item.get("reveal_instruction"), REVEAL_INSTRUCTIONS, f"{path}.reveal_instruction", errors)
        if not item.get("content") and not item.get("content_ref"):
            errors.append(f"{path} must provide content or content_ref")
        if item.get("visibility") == "group_limited" or item.get("after_reveal_visibility") == "group_limited":
            recipients = item.get("recipients")
            if not isinstance(recipients, list) or not recipients:
                errors.append(f"{path}.recipients is required for group_limited visibility")
    return ids


def _validate_clues(
    clues: list[Any],
    assets: list[Any],
    character_ids: set[str],
    phase_ids: set[str],
    errors: list[str],
) -> set[str]:
    asset_ids = {asset.get("asset_id") for asset in assets if isinstance(asset, dict)}
    ids: set[str] = set()
    for index, item in enumerate(clues):
        path = f"$.clues[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("clue_id", "title", "clue_type", "content", "asset_refs", "initial_visibility", "reveal_phase", "related_characters"), path, errors)
        if _nonempty_string(item.get("clue_id"), f"{path}.clue_id", errors):
            _unique_add(ids, item["clue_id"], f"{path}.clue_id", errors)
        _enum(item.get("clue_type"), CLUE_TYPES, f"{path}.clue_type", errors)
        _enum(item.get("initial_visibility"), VISIBILITIES, f"{path}.initial_visibility", errors)
        if item.get("reveal_phase") is not None:
            _ref(item.get("reveal_phase"), phase_ids, f"{path}.reveal_phase", errors)
        for asset_ref in item.get("asset_refs", []):
            if asset_ref not in asset_ids:
                errors.append(f"{path}.asset_refs references unknown asset {asset_ref!r}")
        for character_id in item.get("related_characters", []):
            _ref(character_id, character_ids, f"{path}.related_characters", errors)
    return ids


def _validate_assets(assets: list[Any], clue_ids: set[str], errors: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(assets):
        path = f"$.assets[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("asset_id", "asset_type", "path", "description", "linked_clue_id", "visibility", "source_page", "requires_manual_review"), path, errors)
        if _nonempty_string(item.get("asset_id"), f"{path}.asset_id", errors):
            _unique_add(ids, item["asset_id"], f"{path}.asset_id", errors)
        _enum(item.get("asset_type"), ASSET_TYPES, f"{path}.asset_type", errors)
        _enum(item.get("visibility"), VISIBILITIES, f"{path}.visibility", errors)
        if item.get("linked_clue_id") is not None:
            _ref(item.get("linked_clue_id"), clue_ids, f"{path}.linked_clue_id", errors)
    return ids


def _validate_forms(forms: list[Any], phase_ids: set[str], errors: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(forms):
        path = f"$.forms[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("form_id", "title", "form_type", "per_player_or_global", "read_aloud_after_submit", "used_for_resolution", "fields", "submit_phase"), path, errors)
        if _nonempty_string(item.get("form_id"), f"{path}.form_id", errors):
            _unique_add(ids, item["form_id"], f"{path}.form_id", errors)
        _enum(item.get("form_type"), FORM_TYPES, f"{path}.form_type", errors)
        _enum(item.get("per_player_or_global"), {"per_player", "global"}, f"{path}.per_player_or_global", errors)
        _ref(item.get("submit_phase"), phase_ids, f"{path}.submit_phase", errors)
        for field_index, field in enumerate(item.get("fields", [])):
            field_path = f"{path}.fields[{field_index}]"
            if not isinstance(field, dict):
                errors.append(f"{field_path} must be an object")
                continue
            _require_keys(field, ("field_id", "label", "field_type", "required"), field_path, errors)
            _enum(field.get("field_type"), FIELD_TYPES, f"{field_path}.field_type", errors)
    return ids


def _validate_truth_model(
    data: dict[str, Any],
    game_mode: str,
    clue_ids: set[str],
    character_ids: set[str],
    errors: list[str],
) -> set[str]:
    truth_model = _object(data, "truth_model", "$", errors)
    _require_keys(truth_model, ("truth_type", "case_questions", "truth_nodes", "evidence_links"), "$.truth_model", errors)
    if "final_reveal_sequence" in truth_model:
        errors.append("$.truth_model.final_reveal_sequence is not allowed in v0.2.1")
    expected_truth_type = TRUTH_TYPES_BY_MODE.get(game_mode)
    if expected_truth_type and truth_model.get("truth_type") != expected_truth_type:
        errors.append(f"$.truth_model.truth_type must be {expected_truth_type!r} for game_mode {game_mode!r}")

    ids: set[str] = set()
    for index, item in enumerate(truth_model.get("truth_nodes", [])):
        path = f"$.truth_model.truth_nodes[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("node_id", "node_type", "content", "conditions", "related_characters", "related_clues"), path, errors)
        if _nonempty_string(item.get("node_id"), f"{path}.node_id", errors):
            _unique_add(ids, item["node_id"], f"{path}.node_id", errors)
        for character_id in item.get("related_characters", []):
            _ref(character_id, character_ids, f"{path}.related_characters", errors)
        for clue_id in item.get("related_clues", []):
            _ref(clue_id, clue_ids, f"{path}.related_clues", errors)

    for index, question in enumerate(truth_model.get("case_questions", [])):
        path = f"$.truth_model.case_questions[{index}]"
        if not isinstance(question, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(question, ("question_id", "prompt", "expected_answer_node_ids"), path, errors)
        for node_id in question.get("expected_answer_node_ids", []):
            _ref(node_id, ids, f"{path}.expected_answer_node_ids", errors)

    for index, link in enumerate(truth_model.get("evidence_links", [])):
        path = f"$.truth_model.evidence_links[{index}]"
        if not isinstance(link, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(link, ("link_id", "truth_node_id", "clue_id", "strength", "explanation"), path, errors)
        _ref(link.get("truth_node_id"), ids, f"{path}.truth_node_id", errors)
        _ref(link.get("clue_id"), clue_ids, f"{path}.clue_id", errors)
    return ids


def _validate_reveal_rules(
    reveal_rules: list[Any],
    phase_ids: set[str],
    clue_ids: set[str],
    packet_ids: set[str],
    asset_ids: set[str],
    form_ids: set[str],
    truth_node_ids: set[str],
    errors: list[str],
) -> set[str]:
    ids: set[str] = set()
    targets = {
        "clue": clue_ids,
        "role_packet": packet_ids,
        "asset": asset_ids,
        "form": form_ids,
        "truth_node": truth_node_ids,
    }
    for index, item in enumerate(reveal_rules):
        path = f"$.reveal_rules[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("rule_id", "target_type", "target_id", "trigger_type", "phase_id", "recipients", "after_reveal_visibility", "announcement_template"), path, errors)
        if _nonempty_string(item.get("rule_id"), f"{path}.rule_id", errors):
            _unique_add(ids, item["rule_id"], f"{path}.rule_id", errors)
        target_type = item.get("target_type")
        _enum(target_type, REVEAL_TARGET_TYPES, f"{path}.target_type", errors)
        _enum(item.get("trigger_type"), REVEAL_TRIGGERS, f"{path}.trigger_type", errors)
        _enum(item.get("after_reveal_visibility"), PACKET_VISIBILITIES, f"{path}.after_reveal_visibility", errors)
        if item.get("phase_id") is not None:
            _ref(item.get("phase_id"), phase_ids, f"{path}.phase_id", errors)
        if target_type in targets:
            _ref(item.get("target_id"), targets[target_type], f"{path}.target_id", errors)
        if not isinstance(item.get("recipients"), list) or not item.get("recipients"):
            errors.append(f"{path}.recipients must be a non-empty list")
    return ids


def _validate_player_config(data: dict[str, Any], character_ids: set[str], errors: list[str]) -> None:
    config = _object(data, "player_config", "$", errors)
    _require_keys(config, ("mode", "role_player_slots", "observer_slots"), "$.player_config", errors)
    _enum(config.get("mode"), {"all_role_players", "role_players_plus_observers", "role_players_plus_detectives"}, "$.player_config.mode", errors)
    for index, slot in enumerate(config.get("role_player_slots", [])):
        path = f"$.player_config.role_player_slots[{index}]"
        if isinstance(slot, dict):
            _require_keys(slot, ("slot_id", "character_id", "required"), path, errors)
            _ref(slot.get("character_id"), character_ids, f"{path}.character_id", errors)
        else:
            errors.append(f"{path} must be an object")


def _validate_forbidden_spoilers(
    data: dict[str, Any],
    reveal_rule_ids: set[str],
    phase_ids: set[str],
    errors: list[str],
) -> None:
    for index, item in enumerate(data.get("forbidden_spoilers", [])):
        path = f"$.forbidden_spoilers[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("spoiler_id", "spoiler_type", "content", "aliases", "forbidden_until_phase", "allowed_after_phase", "allowed_after_reveal_rule", "allowed_after_condition"), path, errors)
        if item.get("forbidden_until_phase") is not None:
            _ref(item.get("forbidden_until_phase"), phase_ids, f"{path}.forbidden_until_phase", errors)
        if item.get("allowed_after_phase") is not None:
            _ref(item.get("allowed_after_phase"), phase_ids, f"{path}.allowed_after_phase", errors)
        if item.get("allowed_after_reveal_rule") is not None:
            _ref(item.get("allowed_after_reveal_rule"), reveal_rule_ids, f"{path}.allowed_after_reveal_rule", errors)


def _validate_action_rules(data: dict[str, Any], form_ids: set[str], errors: list[str]) -> set[str]:
    action_rules = _object(data, "action_rules", "$", errors)
    _require_keys(action_rules, ("enabled", "action_types", "resolution_order", "blocking_rules", "outcomes"), "$.action_rules", errors)
    action_types: set[str] = set()
    for index, action in enumerate(action_rules.get("action_types", [])):
        path = f"$.action_rules.action_types[{index}]"
        if not isinstance(action, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(action, ("action_type", "actor_scope", "target_scope", "input_form_id", "changes_character_state", "changes_voting_eligibility", "changes_candidate_eligibility"), path, errors)
        action_type = action.get("action_type")
        _enum(action_type, ACTION_TYPES, f"{path}.action_type", errors)
        if isinstance(action_type, str):
            action_types.add(action_type)
        if action.get("input_form_id") is not None:
            _ref(action.get("input_form_id"), form_ids, f"{path}.input_form_id", errors)
    for action_type in action_rules.get("resolution_order", []):
        if action_type not in action_types:
            errors.append(f"$.action_rules.resolution_order references unknown action type {action_type!r}")
    for index, rule in enumerate(action_rules.get("blocking_rules", [])):
        path = f"$.action_rules.blocking_rules[{index}]"
        if isinstance(rule, dict):
            _require_keys(rule, ("rule_id", "blocked_action_type", "blocked_when", "blocked_by_action_type", "minimum_block_count", "same_target_required", "result"), path, errors)
            _ref(rule.get("blocked_action_type"), action_types, f"{path}.blocked_action_type", errors)
            if rule.get("blocked_by_action_type") is not None:
                _ref(rule.get("blocked_by_action_type"), action_types, f"{path}.blocked_by_action_type", errors)
    return action_types


def _validate_action_form_refs(action_types: set[str], forms: list[Any], errors: list[str]) -> None:
    if action_types and not any(isinstance(form, dict) and form.get("used_for_resolution") for form in forms):
        errors.append("$.forms must include at least one resolution form when action_rules are enabled")


def _validate_ending_rules(
    data: dict[str, Any],
    truth_node_ids: set[str],
    clue_ids: set[str],
    packet_ids: set[str],
    asset_ids: set[str],
    errors: list[str],
) -> None:
    ending_rules = _object(data, "ending_rules", "$", errors)
    _require_keys(ending_rules, ("ending_type", "conditions", "final_reveal_sequence"), "$.ending_rules", errors)
    valid_refs = truth_node_ids | clue_ids | packet_ids | asset_ids
    for index, item in enumerate(ending_rules.get("final_reveal_sequence", [])):
        path = f"$.ending_rules.final_reveal_sequence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("step", "trigger", "speaker_character_id", "required_code_word", "content_ref", "next_step_condition"), path, errors)
        content_ref = item.get("content_ref")
        if not isinstance(content_ref, str) or not content_ref:
            errors.append(f"{path}.content_ref must be a non-empty string")
        elif content_ref not in valid_refs and not content_ref.startswith("ending_text"):
            errors.append(f"{path}.content_ref references unknown content {content_ref!r}")


def _validate_scoring_rules(data: dict[str, Any], character_ids: set[str], errors: list[str]) -> None:
    scoring = _object(data, "scoring_rules", "$", errors)
    _require_keys(scoring, ("enabled", "goal_checks"), "$.scoring_rules", errors)
    for index, item in enumerate(scoring.get("goal_checks", [])):
        path = f"$.scoring_rules.goal_checks[{index}]"
        if isinstance(item, dict):
            _ref(item.get("character_id"), character_ids, f"{path}.character_id", errors)


def _validate_hint_rules(
    data: dict[str, Any],
    phase_ids: set[str],
    clue_ids: set[str],
    truth_node_ids: set[str],
    errors: list[str],
) -> None:
    for index, item in enumerate(data.get("hint_rules", [])):
        path = f"$.hint_rules[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("hint_id", "level", "phase_id", "allowed_when", "allowed_clue_ids", "allowed_truth_nodes", "forbidden_truth_nodes", "template", "cooldown_turns", "spoiler_check_mode"), path, errors)
        _enum(item.get("level"), HINT_LEVELS, f"{path}.level", errors)
        _enum(item.get("spoiler_check_mode"), SPOILER_CHECK_MODES, f"{path}.spoiler_check_mode", errors)
        if item.get("phase_id") is not None:
            _ref(item.get("phase_id"), phase_ids, f"{path}.phase_id", errors)
        for clue_id in item.get("allowed_clue_ids", []):
            _ref(clue_id, clue_ids, f"{path}.allowed_clue_ids", errors)
        for node_id in item.get("allowed_truth_nodes", []):
            _ref(node_id, truth_node_ids, f"{path}.allowed_truth_nodes", errors)
        for node_id in item.get("forbidden_truth_nodes", []):
            _ref(node_id, truth_node_ids, f"{path}.forbidden_truth_nodes", errors)


def _object(parent: dict[str, Any], key: str, path: str, errors: list[str]) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        errors.append(f"{path}.{key} must be an object")
        return {}
    return value


def _list(parent: dict[str, Any], key: str, path: str, errors: list[str]) -> list[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list")
        return []
    return value


def _require_keys(obj: dict[str, Any], keys: tuple[str, ...], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{path}.{key} is required")


def _enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path} must be one of {sorted(allowed)}, got {value!r}")


def _ref(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path} references unknown id {value!r}")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value:
        errors.append(f"{path} must be a non-empty string")
        return False
    return True


def _unique_add(values: set[str], value: str, path: str, errors: list[str]) -> None:
    if value in values:
        errors.append(f"{path} duplicates id {value!r}")
    values.add(value)
