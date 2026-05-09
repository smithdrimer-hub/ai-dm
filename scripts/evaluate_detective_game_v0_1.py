"""Offline auto-evaluator for DetectiveGameEngine v0.1 cases.

The evaluator is an oracle-driven smoke/playthrough tool. It does not claim to
model real player reasoning; it checks whether a case can be completed, whether
misleading paths end stably, and whether lightweight NPC autonomy rules fire in
observable, deterministic ways.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine


TINY_CASE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "tiny_detective_case_v0_1.json"
MEDIUM_CASE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "medium_detective_case_v0_1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "scripts" / "eval_outputs"

SUPPORTED_TRIGGERS = {
    "after_any_player_action",
    "after_search",
    "after_ask",
    "after_confront",
    "search",
    "ask",
    "confront",
}
SUPPORTED_ACTION_TYPES = {
    "stay",
    "move_to_scene",
    "change_stance",
    "raise_stress",
    "redirect_suspicion",
    "ask_player_question",
    "withdraw",
}
SUPPORTED_CONDITIONS = {
    "phase_id_is",
    "phase_type_is",
    "area_id_is",
    "target_character_id_is",
    "character_id_is",
    "evidence_id_is",
    "result_code_is",
    "npc_stance_is",
    "npc_location_scene_id_is",
    "min_stress",
    "max_stress",
    "discovered_evidence_ids_all",
    "discovered_evidence_ids_any",
    "broken_lie_ids_all",
    "broken_lie_ids_any",
    "new_evidence_ids_all",
    "new_evidence_ids_any",
    "new_broken_lie_ids_all",
    "new_broken_lie_ids_any",
}
SNAPSHOT_LIST_FIELDS = (
    "unlocked_scene_ids",
    "searched_scene_ids",
    "discovered_evidence_ids",
    "shown_evidence_ids",
    "unlocked_truth_ids",
    "broken_lie_ids",
    "asked_character_ids",
)
FORBIDDEN_REPORT_MARKERS = (
    "private_profile",
    "culprit_character_id",
    "action_profile",
    "directive",
)


class LimitedNPCActor:
    """Cap real LLM calls during optional evaluation."""

    def __init__(self, actor: Any, max_turns: int):
        self.actor = actor
        self.max_turns = max(0, int(max_turns))
        self.call_count = 0

    def render_response(self, context: dict[str, Any], deterministic_message: str) -> str:
        if self.call_count >= self.max_turns:
            raise RuntimeError("llm_eval_turn_limit_reached")
        self.call_count += 1
        return self.actor.render_response(context, deterministic_message)


def resolve_case_path(case_name_or_path: str) -> Path:
    if case_name_or_path == "tiny":
        return TINY_CASE_PATH
    if case_name_or_path == "medium":
        return MEDIUM_CASE_PATH
    path = Path(case_name_or_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def make_engine(case_path: Path, *, llm_eval: bool = False, max_llm_turns: int = 8) -> DetectiveGameEngine:
    npc_actor = None
    if llm_eval:
        from detective_llm_actor import OpenAINPCActor

        npc_actor = LimitedNPCActor(OpenAINPCActor.from_env(), max_llm_turns)
    return DetectiveGameEngine(case_path, npc_actor=npc_actor)


def run_command(engine: DetectiveGameEngine, command: str, turns: list[dict[str, Any]]) -> Any:
    before = engine.get_progress_snapshot()
    result = engine.handle_command_result(command)
    after = engine.get_progress_snapshot()
    turns.append(build_turn_record(command, result, before, after))
    return result


def build_turn_record(command: str, result: Any, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    data = result.data or {}
    return {
        "turn_index": result.turn_index,
        "command": command,
        "action": result.action,
        "code": result.code,
        "ok": result.ok,
        "phase_id": result.phase_id,
        "target_id": result.target_id,
        "new_evidence_ids": list(result.new_evidence_ids),
        "new_truth_ids": list(result.new_truth_ids),
        "new_broken_lie_ids": list(result.new_broken_lie_ids),
        "new_unlocked_scene_ids": list(result.new_unlocked_scene_ids),
        "score_delta": result.score_delta,
        "actor_mode": str(data.get("actor_mode", "")),
        "actor_error": str(data.get("actor_error", "")),
        "npc_events": sanitize_visible_events(data.get("npc_events", [])),
        "npc_action_policies": sanitize_npc_action_policies(data.get("npc_action_policies", [])),
        "snapshot_hash_before": snapshot_hash(before),
        "snapshot_hash_after": snapshot_hash(after),
        "snapshot_delta": snapshot_delta(before, after),
        "npc_runtime_state": deepcopy(after.get("npc_runtime_state", {})),
    }


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    stable = {
        "current_phase_id": snapshot.get("current_phase_id"),
        "unlocked_scene_ids": snapshot.get("unlocked_scene_ids", []),
        "searched_scene_ids": snapshot.get("searched_scene_ids", []),
        "discovered_evidence_ids": snapshot.get("discovered_evidence_ids", []),
        "shown_evidence_ids": snapshot.get("shown_evidence_ids", []),
        "clue_state_by_id": snapshot.get("clue_state_by_id", {}),
        "unlocked_truth_ids": snapshot.get("unlocked_truth_ids", []),
        "broken_lie_ids": snapshot.get("broken_lie_ids", []),
        "npc_runtime_state": snapshot.get("npc_runtime_state", {}),
        "game_over": snapshot.get("game_over"),
        "won": snapshot.get("won"),
        "wrong_accusations": snapshot.get("wrong_accusations", 0),
    }
    blob = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def snapshot_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for field in SNAPSHOT_LIST_FIELDS:
        before_values = set(before.get(field, []) or [])
        after_values = set(after.get(field, []) or [])
        gained = sorted(after_values - before_values)
        if gained:
            delta[field] = gained
    clue_changes = {}
    before_clues = before.get("clue_state_by_id", {}) or {}
    after_clues = after.get("clue_state_by_id", {}) or {}
    for clue_id in sorted(set(before_clues) | set(after_clues)):
        if before_clues.get(clue_id) != after_clues.get(clue_id):
            clue_changes[clue_id] = {
                "from": before_clues.get(clue_id, ""),
                "to": after_clues.get(clue_id, ""),
            }
    if clue_changes:
        delta["clue_state_changes"] = clue_changes
    npc_changes = {}
    before_runtime = before.get("npc_runtime_state", {}) or {}
    after_runtime = after.get("npc_runtime_state", {}) or {}
    for npc_id in sorted(set(before_runtime) | set(after_runtime)):
        changed = {}
        before_state = before_runtime.get(npc_id, {}) or {}
        after_state = after_runtime.get(npc_id, {}) or {}
        for key in sorted(set(before_state) | set(after_state)):
            if before_state.get(key) != after_state.get(key):
                changed[key] = {
                    "from": before_state.get(key, ""),
                    "to": after_state.get(key, ""),
                }
        if changed:
            npc_changes[npc_id] = changed
    if npc_changes:
        delta["npc_runtime_changes"] = npc_changes
    before_history = before.get("npc_action_history", []) or []
    after_history = after.get("npc_action_history", []) or []
    new_actions = after_history[len(before_history):]
    if new_actions:
        delta["new_npc_action_rules"] = [
            rule_ref(action)
            for action in new_actions
            if isinstance(action, dict) and action.get("rule_id")
        ]
    return delta


def sanitize_visible_events(events: Any) -> list[dict[str, Any]]:
    sanitized = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        sanitized.append(
            {
                "turn_index": event.get("turn_index", 0),
                "npc_id": event.get("npc_id", ""),
                "rule_id": event.get("rule_id", ""),
                "action_type": event.get("action_type", ""),
                "source_action": event.get("source_action", ""),
                "text": event.get("text", ""),
            }
        )
    return sanitized


def sanitize_npc_action_policies(policies: Any) -> list[dict[str, Any]]:
    sanitized = []
    for policy in policies or []:
        if not isinstance(policy, dict):
            continue
        sanitized.append(
            {
                "turn_index": policy.get("turn_index", 0),
                "npc_id": policy.get("npc_id", ""),
                "rule_id": policy.get("rule_id", ""),
                "trigger": policy.get("trigger", ""),
                "action_type": policy.get("action_type", ""),
                "from_scene_id": policy.get("from_scene_id", ""),
                "to_scene_id": policy.get("to_scene_id", ""),
                "stance": policy.get("stance", ""),
                "stress": policy.get("stress", 0),
                "suspicion_target_id": policy.get("suspicion_target_id", ""),
                "visible_event": policy.get("visible_event", ""),
                "matched_conditions": sorted(policy.get("matched_conditions", []) or []),
                "failed_conditions": sorted(policy.get("failed_conditions", []) or []),
                "source_action": policy.get("source_action", ""),
                "reason": policy.get("reason", ""),
            }
        )
    return sanitized


def evaluate_case(
    case_path: Path,
    *,
    policy: str = "completion",
    llm_eval: bool = False,
    max_llm_turns: int = 8,
) -> dict[str, Any]:
    if policy == "all":
        reports = [
            evaluate_case(case_path, policy=item, llm_eval=llm_eval, max_llm_turns=max_llm_turns)
            for item in ("completion", "misled", "npc-autonomy")
        ]
        passed = all(item["summary"]["passed"] for item in reports)
        return {
            "summary": {
                "passed": passed,
                "case": case_path.name,
                "policy": "all",
                "turn_count": sum(item["summary"]["turn_count"] for item in reports),
                "score": None,
                "max_score": None,
                "won": None,
                "llm_eval": llm_eval,
                "oracle_note": "Aggregate of deterministic evaluator policies.",
            },
            "reports": reports,
            "risk_flags": sorted({flag for item in reports for flag in item.get("risk_flags", [])}),
        }

    engine = make_engine(case_path, llm_eval=llm_eval, max_llm_turns=max_llm_turns)
    turns: list[dict[str, Any]] = []
    lint_errors = lint_action_profiles(engine.schema)

    if policy == "completion":
        run_completion_policy(engine, turns)
    elif policy == "misled":
        run_misled_policy(engine, turns)
    elif policy == "npc-autonomy":
        run_npc_autonomy_policy(engine, turns)
    else:
        raise ValueError(f"Unknown evaluator policy: {policy}")

    snapshot = engine.get_progress_snapshot()
    coverage = build_coverage(engine.schema, snapshot)
    npc_report = build_npc_action_report(engine.schema, snapshot, lint_errors)
    risk_flags = build_risk_flags(policy, engine.schema, turns, snapshot, npc_report)
    summary = build_summary(case_path, policy, turns, snapshot, llm_eval)
    report = {
        "summary": summary,
        "coverage": coverage,
        "npc_action_report": npc_report,
        "risk_flags": risk_flags,
        "turns": turns,
    }
    report["risk_flags"] = sorted(set(risk_flags + scan_report_for_leaks(report)))
    report["summary"]["passed"] = report_passed(policy, report)
    return report


def run_completion_policy(engine: DetectiveGameEngine, turns: list[dict[str, Any]]) -> None:
    run_command(engine, "/status", turns)
    safety = 0
    while not engine.game_over and safety < 80:
        safety += 1
        progress = False

        for scene_id in sorted(engine.unlocked_scene_ids - engine.searched_scene_ids):
            result = run_command(engine, f"/search {scene_id}", turns)
            progress = progress or result.ok

        for evidence_id in sorted(engine.discovered_evidence_ids - engine.shown_evidence_ids):
            result = run_command(engine, f"/show {evidence_id}", turns)
            progress = progress or result.ok

        for character_id in sorted(engine.npcs_by_id):
            if character_id in engine.asked_character_ids:
                continue
            if not engine._is_npc_reachable(character_id):
                continue
            result = run_command(engine, f"/ask {character_id} What should I know right now?", turns)
            progress = progress or result.ok

        confronted = confront_all_breakable_lies(engine, turns)
        progress = progress or confronted
        if not progress:
            break

    if not engine.game_over:
        run_command(engine, build_oracle_accusation_command(engine.schema), turns)


def confront_all_breakable_lies(engine: DetectiveGameEngine, turns: list[dict[str, Any]]) -> bool:
    progress = False
    for lie_id, lie in sorted(engine.lies_by_id.items()):
        if lie_id in engine.broken_lie_ids:
            continue
        character_id = lie.get("character_id", "")
        if not character_id or not engine._is_npc_reachable(character_id):
            continue
        required = set(lie.get("required_evidence_ids", []) or [])
        if not required or not required.issubset(engine.discovered_evidence_ids):
            continue
        evidence_id = preferred_confront_evidence(engine, lie_id, required)
        if not evidence_id:
            continue
        result = run_command(engine, f"/confront {character_id} {evidence_id}", turns)
        progress = progress or result.ok
    return progress


def preferred_confront_evidence(engine: DetectiveGameEngine, lie_id: str, required: set[str]) -> str:
    discovered_required = sorted(required & engine.discovered_evidence_ids)
    for evidence_id in discovered_required:
        evidence = engine.evidence_by_id.get(evidence_id, {})
        if lie_id in (evidence.get("can_confront_lie_ids", []) or []):
            return evidence_id
    return discovered_required[0] if discovered_required else ""


def run_misled_policy(engine: DetectiveGameEngine, turns: list[dict[str, Any]]) -> None:
    run_command(engine, "/status", turns)
    case_id = engine.schema.get("game_info", {}).get("id", "")
    if case_id == "medium_detective_case_v0_1":
        commands = [
            "/search scene_atrium",
            "/show evidence_red_fiber",
            "/ask liam_chen Did your scarf leave the red fiber?",
            "/accuse liam_chen",
        ]
    else:
        culprit = expected_culprit_id(engine.schema)
        wrong_suspect = next((item for item in sorted(engine.npcs_by_id) if item != culprit), culprit)
        first_scene = sorted(engine.unlocked_scene_ids)[0]
        commands = [f"/search {first_scene}", f"/accuse {wrong_suspect}"]
    for command in commands:
        if engine.game_over and not command.startswith("/status"):
            break
        run_command(engine, command, turns)


def run_npc_autonomy_policy(engine: DetectiveGameEngine, turns: list[dict[str, Any]]) -> None:
    run_command(engine, "/status", turns)
    case_id = engine.schema.get("game_info", {}).get("id", "")
    if case_id == "medium_detective_case_v0_1":
        commands = [
            "/search scene_atrium",
            "/search scene_security",
            "/confront mira_sun evidence_camera_gap",
            "/search scene_rooftop",
            "/confront nova_park evidence_drone_receipt",
            "/confront arden_kai evidence_rooftop_keycard",
        ]
    else:
        commands = [f"/search {scene_id}" for scene_id in sorted(engine.unlocked_scene_ids)]
    for command in commands:
        if engine.game_over and not command.startswith("/status"):
            break
        run_command(engine, command, turns)


def build_oracle_accusation_command(schema: dict[str, Any]) -> str:
    culprit = expected_culprit_id(schema)
    truth_model = schema.get("truth_model", {}) or {}
    motive = truth_model.get("motive_truth_id", "")
    method = truth_model.get("method_truth_id", "")
    evidence_ids: set[str] = set()
    lie_ids: set[str] = set()
    for item in schema.get("accusation_rules", {}).get("scoring_items", []) or []:
        evidence_ids.update(item.get("expected_evidence_ids", []) or [])
        lie_ids.update(item.get("expected_lie_ids", []) or [])
    parts = [f"/accuse {culprit}"]
    if motive:
        parts.append(f"motive={motive}")
    if method:
        parts.append(f"method={method}")
    if evidence_ids:
        parts.append(f"evidence={','.join(sorted(evidence_ids))}")
    if lie_ids:
        parts.append(f"lies={','.join(sorted(lie_ids))}")
    return " ".join(parts)


def expected_culprit_id(schema: dict[str, Any]) -> str:
    for item in schema.get("accusation_rules", {}).get("scoring_items", []) or []:
        if item.get("field_id") == "culprit" and item.get("expected_character_id"):
            return str(item.get("expected_character_id"))
    return str((schema.get("truth_model", {}) or {}).get("culprit_character_id", ""))


def build_summary(
    case_path: Path,
    policy: str,
    turns: list[dict[str, Any]],
    snapshot: dict[str, Any],
    llm_eval: bool,
) -> dict[str, Any]:
    latest_accusation = snapshot.get("latest_accusation_result") or {}
    return {
        "passed": False,
        "case": case_path.name,
        "policy": policy,
        "turn_count": len(turns),
        "score": latest_accusation.get("score"),
        "max_score": latest_accusation.get("max_score"),
        "won": snapshot.get("won"),
        "game_over": snapshot.get("game_over"),
        "wrong_accusations": snapshot.get("wrong_accusations", 0),
        "llm_eval": llm_eval,
        "oracle_note": "completion uses schema answers to verify the case is runnable, not player intelligence.",
    }


def build_coverage(schema: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    fired_rules = sorted(rule_ref(item) for item in snapshot.get("npc_action_history", []) if item.get("rule_id"))
    return {
        "scenes": coverage_item(snapshot.get("searched_scene_ids", []), scene_ids(schema)),
        "evidence": coverage_item(snapshot.get("discovered_evidence_ids", []), evidence_ids(schema)),
        "truth": coverage_item(snapshot.get("unlocked_truth_ids", []), truth_ids(schema)),
        "lies": coverage_item(snapshot.get("broken_lie_ids", []), lie_ids(schema)),
        "npc_rules": coverage_item(fired_rules, all_npc_rule_refs(schema)),
        "clue_lifecycle": clue_lifecycle_coverage(schema, snapshot),
    }


def coverage_item(covered: Any, total: Any) -> dict[str, Any]:
    covered_ids = sorted(set(covered or []))
    total_ids = sorted(set(total or []))
    missing_ids = sorted(set(total_ids) - set(covered_ids))
    ratio = 1.0 if not total_ids else round(len(set(covered_ids) & set(total_ids)) / len(total_ids), 4)
    return {
        "covered_ids": covered_ids,
        "total_ids": total_ids,
        "missing_ids": missing_ids,
        "ratio": ratio,
    }


def clue_lifecycle_coverage(schema: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    schema_state_by_id = {}
    for item in schema.get("evidence", []) or []:
        if not isinstance(item, dict) or not item.get("evidence_id"):
            continue
        lifecycle = item.get("lifecycle", {}) if isinstance(item.get("lifecycle"), dict) else {}
        schema_state_by_id[item["evidence_id"]] = lifecycle.get(
            "initial_state",
            "discovered" if item.get("initially_discovered") else "discoverable",
        )
    final_state_by_id = snapshot.get("clue_state_by_id", {}) or {}
    schema_states = sorted(set(schema_state_by_id.values()))
    final_states = sorted(set(final_state_by_id.values()))
    covered_states = sorted(set(schema_states) | set(final_states))
    expected_states = sorted(set(schema_states) | {"discovered", "revealed"})
    missing_states = sorted(set(expected_states) - set(covered_states))
    return {
        "schema_state_by_id": dict(sorted(schema_state_by_id.items())),
        "final_state_by_id": dict(sorted(final_state_by_id.items())),
        "schema_states": schema_states,
        "final_states": final_states,
        "covered_states": covered_states,
        "missing_states": missing_states,
        "ratio": 1.0 if not expected_states else round(len(set(covered_states) & set(expected_states)) / len(expected_states), 4),
    }


def build_npc_action_report(
    schema: dict[str, Any],
    snapshot: dict[str, Any],
    lint_errors: list[str],
) -> dict[str, Any]:
    action_history = [sanitize_npc_action_policies([item])[0] for item in snapshot.get("npc_action_history", [])]
    fired_rules = sorted(rule_ref(item) for item in action_history if item.get("rule_id"))
    fire_counts: dict[str, int] = {}
    for ref in fired_rules:
        fire_counts[ref] = fire_counts.get(ref, 0) + 1
    total_rules = all_npc_rule_refs(schema)
    scene_id_set = set(scene_ids(schema))
    invalid_locations = sorted(
        f"{character_id}:{state.get('location_scene_id', '')}"
        for character_id, state in (snapshot.get("npc_runtime_state", {}) or {}).items()
        if state.get("location_scene_id", "") and state.get("location_scene_id", "") not in scene_id_set
    )
    return {
        "fired_rules": fired_rules,
        "dead_rules": sorted(set(total_rules) - set(fired_rules)),
        "repeated_rules": sorted(ref for ref, count in fire_counts.items() if count > 1),
        "invalid_locations": invalid_locations,
        "visible_events": sanitize_visible_events(snapshot.get("visible_npc_events", [])),
        "runtime_final_state": deepcopy(snapshot.get("npc_runtime_state", {})),
        "action_history": action_history,
        "lint_errors": list(lint_errors),
    }


def build_risk_flags(
    policy: str,
    schema: dict[str, Any],
    turns: list[dict[str, Any]],
    snapshot: dict[str, Any],
    npc_report: dict[str, Any],
) -> list[str]:
    flags = []
    for error in npc_report.get("lint_errors", []):
        flags.append(f"action_profile_lint:{error}")
    if policy in {"completion", "npc-autonomy"}:
        for rule in npc_report.get("dead_rules", []):
            flags.append(f"dead_npc_rule:{rule}")
    for rule in npc_report.get("repeated_rules", []):
        flags.append(f"repeated_npc_rule:{rule}")
    for item in npc_report.get("invalid_locations", []):
        flags.append(f"npc_invalid_location:{item}")
    for turn in turns:
        if turn.get("actor_error", "").startswith("context_audit_failed"):
            flags.append(f"actor_audit_fallback:turn_{turn.get('turn_index')}")
        if turn.get("code") == "game_already_over" and not turn.get("command", "").startswith("/status"):
            flags.append(f"unexpected_game_over:turn_{turn.get('turn_index')}")
    return sorted(set(flags))


def scan_report_for_leaks(report: dict[str, Any]) -> list[str]:
    blob = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if any(marker in blob for marker in FORBIDDEN_REPORT_MARKERS):
        return ["hidden_info_marker_in_report"]
    return []


def report_passed(policy: str, report: dict[str, Any]) -> bool:
    summary = report["summary"]
    risk_flags = report.get("risk_flags", [])
    blocking_risks = [
        flag
        for flag in risk_flags
        if policy in {"completion", "npc-autonomy"} or not flag.startswith("dead_npc_rule:")
    ]
    if blocking_risks:
        return False
    if policy == "completion":
        return bool(summary["won"]) and summary["score"] == summary["max_score"]
    if policy == "misled":
        return bool(summary["game_over"]) and not bool(summary["won"]) and int(summary["wrong_accusations"] or 0) >= 1
    if policy == "npc-autonomy":
        return not report["npc_action_report"]["dead_rules"]
    return False


def lint_action_profiles(schema: dict[str, Any]) -> list[str]:
    errors = []
    seen_rule_ids: set[str] = set()
    ids = {
        "characters": set(character_ids(schema)),
        "scenes": set(scene_ids(schema)),
        "evidence": set(evidence_ids(schema)),
        "lies": set(lie_ids(schema)),
        "phases": set(phase_ids(schema)),
    }
    for npc in schema.get("npc_characters", []) or []:
        character_id = npc.get("character_id", "")
        profile = npc.get("action_profile", {}) or {}
        if not profile:
            continue
        initial_scene = profile.get("initial_location_scene_id", "")
        if initial_scene and initial_scene not in ids["scenes"]:
            errors.append(f"{character_id}:unknown_initial_scene:{initial_scene}")
        rules = profile.get("rules", []) or []
        if not isinstance(rules, list):
            errors.append(f"{character_id}:rules_not_list")
            continue
        for index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                errors.append(f"{character_id}:rule_{index}:not_object")
                continue
            rule_id = rule.get("rule_id", "")
            rule_label = f"{character_id}:{rule_id or f'rule_{index}'}"
            if not rule_id:
                errors.append(f"{rule_label}:missing_rule_id")
            elif rule_id in seen_rule_ids:
                errors.append(f"{rule_label}:duplicate_rule_id")
            seen_rule_ids.add(rule_id)
            if not isinstance(rule.get("priority", 0), int):
                errors.append(f"{rule_label}:priority_not_int")
            trigger = rule.get("trigger", "after_any_player_action")
            if trigger not in SUPPORTED_TRIGGERS:
                errors.append(f"{rule_label}:unsupported_trigger:{trigger}")
            for key in ("max_times", "cooldown_turns"):
                if key in rule and not is_nonnegative_int(rule.get(key)):
                    errors.append(f"{rule_label}:{key}_not_nonnegative_int")
            conditions = rule.get("conditions", {}) or {}
            if not isinstance(conditions, dict):
                errors.append(f"{rule_label}:conditions_not_object")
                conditions = {}
            for condition_key, condition_value in conditions.items():
                if condition_key not in SUPPORTED_CONDITIONS:
                    errors.append(f"{rule_label}:unsupported_condition:{condition_key}")
                    continue
                errors.extend(lint_condition_reference(rule_label, condition_key, condition_value, ids))
            action = rule.get("action", {}) or {}
            if not isinstance(action, dict):
                errors.append(f"{rule_label}:action_not_object")
                action = {}
            action_type = action.get("type", "stay")
            if action_type not in SUPPORTED_ACTION_TYPES:
                errors.append(f"{rule_label}:unsupported_action_type:{action_type}")
            target_scene = action.get("target_scene_id", "")
            if target_scene and target_scene not in ids["scenes"]:
                errors.append(f"{rule_label}:unknown_target_scene:{target_scene}")
            for target_key in ("target_character_id", "suspicion_target_id"):
                target_character = action.get(target_key, "")
                if target_character and target_character not in ids["characters"]:
                    errors.append(f"{rule_label}:unknown_{target_key}:{target_character}")
    return sorted(errors)


def lint_condition_reference(
    rule_label: str,
    key: str,
    value: Any,
    ids: dict[str, set[str]],
) -> list[str]:
    errors = []
    values = as_list(value)
    if key in {"area_id_is", "npc_location_scene_id_is"}:
        errors.extend(
            f"{rule_label}:unknown_scene_ref:{item}"
            for item in values
            if item not in ids["scenes"]
        )
    if key in {"target_character_id_is", "character_id_is"}:
        errors.extend(
            f"{rule_label}:unknown_character_ref:{item}"
            for item in values
            if item not in ids["characters"]
        )
    if key == "evidence_id_is" or key.startswith("discovered_evidence_ids_") or key.startswith("new_evidence_ids_"):
        errors.extend(
            f"{rule_label}:unknown_evidence_ref:{item}"
            for item in values
            if item not in ids["evidence"]
        )
    if key.startswith("broken_lie_ids_") or key.startswith("new_broken_lie_ids_"):
        errors.extend(
            f"{rule_label}:unknown_lie_ref:{item}"
            for item in values
            if item not in ids["lies"]
        )
    if key == "phase_id_is":
        errors.extend(
            f"{rule_label}:unknown_phase_ref:{item}"
            for item in values
            if item not in ids["phases"]
        )
    if key in {"min_stress", "max_stress"} and not is_nonnegative_int(value):
        errors.append(f"{rule_label}:{key}_not_nonnegative_int")
    return errors


def is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and value >= 0


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def all_npc_rule_refs(schema: dict[str, Any]) -> list[str]:
    refs = []
    for npc in schema.get("npc_characters", []) or []:
        character_id = npc.get("character_id", "")
        profile = npc.get("action_profile", {}) or {}
        for rule in profile.get("rules", []) or []:
            if isinstance(rule, dict) and rule.get("rule_id"):
                refs.append(f"{character_id}:{rule.get('rule_id')}")
    return sorted(refs)


def rule_ref(item: dict[str, Any]) -> str:
    return f"{item.get('npc_id', '')}:{item.get('rule_id', '')}"


def character_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(item.get("character_id", "") for item in schema.get("npc_characters", []) or [] if item.get("character_id"))


def scene_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(item.get("scene_id", "") for item in schema.get("scenes", []) or [] if item.get("scene_id"))


def evidence_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(item.get("evidence_id", "") for item in schema.get("evidence", []) or [] if item.get("evidence_id"))


def lie_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(item.get("lie_id", "") for item in schema.get("lies", []) or [] if item.get("lie_id"))


def truth_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(
        item.get("truth_id", "")
        for item in (schema.get("truth_model", {}) or {}).get("truth_nodes", []) or []
        if item.get("truth_id")
    )


def phase_ids(schema: dict[str, Any]) -> list[str]:
    return sorted(item.get("phase_id", "") for item in schema.get("phases", []) or [] if item.get("phase_id"))


def print_text_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    status = "PASS" if summary["passed"] else "FAIL"
    print(f"[{status}] case={summary['case']} policy={summary['policy']} turns={summary['turn_count']}")
    print(f"score={summary.get('score')}/{summary.get('max_score')} won={summary.get('won')} llm_eval={summary.get('llm_eval')}")
    if report.get("risk_flags"):
        print("risk_flags:")
        for flag in report["risk_flags"]:
            print(f"- {flag}")
    if "coverage" in report:
        print("coverage:")
        for name, item in report["coverage"].items():
            if "covered_ids" in item:
                print(f"- {name}: {len(item['covered_ids'])}/{len(item['total_ids'])} ratio={item['ratio']}")
            else:
                print(f"- {name}: states={','.join(item.get('covered_states', [])) or 'none'} ratio={item.get('ratio')}")
    if "npc_action_report" in report:
        npc_report = report["npc_action_report"]
        print("npc rules:")
        print(f"- fired: {', '.join(npc_report['fired_rules']) or 'none'}")
        print(f"- dead: {', '.join(npc_report['dead_rules']) or 'none'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a DetectiveGameEngine v0.1 case offline.")
    parser.add_argument("--case", default="medium", help="Case alias tiny|medium or a schema JSON path.")
    parser.add_argument(
        "--policy",
        default="completion",
        choices=["completion", "misled", "npc-autonomy", "all"],
        help="Auto-player policy to run.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    parser.add_argument("--output", default="", help="Optional JSON report output path.")
    parser.add_argument("--llm-eval", action="store_true", help="Use the real OpenAI-compatible actor for sampled turns.")
    parser.add_argument("--max-llm-turns", type=int, default=8, help="Maximum real LLM actor calls when --llm-eval is set.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    case_path = resolve_case_path(args.case)
    report = evaluate_case(case_path, policy=args.policy, llm_eval=args.llm_eval, max_llm_turns=args.max_llm_turns)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text_report(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
