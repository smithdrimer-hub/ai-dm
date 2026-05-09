"""Validation helpers for single-player detective GameSchema v0.1.

GameSchema is intentionally separate from ScriptSchema. ScriptSchema models a
multi-player murder mystery host workflow; GameSchema models a single detective
game where the program is the judge and the LLM is only an actor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


GAME_SCHEMA_VERSION = "game_schema_v0.1"


class GameSchemaValidationError(ValueError):
    """Raised when a GameSchema payload fails validation."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def load_game_schema(path: str | Path) -> dict[str, Any]:
    """Load and validate one GameSchema JSON file."""
    schema_path = Path(path)
    data = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    errors = validate_game_schema(data)
    if errors:
        raise GameSchemaValidationError(errors)
    return data


def validate_game_schema(data: Any) -> list[str]:
    """Return validation errors for a GameSchema v0.1 payload."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$ must be an object"]

    required = (
        "schema_version",
        "game_info",
        "source_info",
        "review",
        "public_case",
        "npc_characters",
        "scenes",
        "evidence",
        "lies",
        "truth_model",
        "phases",
        "mechanics",
        "accusation_rules",
        "recap",
    )
    _require_keys(data, required, "$", errors)
    if data.get("schema_version") != GAME_SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {GAME_SCHEMA_VERSION!r}")

    game_info = _object(data, "game_info", "$.game_info", errors)
    _require_keys(game_info, ("id", "title", "language", "mode", "player_role"), "$.game_info", errors)
    _enum(game_info.get("mode"), {"single_player_detective"}, "$.game_info.mode", errors)
    _enum(game_info.get("player_role"), {"detective"}, "$.game_info.player_role", errors)

    source_info = _object(data, "source_info", "$.source_info", errors)
    _require_keys(source_info, ("source_type", "input_format", "license_status", "notes"), "$.source_info", errors)
    _enum(source_info.get("source_type"), {"murder_mystery_text", "suspense_novel", "manual"}, "$.source_info.source_type", errors)
    _enum(source_info.get("input_format"), {"md", "txt", "json", "manual"}, "$.source_info.input_format", errors)

    review = _object(data, "review", "$.review", errors)
    _require_keys(
        review,
        ("status", "missing_fields", "logic_warnings", "spoiler_risks", "manual_checklist", "source_traces"),
        "$.review",
        errors,
    )
    _enum(review.get("status"), {"draft", "needs_review", "confirmed"}, "$.review.status", errors)
    for key in ("missing_fields", "logic_warnings", "spoiler_risks", "manual_checklist", "source_traces"):
        _list(review, key, f"$.review.{key}", errors)

    public_case = _object(data, "public_case", "$.public_case", errors)
    _require_keys(
        public_case,
        ("setting", "opening_text", "detective_briefing", "case_objectives", "initial_available_scene_ids", "content_warnings"),
        "$.public_case",
        errors,
    )
    _list(public_case, "case_objectives", "$.public_case.case_objectives", errors)
    _list(public_case, "initial_available_scene_ids", "$.public_case.initial_available_scene_ids", errors)
    _list(public_case, "content_warnings", "$.public_case.content_warnings", errors)

    npcs = _list(data, "npc_characters", "$.npc_characters", errors)
    scenes = _list(data, "scenes", "$.scenes", errors)
    evidence = _list(data, "evidence", "$.evidence", errors)
    lies = _list(data, "lies", "$.lies", errors)
    phases = _list(data, "phases", "$.phases", errors)

    npc_ids = _collect_ids(npcs, "character_id", "$.npc_characters", errors)
    scene_ids = _collect_ids(scenes, "scene_id", "$.scenes", errors)
    evidence_ids = _collect_ids(evidence, "evidence_id", "$.evidence", errors)
    lie_ids = _collect_ids(lies, "lie_id", "$.lies", errors)
    phase_ids = _collect_ids(phases, "phase_id", "$.phases", errors)

    truth_model = _object(data, "truth_model", "$.truth_model", errors)
    _require_keys(
        truth_model,
        ("culprit_character_id", "motive_truth_id", "method_truth_id", "truth_nodes", "timeline", "evidence_links"),
        "$.truth_model",
        errors,
    )
    truth_nodes = _list(truth_model, "truth_nodes", "$.truth_model.truth_nodes", errors)
    truth_ids = _collect_ids(truth_nodes, "truth_id", "$.truth_model.truth_nodes", errors)

    _ref(truth_model.get("culprit_character_id"), npc_ids, "$.truth_model.culprit_character_id", errors)
    _ref(truth_model.get("motive_truth_id"), truth_ids, "$.truth_model.motive_truth_id", errors)
    _ref(truth_model.get("method_truth_id"), truth_ids, "$.truth_model.method_truth_id", errors)

    _validate_npcs(npcs, npc_ids, lie_ids, truth_ids, errors)
    _validate_scenes(scenes, scene_ids, npc_ids, evidence_ids, errors)
    _validate_evidence(evidence, scene_ids, truth_ids, lie_ids, errors)
    _validate_lies(lies, npc_ids, evidence_ids, truth_ids, phase_ids, errors)
    _validate_truth_model(truth_model, truth_ids, npc_ids, evidence_ids, errors)
    _validate_phases(phases, scene_ids, evidence_ids, errors)
    _validate_mechanics(data, phase_ids, errors)
    _validate_accusation_rules(data, npc_ids, evidence_ids, truth_ids, lie_ids, errors)
    _validate_recap(data, errors)

    for index, scene_id in enumerate(public_case.get("initial_available_scene_ids", []) or []):
        _ref(scene_id, scene_ids, f"$.public_case.initial_available_scene_ids[{index}]", errors)

    return errors


def _validate_npcs(
    npcs: list[Any],
    npc_ids: set[str],
    lie_ids: set[str],
    truth_ids: set[str],
    errors: list[str],
) -> None:
    for index, npc in enumerate(npcs):
        path = f"$.npc_characters[{index}]"
        if not isinstance(npc, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            npc,
            (
                "character_id",
                "display_name",
                "public_profile",
                "private_profile",
                "known_truth_ids",
                "initial_attitude",
                "conversation_rules",
            ),
            path,
            errors,
        )
        for item_index, truth_id in enumerate(npc.get("known_truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.known_truth_ids[{item_index}]", errors)
        rules = _object(npc, "conversation_rules", f"{path}.conversation_rules", errors)
        _require_keys(rules, ("can_lie", "lie_ids", "forbidden_truth_ids", "fallback_style"), f"{path}.conversation_rules", errors)
        if not isinstance(rules.get("can_lie"), bool):
            errors.append(f"{path}.conversation_rules.can_lie must be boolean")
        for item_index, lie_id in enumerate(rules.get("lie_ids", []) or []):
            _ref(lie_id, lie_ids, f"{path}.conversation_rules.lie_ids[{item_index}]", errors)
        for item_index, truth_id in enumerate(rules.get("forbidden_truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.conversation_rules.forbidden_truth_ids[{item_index}]", errors)
        _ref(npc.get("character_id"), npc_ids, f"{path}.character_id", errors)


def _validate_scenes(
    scenes: list[Any],
    scene_ids: set[str],
    npc_ids: set[str],
    evidence_ids: set[str],
    errors: list[str],
) -> None:
    for index, scene in enumerate(scenes):
        path = f"$.scenes[{index}]"
        if not isinstance(scene, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(scene, ("scene_id", "title", "description", "initially_unlocked", "unlock_condition", "evidence_ids", "npc_ids"), path, errors)
        if not isinstance(scene.get("initially_unlocked"), bool):
            errors.append(f"{path}.initially_unlocked must be boolean")
        _ref(scene.get("scene_id"), scene_ids, f"{path}.scene_id", errors)
        for item_index, evidence_id in enumerate(scene.get("evidence_ids", []) or []):
            _ref(evidence_id, evidence_ids, f"{path}.evidence_ids[{item_index}]", errors)
        for item_index, npc_id in enumerate(scene.get("npc_ids", []) or []):
            _ref(npc_id, npc_ids, f"{path}.npc_ids[{item_index}]", errors)


def _validate_evidence(
    evidence: list[Any],
    scene_ids: set[str],
    truth_ids: set[str],
    lie_ids: set[str],
    errors: list[str],
) -> None:
    for index, item in enumerate(evidence):
        path = f"$.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            item,
            (
                "evidence_id",
                "title",
                "evidence_type",
                "content",
                "scene_id",
                "initially_discovered",
                "unlock_condition",
                "related_truth_ids",
                "can_confront_lie_ids",
            ),
            path,
            errors,
        )
        _enum(item.get("evidence_type"), {"physical", "document", "testimony", "digital", "observation", "other"}, f"{path}.evidence_type", errors)
        if not isinstance(item.get("initially_discovered"), bool):
            errors.append(f"{path}.initially_discovered must be boolean")
        _ref(item.get("scene_id"), scene_ids, f"{path}.scene_id", errors)
        for item_index, truth_id in enumerate(item.get("related_truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.related_truth_ids[{item_index}]", errors)
        for item_index, lie_id in enumerate(item.get("can_confront_lie_ids", []) or []):
            _ref(lie_id, lie_ids, f"{path}.can_confront_lie_ids[{item_index}]", errors)


def _validate_lies(
    lies: list[Any],
    npc_ids: set[str],
    evidence_ids: set[str],
    truth_ids: set[str],
    phase_ids: set[str],
    errors: list[str],
) -> None:
    for index, lie in enumerate(lies):
        path = f"$.lies[{index}]"
        if not isinstance(lie, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(lie, ("lie_id", "character_id", "claim", "truth_id", "required_evidence_ids", "break_result"), path, errors)
        _ref(lie.get("character_id"), npc_ids, f"{path}.character_id", errors)
        _ref(lie.get("truth_id"), truth_ids, f"{path}.truth_id", errors)
        for item_index, evidence_id in enumerate(lie.get("required_evidence_ids", []) or []):
            _ref(evidence_id, evidence_ids, f"{path}.required_evidence_ids[{item_index}]", errors)
        result = _object(lie, "break_result", f"{path}.break_result", errors)
        _require_keys(result, ("unlocked_truth_ids", "phase_unlock_ids", "attitude_shift", "response_guidance"), f"{path}.break_result", errors)
        for item_index, truth_id in enumerate(result.get("unlocked_truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.break_result.unlocked_truth_ids[{item_index}]", errors)
        for item_index, phase_id in enumerate(result.get("phase_unlock_ids", []) or []):
            _ref(phase_id, phase_ids, f"{path}.break_result.phase_unlock_ids[{item_index}]", errors)


def _validate_truth_model(
    truth_model: dict[str, Any],
    truth_ids: set[str],
    npc_ids: set[str],
    evidence_ids: set[str],
    errors: list[str],
) -> None:
    for index, node in enumerate(truth_model.get("truth_nodes", []) or []):
        path = f"$.truth_model.truth_nodes[{index}]"
        if not isinstance(node, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(node, ("truth_id", "truth_type", "content", "revealed_by_default", "related_character_ids", "related_evidence_ids"), path, errors)
        _enum(node.get("truth_type"), {"fact", "motive", "method", "timeline", "alibi", "contradiction", "identity", "other"}, f"{path}.truth_type", errors)
        if not isinstance(node.get("revealed_by_default"), bool):
            errors.append(f"{path}.revealed_by_default must be boolean")
        for item_index, npc_id in enumerate(node.get("related_character_ids", []) or []):
            _ref(npc_id, npc_ids, f"{path}.related_character_ids[{item_index}]", errors)
        for item_index, evidence_id in enumerate(node.get("related_evidence_ids", []) or []):
            _ref(evidence_id, evidence_ids, f"{path}.related_evidence_ids[{item_index}]", errors)

    for index, item in enumerate(truth_model.get("timeline", []) or []):
        path = f"$.truth_model.timeline[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(item, ("time_label", "event", "truth_ids"), path, errors)
        for item_index, truth_id in enumerate(item.get("truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.truth_ids[{item_index}]", errors)

    for index, link in enumerate(truth_model.get("evidence_links", []) or []):
        path = f"$.truth_model.evidence_links[{index}]"
        if not isinstance(link, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(link, ("link_id", "truth_id", "evidence_id", "strength", "explanation"), path, errors)
        _ref(link.get("truth_id"), truth_ids, f"{path}.truth_id", errors)
        _ref(link.get("evidence_id"), evidence_ids, f"{path}.evidence_id", errors)
        _enum(link.get("strength"), {"suggests", "supports", "contradicts", "proves"}, f"{path}.strength", errors)


def _validate_phases(phases: list[Any], scene_ids: set[str], evidence_ids: set[str], errors: list[str]) -> None:
    seen_orders: set[int] = set()
    for index, phase in enumerate(phases):
        path = f"$.phases[{index}]"
        if not isinstance(phase, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            phase,
            ("phase_id", "title", "phase_type", "order", "unlock_condition", "unlocked_scene_ids", "unlocked_evidence_ids", "allowed_actions"),
            path,
            errors,
        )
        _enum(phase.get("phase_type"), {"intro", "investigation", "confrontation", "accusation", "recap"}, f"{path}.phase_type", errors)
        order = phase.get("order")
        if not isinstance(order, int):
            errors.append(f"{path}.order must be integer")
        elif order in seen_orders:
            errors.append(f"{path}.order duplicates another phase order: {order}")
        else:
            seen_orders.add(order)
        for item_index, scene_id in enumerate(phase.get("unlocked_scene_ids", []) or []):
            _ref(scene_id, scene_ids, f"{path}.unlocked_scene_ids[{item_index}]", errors)
        for item_index, evidence_id in enumerate(phase.get("unlocked_evidence_ids", []) or []):
            _ref(evidence_id, evidence_ids, f"{path}.unlocked_evidence_ids[{item_index}]", errors)
        for item_index, action in enumerate(phase.get("allowed_actions", []) or []):
            _enum(action, {"ask", "search", "inspect", "show_evidence", "accuse", "status", "hint", "review"}, f"{path}.allowed_actions[{item_index}]", errors)


def _validate_mechanics(data: dict[str, Any], phase_ids: set[str], errors: list[str]) -> None:
    mechanics = _object(data, "mechanics", "$.mechanics", errors)
    _require_keys(mechanics, ("starting_phase_id", "max_hint_level", "commands"), "$.mechanics", errors)
    _ref(mechanics.get("starting_phase_id"), phase_ids, "$.mechanics.starting_phase_id", errors)
    if not isinstance(mechanics.get("max_hint_level"), int):
        errors.append("$.mechanics.max_hint_level must be integer")
    commands = _object(mechanics, "commands", "$.mechanics.commands", errors)
    for key in ("ask", "search", "inspect", "show_evidence", "accuse", "status", "hint"):
        _nonempty_string(commands.get(key), f"$.mechanics.commands.{key}", errors)


def _validate_accusation_rules(
    data: dict[str, Any],
    npc_ids: set[str],
    evidence_ids: set[str],
    truth_ids: set[str],
    lie_ids: set[str],
    errors: list[str],
) -> None:
    rules = _object(data, "accusation_rules", "$.accusation_rules", errors)
    _require_keys(rules, ("required_fields", "scoring_items", "score_thresholds"), "$.accusation_rules", errors)
    required_fields = _list(rules, "required_fields", "$.accusation_rules.required_fields", errors)
    for field in ("culprit", "motive", "method", "evidence_chain"):
        if field not in required_fields:
            errors.append(f"$.accusation_rules.required_fields must include {field!r}")
    thresholds = _object(rules, "score_thresholds", "$.accusation_rules.score_thresholds", errors)
    _require_keys(thresholds, ("perfect", "pass"), "$.accusation_rules.score_thresholds", errors)
    for key in ("perfect", "pass"):
        if not isinstance(thresholds.get(key), int):
            errors.append(f"$.accusation_rules.score_thresholds.{key} must be integer")

    items = _list(rules, "scoring_items", "$.accusation_rules.scoring_items", errors)
    _collect_ids(items, "score_id", "$.accusation_rules.scoring_items", errors)
    for index, item in enumerate(items):
        path = f"$.accusation_rules.scoring_items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            item,
            (
                "score_id",
                "field_id",
                "prompt",
                "expected_character_id",
                "expected_truth_ids",
                "expected_evidence_ids",
                "expected_lie_ids",
                "points",
            ),
            path,
            errors,
        )
        _enum(item.get("field_id"), {"culprit", "motive", "method", "evidence_chain"}, f"{path}.field_id", errors)
        expected_character_id = item.get("expected_character_id")
        if expected_character_id is not None:
            _ref(expected_character_id, npc_ids, f"{path}.expected_character_id", errors)
        for item_index, truth_id in enumerate(item.get("expected_truth_ids", []) or []):
            _ref(truth_id, truth_ids, f"{path}.expected_truth_ids[{item_index}]", errors)
        for item_index, evidence_id in enumerate(item.get("expected_evidence_ids", []) or []):
            _ref(evidence_id, evidence_ids, f"{path}.expected_evidence_ids[{item_index}]", errors)
        for item_index, lie_id in enumerate(item.get("expected_lie_ids", []) or []):
            _ref(lie_id, lie_ids, f"{path}.expected_lie_ids[{item_index}]", errors)
        if not isinstance(item.get("points"), int) or item.get("points", 0) <= 0:
            errors.append(f"{path}.points must be a positive integer")


def _validate_recap(data: dict[str, Any], errors: list[str]) -> None:
    recap = _object(data, "recap", "$.recap", errors)
    _require_keys(recap, ("truth_summary", "timeline_summary", "missed_content_templates"), "$.recap", errors)
    _list(recap, "missed_content_templates", "$.recap.missed_content_templates", errors)


def _object(parent: dict[str, Any], key: str, path: str, errors: list[str]) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    errors.append(f"{path} must be an object")
    return {}


def _list(parent: dict[str, Any], key: str, path: str, errors: list[str]) -> list[Any]:
    value = parent.get(key)
    if isinstance(value, list):
        return value
    errors.append(f"{path} must be an array")
    return []


def _require_keys(obj: dict[str, Any], keys: tuple[str, ...], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in obj:
            errors.append(f"{path}.{key} is required")


def _enum(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{path} must be one of {sorted(allowed)}, got {value!r}")


def _ref(value: Any, allowed: set[str], path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        errors.append(f"{path} must be a non-empty string reference")
        return
    if value not in allowed:
        errors.append(f"{path} references unknown id: {value!r}")


def _nonempty_string(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")


def _collect_ids(items: list[Any], key: str, path: str, errors: list[str]) -> set[str]:
    values: set[str] = set()
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_path} must be an object")
            continue
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{item_path}.{key} must be a non-empty string")
            continue
        if value in values:
            errors.append(f"{item_path}.{key} duplicates id: {value!r}")
        values.add(value)
    return values


__all__ = [
    "GAME_SCHEMA_VERSION",
    "GameSchemaValidationError",
    "load_game_schema",
    "validate_game_schema",
]
