"""Validation helpers for single-player detective GameSchema v0.3.

GameSchema v0.3 keeps v0.1 compatibility while adding the minimum structure
needed for a more inspectable runtime: clue lifecycle, phase/scene graph
conditions, stronger truth links, ending rules, and NPC action profiles.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from game_schema import GameSchemaValidationError, validate_game_schema as validate_game_schema_v0_1


GAME_SCHEMA_VERSION = "game_schema_v0.3"
CLUE_STATES = {"hidden", "discoverable", "discovered", "revealed", "locked"}
CONDITION_KEYS = {
    "manual",
    "game_over",
    "accusation_submitted",
    "phase_id_is",
    "phase_type_is",
    "turn_index_min",
    "action_count_min",
    "area_id_is",
    "target_character_id_is",
    "character_id_is",
    "evidence_id_is",
    "result_code_is",
    "npc_stance_is",
    "npc_location_scene_id_is",
    "unlocked_scene_ids_all",
    "unlocked_scene_ids_any",
    "searched_scene_ids_all",
    "searched_scene_ids_any",
    "discovered_evidence_ids_all",
    "discovered_evidence_ids_any",
    "new_evidence_ids_all",
    "new_evidence_ids_any",
    "revealed_evidence_ids_all",
    "revealed_evidence_ids_any",
    "broken_lie_ids_all",
    "broken_lie_ids_any",
    "new_broken_lie_ids_all",
    "new_broken_lie_ids_any",
    "unlocked_truth_ids_all",
    "unlocked_truth_ids_any",
}
ACTION_TYPES = {
    "stay",
    "move_to_scene",
    "change_stance",
    "raise_stress",
    "redirect_suspicion",
    "ask_player_question",
    "withdraw",
}
ACTION_TRIGGERS = {
    "after_any_player_action",
    "after_search",
    "after_ask",
    "after_confront",
    "search",
    "ask",
    "confront",
}
AUTHOR_QUESTION_TOPICS = {
    "public_identity",
    "private_pressure",
    "voice_and_attitude",
    "knowledge_boundary",
    "behavior_goal",
}
AUTHOR_QUESTION_JARGON = {
    "action_profile",
    "private_profile",
    "public_profile",
    "truth_id",
    "truth_ids",
    "forbidden_truth",
    "schema",
    "json",
}
PROFILE_PLACEHOLDERS = {
    "tbd",
    "todo",
    "unknown",
    "needs manual review",
    "requires manual review",
    "manual review required",
    "public profile needs manual review",
    "public profile requires manual review",
    "private details require manual review",
}


def load_game_schema_v0_3(path: str | Path) -> dict[str, Any]:
    """Load and validate one GameSchema v0.3 JSON file."""
    schema_path = Path(path)
    data = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    errors = validate_game_schema_v0_3(data)
    if errors:
        raise GameSchemaValidationError(errors)
    return data


def validate_game_schema_v0_3(data: Any) -> list[str]:
    """Return validation errors for a GameSchema v0.3 payload."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["$ must be an object"]
    if data.get("schema_version") != GAME_SCHEMA_VERSION:
        errors.append(f"$.schema_version must be {GAME_SCHEMA_VERSION!r}")

    base_payload = copy.deepcopy(data)
    base_payload["schema_version"] = "game_schema_v0.1"
    errors.extend(validate_game_schema_v0_1(base_payload))

    npcs = _list_value(data.get("npc_characters"))
    scenes = _list_value(data.get("scenes"))
    evidence = _list_value(data.get("evidence"))
    lies = _list_value(data.get("lies"))
    phases = _list_value(data.get("phases"))
    truth_model = data.get("truth_model", {}) if isinstance(data.get("truth_model"), dict) else {}
    truth_nodes = _list_value(truth_model.get("truth_nodes"))
    timeline = _list_value(truth_model.get("timeline"))

    ids = {
        "npc": _ids(npcs, "character_id"),
        "scene": _ids(scenes, "scene_id"),
        "evidence": _ids(evidence, "evidence_id"),
        "lie": _ids(lies, "lie_id"),
        "phase": _ids(phases, "phase_id"),
        "truth": _ids(truth_nodes, "truth_id"),
        "timeline": _ids(timeline, "timeline_id"),
    }
    evidence_by_id = {item.get("evidence_id"): item for item in evidence if isinstance(item, dict)}
    scene_by_id = {item.get("scene_id"): item for item in scenes if isinstance(item, dict)}

    _validate_evidence_lifecycle(evidence, ids, errors)
    _validate_scene_graph(scenes, ids, errors)
    _validate_phase_graph(phases, ids, errors)
    _validate_truth_links(truth_model, ids, errors)
    _validate_ending_rules(data, ids, evidence_by_id, scene_by_id, errors)
    _validate_review_author_questions(data, npcs, ids, errors)
    _validate_npc_action_profiles(npcs, ids, errors)
    _validate_spoiler_boundaries(data, npcs, truth_nodes, errors)

    return sorted(set(errors))


def build_npc_author_questions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build friendly author questions for NPCs whose roleplay setup is thin.

    These questions are intentionally author-facing. They avoid schema field
    names and ask for story intent in plain language so the importer can remain
    automatic for structural fields.
    """
    questions: list[dict[str, Any]] = []
    for npc in _list_value(data.get("npc_characters")):
        if not isinstance(npc, dict):
            continue
        for gap in _npc_profile_gaps(npc):
            questions.append(_build_author_question(npc, gap))
    return questions


def _validate_evidence_lifecycle(evidence: list[Any], ids: dict[str, set[str]], errors: list[str]) -> None:
    for index, item in enumerate(evidence):
        path = f"$.evidence[{index}]"
        if not isinstance(item, dict):
            continue
        _require_keys(item, ("source_scene_id", "lifecycle"), path, errors)
        _ref(item.get("source_scene_id"), ids["scene"], f"{path}.source_scene_id", errors)
        if item.get("source_scene_id") and item.get("scene_id") and item.get("source_scene_id") != item.get("scene_id"):
            errors.append(f"{path}.source_scene_id must match scene_id for v0.3 compatibility")
        lifecycle = item.get("lifecycle")
        if not isinstance(lifecycle, dict):
            errors.append(f"{path}.lifecycle must be an object")
            continue
        _require_keys(lifecycle, ("initial_state", "discoverable_when", "reveal_when", "lock_reason"), f"{path}.lifecycle", errors)
        if lifecycle.get("initial_state") not in CLUE_STATES:
            errors.append(f"{path}.lifecycle.initial_state must be one of {sorted(CLUE_STATES)}")
        if item.get("initially_discovered") and lifecycle.get("initial_state") in {"hidden", "locked"}:
            errors.append(f"{path}.lifecycle.initial_state conflicts with initially_discovered=true")
        if lifecycle.get("initial_state") == "locked" and not lifecycle.get("lock_reason"):
            errors.append(f"{path}.lifecycle.lock_reason is required when initial_state is locked")
        _validate_condition(lifecycle.get("discoverable_when"), f"{path}.lifecycle.discoverable_when", ids, errors)
        _validate_condition(lifecycle.get("reveal_when"), f"{path}.lifecycle.reveal_when", ids, errors)


def _validate_scene_graph(scenes: list[Any], ids: dict[str, set[str]], errors: list[str]) -> None:
    for index, scene in enumerate(scenes):
        path = f"$.scenes[{index}]"
        if not isinstance(scene, dict):
            continue
        _require_keys(scene, ("entry_condition", "exit_condition", "search_result_events", "scene_tags"), path, errors)
        _validate_condition(scene.get("entry_condition"), f"{path}.entry_condition", ids, errors)
        _validate_condition(scene.get("exit_condition"), f"{path}.exit_condition", ids, errors)
        if not isinstance(scene.get("scene_tags", []), list):
            errors.append(f"{path}.scene_tags must be a list")
        events = scene.get("search_result_events", [])
        if not isinstance(events, list):
            errors.append(f"{path}.search_result_events must be a list")
            continue
        for event_index, event in enumerate(events):
            if not isinstance(event, dict):
                errors.append(f"{path}.search_result_events[{event_index}] must be an object")
                continue
            _require_keys(event, ("event_id", "event_type", "target_ids"), f"{path}.search_result_events[{event_index}]", errors)
            for target_index, target_id in enumerate(event.get("target_ids", []) or []):
                if target_id not in ids["evidence"] and target_id not in ids["truth"] and target_id not in ids["lie"]:
                    errors.append(f"{path}.search_result_events[{event_index}].target_ids[{target_index}] unknown id: {target_id!r}")


def _validate_phase_graph(phases: list[Any], ids: dict[str, set[str]], errors: list[str]) -> None:
    for index, phase in enumerate(phases):
        path = f"$.phases[{index}]"
        if not isinstance(phase, dict):
            continue
        _require_keys(phase, ("entry_condition", "exit_condition", "mandatory_events", "optional_events"), path, errors)
        _validate_condition(phase.get("entry_condition"), f"{path}.entry_condition", ids, errors)
        _validate_condition(phase.get("exit_condition"), f"{path}.exit_condition", ids, errors)
        if phase.get("phase_type") != "recap" and not phase.get("exit_condition"):
            errors.append(f"{path}.exit_condition is required so the phase can exit")
        for key in ("mandatory_events", "optional_events"):
            if not isinstance(phase.get(key, []), list):
                errors.append(f"{path}.{key} must be a list")


def _validate_truth_links(truth_model: dict[str, Any], ids: dict[str, set[str]], errors: list[str]) -> None:
    for index, item in enumerate(_list_value(truth_model.get("timeline"))):
        path = f"$.truth_model.timeline[{index}]"
        if not isinstance(item, dict):
            continue
        _require_keys(item, ("timeline_id",), path, errors)

    for index, node in enumerate(_list_value(truth_model.get("truth_nodes"))):
        path = f"$.truth_model.truth_nodes[{index}]"
        if not isinstance(node, dict):
            continue
        _require_keys(node, ("required_clue_ids", "supporting_character_ids", "timeline_refs", "unlock_condition"), path, errors)
        for item_index, clue_id in enumerate(node.get("required_clue_ids", []) or []):
            _ref(clue_id, ids["evidence"], f"{path}.required_clue_ids[{item_index}]", errors)
        for item_index, npc_id in enumerate(node.get("supporting_character_ids", []) or []):
            _ref(npc_id, ids["npc"], f"{path}.supporting_character_ids[{item_index}]", errors)
        for item_index, timeline_id in enumerate(node.get("timeline_refs", []) or []):
            _ref(timeline_id, ids["timeline"], f"{path}.timeline_refs[{item_index}]", errors)
        _validate_condition(node.get("unlock_condition"), f"{path}.unlock_condition", ids, errors)
        related_evidence = node.get("related_evidence_ids", []) or []
        required_clues = node.get("required_clue_ids", []) or []
        if not node.get("revealed_by_default") and not related_evidence and not required_clues:
            errors.append(f"{path} truth_node lacks evidence: add related_evidence_ids or required_clue_ids")


def _validate_ending_rules(
    data: dict[str, Any],
    ids: dict[str, set[str]],
    evidence_by_id: dict[str, dict[str, Any]],
    scene_by_id: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    ending_rules = data.get("ending_rules")
    if not isinstance(ending_rules, dict):
        errors.append("$.ending_rules is required in GameSchema v0.3")
        return
    _require_keys(ending_rules, ("required_fields", "score_thresholds", "scoring_items"), "$.ending_rules", errors)
    scoring_items = ending_rules.get("scoring_items", [])
    if not isinstance(scoring_items, list) or not scoring_items:
        errors.append("$.ending_rules.scoring_items must be a non-empty list")
        return
    reachable_scenes = _statically_reachable_scene_ids(data, scene_by_id)
    for index, item in enumerate(scoring_items):
        path = f"$.ending_rules.scoring_items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(
            item,
            ("score_id", "field_id", "expected_character_id", "expected_truth_ids", "expected_evidence_ids", "expected_lie_ids", "points"),
            path,
            errors,
        )
        field_id = item.get("field_id")
        if field_id == "culprit" and not item.get("expected_character_id"):
            errors.append(f"{path} ending_rule incomplete: culprit scoring needs expected_character_id")
        if field_id in {"motive", "method"} and not item.get("expected_truth_ids") and not item.get("expected_evidence_ids"):
            errors.append(f"{path} ending_rule incomplete: {field_id} scoring needs expected truth or evidence")
        if field_id == "evidence_chain" and not (item.get("expected_truth_ids") or item.get("expected_evidence_ids") or item.get("expected_lie_ids")):
            errors.append(f"{path} ending_rule incomplete: evidence_chain needs expected refs")
        if item.get("expected_character_id"):
            _ref(item.get("expected_character_id"), ids["npc"], f"{path}.expected_character_id", errors)
        for item_index, truth_id in enumerate(item.get("expected_truth_ids", []) or []):
            _ref(truth_id, ids["truth"], f"{path}.expected_truth_ids[{item_index}]", errors)
        for item_index, evidence_id in enumerate(item.get("expected_evidence_ids", []) or []):
            _ref(evidence_id, ids["evidence"], f"{path}.expected_evidence_ids[{item_index}]", errors)
            evidence = evidence_by_id.get(evidence_id, {})
            scene_id = evidence.get("source_scene_id") or evidence.get("scene_id")
            lifecycle = evidence.get("lifecycle", {}) if isinstance(evidence.get("lifecycle"), dict) else {}
            if lifecycle.get("initial_state") == "locked":
                errors.append(f"{path}.expected_evidence_ids[{item_index}] references locked critical clue: {evidence_id}")
            if scene_id and scene_id not in reachable_scenes:
                errors.append(f"{path}.expected_evidence_ids[{item_index}] critical clue unreachable: {evidence_id}")
        for item_index, lie_id in enumerate(item.get("expected_lie_ids", []) or []):
            _ref(lie_id, ids["lie"], f"{path}.expected_lie_ids[{item_index}]", errors)


def _validate_review_author_questions(
    data: dict[str, Any],
    npcs: list[Any],
    ids: dict[str, set[str]],
    errors: list[str],
) -> None:
    review = data.get("review")
    if not isinstance(review, dict):
        return
    if "author_questions" not in review:
        errors.append("$.review.author_questions is required in GameSchema v0.3")
        questions = []
    else:
        questions = review.get("author_questions")
    if not isinstance(questions, list):
        errors.append("$.review.author_questions must be a list")
        questions = []

    question_ids: set[str] = set()
    seen_question_ids: set[str] = set()
    for index, question in enumerate(questions):
        path = f"$.review.author_questions[{index}]"
        if not isinstance(question, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(question, ("question_id", "target_type", "target_id", "topic", "question", "why", "blocking"), path, errors)
        question_id = question.get("question_id")
        if isinstance(question_id, str):
            if question_id in seen_question_ids:
                errors.append(f"{path}.question_id duplicates another author question: {question_id!r}")
            seen_question_ids.add(question_id)
            question_ids.add(question_id)
        if question.get("target_type") != "npc_character":
            errors.append(f"{path}.target_type must be 'npc_character'")
        if question.get("target_id"):
            _ref(question.get("target_id"), ids["npc"], f"{path}.target_id", errors)
        if question.get("topic") not in AUTHOR_QUESTION_TOPICS:
            errors.append(f"{path}.topic unsupported: {question.get('topic')!r}")
        question_text = str(question.get("question", "") or "").strip()
        if _is_thin_text(question_text, min_chars=16):
            errors.append(f"{path}.question must be a friendly complete question")
        lowered = question_text.casefold()
        for jargon in sorted(AUTHOR_QUESTION_JARGON):
            if jargon in lowered:
                errors.append(f"{path}.question uses technical wording; ask in plain chat language instead: {jargon}")
        if not isinstance(question.get("blocking"), bool):
            errors.append(f"{path}.blocking must be boolean")

    for npc_index, npc in enumerate(npcs):
        if not isinstance(npc, dict):
            continue
        for gap in _npc_profile_gaps(npc):
            expected_id = _author_question_id(npc, gap["gap_key"])
            if expected_id not in question_ids:
                errors.append(
                    f"$.npc_characters[{npc_index}] NPC profile incomplete: add review.author_questions item {expected_id!r}"
                )


def _validate_npc_action_profiles(npcs: list[Any], ids: dict[str, set[str]], errors: list[str]) -> None:
    seen_rule_ids: set[str] = set()
    for npc_index, npc in enumerate(npcs):
        if not isinstance(npc, dict):
            continue
        character_id = npc.get("character_id", f"npc_{npc_index}")
        profile = npc.get("action_profile")
        if profile is None:
            continue
        path = f"$.npc_characters[{npc_index}].action_profile"
        if not isinstance(profile, dict):
            errors.append(f"{path} must be an object")
            continue
        _require_keys(profile, ("initial_location_scene_id", "goals", "rules"), path, errors)
        _ref(profile.get("initial_location_scene_id"), ids["scene"], f"{path}.initial_location_scene_id", errors)
        for rule_index, rule in enumerate(profile.get("rules", []) or []):
            rule_path = f"{path}.rules[{rule_index}]"
            if not isinstance(rule, dict):
                errors.append(f"{rule_path} must be an object")
                continue
            _require_keys(rule, ("rule_id", "priority", "trigger", "conditions", "action", "visible_event"), rule_path, errors)
            rule_ref = f"{character_id}:{rule.get('rule_id', '')}"
            if rule_ref in seen_rule_ids:
                errors.append(f"{rule_path}.rule_id duplicates action rule: {rule_ref}")
            seen_rule_ids.add(rule_ref)
            if rule.get("trigger") not in ACTION_TRIGGERS:
                errors.append(f"{rule_path}.trigger unsupported: {rule.get('trigger')!r}")
            _validate_condition(rule.get("conditions"), f"{rule_path}.conditions", ids, errors)
            action = rule.get("action")
            if not isinstance(action, dict):
                errors.append(f"{rule_path}.action must be an object")
                continue
            if action.get("type") not in ACTION_TYPES:
                errors.append(f"{rule_path}.action.type unsupported: {action.get('type')!r}")
            if action.get("target_scene_id"):
                _ref(action.get("target_scene_id"), ids["scene"], f"{rule_path}.action.target_scene_id", errors)
            for key in ("target_character_id", "suspicion_target_id"):
                if action.get(key):
                    _ref(action.get(key), ids["npc"], f"{rule_path}.action.{key}", errors)


def _validate_spoiler_boundaries(data: dict[str, Any], npcs: list[Any], truth_nodes: list[Any], errors: list[str]) -> None:
    public_blob = json.dumps(data.get("public_case", {}), ensure_ascii=False)
    for index, npc in enumerate(npcs):
        if not isinstance(npc, dict):
            continue
        private_profile = str(npc.get("private_profile", "") or "")
        if private_profile and private_profile in public_blob:
            errors.append(f"$.public_case leaks private_profile for npc {npc.get('character_id', index)!r}")

    culprit_truth_ids = {
        str(node.get("truth_id"))
        for node in truth_nodes
        if isinstance(node, dict) and "culprit" in str(node.get("truth_id", "")).lower()
    }
    if not culprit_truth_ids:
        return
    for index, npc in enumerate(npcs):
        if not isinstance(npc, dict):
            continue
        rules = npc.get("conversation_rules", {}) if isinstance(npc.get("conversation_rules"), dict) else {}
        forbidden = set(rules.get("forbidden_truth_ids", []) or [])
        missing = sorted(culprit_truth_ids - forbidden)
        if missing:
            errors.append(f"$.npc_characters[{index}].conversation_rules.forbidden_truth_ids missing culprit spoiler truth ids: {missing}")


def _npc_profile_gaps(npc: dict[str, Any]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    rules = npc.get("conversation_rules", {}) if isinstance(npc.get("conversation_rules"), dict) else {}
    profile = npc.get("action_profile", {}) if isinstance(npc.get("action_profile"), dict) else {}
    goals = profile.get("goals", []) if isinstance(profile.get("goals"), list) else []

    if _is_thin_text(npc.get("public_profile"), min_chars=24):
        gaps.append(
            {
                "gap_key": "public_identity",
                "topic": "public_identity",
                "why": "NPC visible identity is too thin for natural conversation.",
            }
        )
    if _is_thin_text(npc.get("private_profile"), min_chars=24):
        gaps.append(
            {
                "gap_key": "private_pressure",
                "topic": "private_pressure",
                "why": "NPC hidden pressure or secret is too thin for roleplay.",
            }
        )
    if _is_thin_text(npc.get("initial_attitude"), min_chars=20) and _is_thin_text(rules.get("fallback_style"), min_chars=20):
        gaps.append(
            {
                "gap_key": "voice_and_attitude",
                "topic": "voice_and_attitude",
                "why": "NPC attitude and speaking style are too thin.",
            }
        )
    if not npc.get("known_truth_ids") or not rules.get("forbidden_truth_ids"):
        gaps.append(
            {
                "gap_key": "knowledge_boundary",
                "topic": "knowledge_boundary",
                "why": "NPC known facts or spoiler boundaries are unclear.",
            }
        )
    if profile and (_is_thin_text(profile.get("initial_stance"), min_chars=4) or not _has_goal_directive(goals)):
        gaps.append(
            {
                "gap_key": "behavior_goal",
                "topic": "behavior_goal",
                "why": "NPC behavior goal is too thin for autonomous action.",
            }
        )
    return gaps


def _build_author_question(npc: dict[str, Any], gap: dict[str, str]) -> dict[str, Any]:
    character_id = str(npc.get("character_id") or "unknown_npc")
    display_name = str(npc.get("display_name") or character_id)
    gap_key = gap["gap_key"]
    question_templates = {
        "public_identity": f"{display_name} 出场时，玩家一眼应该觉得这是个什么样的人？可以说说职业、和死者的关系，以及他给人的第一印象。",
        "private_pressure": f"{display_name} 心里最怕侦探发现什么？这件事不一定等于真凶秘密，也可以是丑闻、亏欠、把柄或难以解释的关系。",
        "voice_and_attitude": f"如果侦探追问到关键处，{display_name} 会怎么说话？比如冷静解释、嘴硬反击、装糊涂、情绪崩溃，还是假装配合。",
        "knowledge_boundary": f"{display_name} 现在明确知道哪些事、绝对不能提前说破哪些事？请用普通剧情描述就好，不需要写技术格式。",
        "behavior_goal": f"玩家每次推进调查后，{display_name} 最想做什么？比如转移怀疑、躲开追问、主动示好、守住某个地点，或者暗示一条线索。",
    }
    return {
        "question_id": _author_question_id(npc, gap_key),
        "target_type": "npc_character",
        "target_id": character_id,
        "topic": gap["topic"],
        "question": question_templates[gap_key],
        "why": gap["why"],
        "blocking": True,
    }


def _author_question_id(npc: dict[str, Any], gap_key: str) -> str:
    return f"npc:{npc.get('character_id', 'unknown_npc')}:{gap_key}"


def _is_thin_text(value: Any, min_chars: int) -> bool:
    if not isinstance(value, str):
        return True
    text = " ".join(value.strip().split())
    if len(text) < min_chars:
        return True
    lowered = text.casefold()
    return any(placeholder in lowered for placeholder in PROFILE_PLACEHOLDERS)


def _has_goal_directive(goals: list[Any]) -> bool:
    for goal in goals:
        if isinstance(goal, dict) and not _is_thin_text(goal.get("directive"), min_chars=20):
            return True
    return False


def _validate_condition(condition: Any, path: str, ids: dict[str, set[str]], errors: list[str]) -> None:
    if condition in (None, {}):
        return
    if not isinstance(condition, dict):
        errors.append(f"{path} must be an object")
        return
    for key, value in condition.items():
        if key not in CONDITION_KEYS:
            errors.append(f"{path}.{key} unsupported condition key")
            continue
        values = _as_list(value)
        if key.endswith("_scene_ids_all") or key.endswith("_scene_ids_any") or key in {"area_id_is", "npc_location_scene_id_is"}:
            _refs(values, ids["scene"], f"{path}.{key}", errors)
        elif key.startswith("discovered_evidence_ids_") or key.startswith("revealed_evidence_ids_") or key.startswith("new_evidence_ids_") or key == "evidence_id_is":
            _refs(values, ids["evidence"], f"{path}.{key}", errors)
        elif key.startswith("broken_lie_ids_") or key.startswith("new_broken_lie_ids_"):
            _refs(values, ids["lie"], f"{path}.{key}", errors)
        elif key.startswith("unlocked_truth_ids_"):
            _refs(values, ids["truth"], f"{path}.{key}", errors)
        elif key in {"target_character_id_is", "character_id_is"}:
            _refs(values, ids["npc"], f"{path}.{key}", errors)
        elif key == "phase_id_is":
            _refs(values, ids["phase"], f"{path}.{key}", errors)
        elif key in {"manual", "game_over", "accusation_submitted"} and not isinstance(value, bool):
            errors.append(f"{path}.{key} must be boolean")
        elif key in {"turn_index_min", "action_count_min"} and not isinstance(value, int):
            errors.append(f"{path}.{key} must be integer")


def _statically_reachable_scene_ids(data: dict[str, Any], scene_by_id: dict[str, dict[str, Any]]) -> set[str]:
    reachable = set((data.get("public_case", {}) or {}).get("initial_available_scene_ids", []) or [])
    for phase in _list_value(data.get("phases")):
        if isinstance(phase, dict):
            reachable.update(phase.get("unlocked_scene_ids", []) or [])
    for scene_id, scene in scene_by_id.items():
        if scene.get("initially_unlocked") or scene.get("entry_condition"):
            reachable.add(scene_id)
    return reachable


def _require_keys(value: dict[str, Any], keys: tuple[str, ...], path: str, errors: list[str]) -> None:
    for key in keys:
        if key not in value:
            errors.append(f"{path}.{key} is required")


def _ids(items: list[Any], key: str) -> set[str]:
    return {
        str(item.get(key))
        for item in items
        if isinstance(item, dict) and item.get(key)
    }


def _ref(value: Any, valid_ids: set[str], path: str, errors: list[str]) -> None:
    if value is None:
        errors.append(f"{path} is required")
    elif str(value) not in valid_ids:
        errors.append(f"{path} references unknown id: {value!r}")


def _refs(values: list[Any], valid_ids: set[str], path: str, errors: list[str]) -> None:
    for index, value in enumerate(values):
        _ref(value, valid_ids, f"{path}[{index}]", errors)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


validate_game_schema = validate_game_schema_v0_3
load_game_schema = load_game_schema_v0_3


__all__ = [
    "GAME_SCHEMA_VERSION",
    "build_npc_author_questions",
    "load_game_schema",
    "load_game_schema_v0_3",
    "validate_game_schema",
    "validate_game_schema_v0_3",
]
