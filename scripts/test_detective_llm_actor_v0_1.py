"""Tests for the optional DetectiveGameEngine NPC actor layer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine


EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "tiny_detective_case_v0_1.json"


class CaptureActor:
    def __init__(self):
        self.contexts: list[dict[str, Any]] = []
        self.messages: list[str] = []

    def render_response(self, context: dict[str, Any], deterministic_message: str) -> str:
        self.contexts.append(context)
        self.messages.append(deterministic_message)
        name = context["self_view"]["display_name"]
        return f"{name}: [AI actor] I will answer within the evidence you have shown me."


class FailingActor:
    def render_response(self, context: dict[str, Any], deterministic_message: str) -> str:
        raise RuntimeError("actor unavailable")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def test_actor_receives_limited_context_and_preserves_judge_result() -> None:
    actor = CaptureActor()
    engine = DetectiveGameEngine(EXAMPLE_PATH, npc_actor=actor)
    engine.search_result("scene_lobby")
    result = engine.ask_result("qin_yu", "Did you leave the monitoring room?")
    snapshot = engine.get_progress_snapshot()

    assert_equal(result.code, "ask_ok", "actor must not change judge result code")
    assert_equal(result.new_broken_lie_ids, [], "ask should not break lies")
    assert_equal(result.data["actor_mode"], "llm", "actor mode should be llm")
    assert_true("[AI actor]" in result.message, "actor response should replace template text")
    assert_equal(len(actor.contexts), 1, "actor should be called once")

    context = actor.contexts[0]
    assert_equal(context["viewer_character_id"], "qin_yu", "context should identify viewer NPC")
    assert_equal(context["interaction_type"], "ask", "ask context should mark ask interaction")
    assert_true("case_public" in context, "context should include public case packet")
    assert_true("self_view" in context, "context should include self view")
    assert_true("other_characters_public" in context, "context should include public summaries of other NPCs")
    assert_true("player_known" in context, "context should include player-known state")
    assert_true("npc_runtime" in context, "context should include NPC runtime state")
    assert_true("selected_action_policy" in context, "context should include selected action policy")
    assert_true("discovered_evidence" in context["player_known"], "player-known evidence missing")
    context_blob = json.dumps(context, ensure_ascii=False, sort_keys=True)
    assert_true("private_profile" not in context_blob, "actor context must not include private_profile")
    assert_true("action_profile" not in context_blob, "actor context must not include full action profile")
    assert_true("culprit_character_id" not in context_blob, "actor context must not include culprit field")
    assert_true("truth_culprit_lin" not in context_blob, "actor context must not include forbidden culprit truth id")
    assert_true("truth_security_gap" not in context_blob, "ask context should not include unbroken lie truth")
    assert_true("evidence_security_log" not in context_blob, "actor context must not include hidden evidence")
    assert_true("lie_qin_no_gap" in context_blob, "actor context should include active lie")
    assert_true("evidence_visit_log" in context_blob, "actor context should include discovered evidence")

    history = snapshot["conversation_history_by_character"]["qin_yu"]
    assert_equal(history[0]["actor_mode"], "llm", "conversation history should record actor mode")
    assert_equal(history[0]["result_code"], "ask_ok", "conversation history should record judge result")
    print("[PASS] actor limited context and judge preservation")


def test_actor_failure_falls_back_to_template() -> None:
    engine = DetectiveGameEngine(EXAMPLE_PATH, npc_actor=FailingActor())
    result = engine.ask_result("lin_wei", "What about the contract?")
    snapshot = engine.get_progress_snapshot()

    assert_equal(result.code, "ask_ok", "fallback must keep judge result code")
    assert_equal(result.data["actor_mode"], "fallback", "actor failure should be marked as fallback")
    assert_true("actor unavailable" in result.data["actor_error"], "actor error should be recorded")
    assert_true("Ask:" in result.message, "fallback should use deterministic template response")
    assert_equal(snapshot["conversation_history_by_character"]["lin_wei"][0]["actor_mode"], "fallback", "history should record fallback")
    print("[PASS] actor failure fallback")


def test_actor_handles_confront_context() -> None:
    actor = CaptureActor()
    engine = DetectiveGameEngine(EXAMPLE_PATH, npc_actor=actor)
    engine.search_result("scene_lobby")
    result = engine.confront_result("qin_yu", "evidence_visit_log")
    snapshot = engine.get_progress_snapshot()

    assert_equal(result.code, "confront_lie_broken", "actor must not change confront judge result")
    assert_equal(result.new_broken_lie_ids, ["lie_qin_no_gap"], "actor must not change confront broken lie ids")
    assert_equal(result.data["actor_mode"], "llm", "confront actor mode should be llm")
    context = actor.contexts[0]
    assert_equal(context["viewer_character_id"], "qin_yu", "confront context should identify viewer NPC")
    assert_equal(context["interaction_type"], "confront", "actor context should mark confront interaction")
    assert_equal(context["presented_evidence"]["evidence_id"], "evidence_visit_log", "presented evidence missing")
    assert_equal(context["judge_result"]["code"], "confront_lie_broken", "judge result code missing")
    assert_equal(context["broken_lies_this_turn"][0]["lie_id"], "lie_qin_no_gap", "broken lie packet missing")

    context_blob = json.dumps(context, ensure_ascii=False, sort_keys=True)
    assert_true("private_profile" not in context_blob, "confront actor context must not include private_profile")
    assert_true("culprit_character_id" not in context_blob, "confront actor context must not include culprit field")
    assert_true("truth_culprit_lin" not in context_blob, "confront actor context must not include forbidden culprit truth id")
    assert_true("evidence_security_log" not in context_blob, "confront actor context must not include hidden evidence")
    assert_true("lie_qin_no_gap" in context_blob, "confront actor context should include broken lie")
    assert_equal(snapshot["conversation_history_by_character"]["qin_yu"][0]["result_code"], "confront_lie_broken", "history should record confront result")
    print("[PASS] actor confront context")


def test_actor_context_audit_blocks_leaks() -> None:
    actor = CaptureActor()
    engine = DetectiveGameEngine(EXAMPLE_PATH, npc_actor=actor)
    malicious_context = {
        "viewer_character_id": "qin_yu",
        "interaction_type": "ask",
        "self_view": {"display_name": "秦雨"},
        "private_profile": "leaked private card",
    }

    response, actor_data = engine._render_npc_actor_response(malicious_context, "template response")

    assert_equal(response, "template response", "audit fallback should preserve deterministic response")
    assert_equal(actor_data["actor_mode"], "fallback", "audit failure should force fallback")
    assert_true(actor_data["actor_error"].startswith("context_audit_failed:"), "audit reason should be recorded")
    assert_equal(len(actor.contexts), 0, "actor must not be called when context audit fails")
    print("[PASS] actor context audit blocks leaks")


def main() -> None:
    test_actor_receives_limited_context_and_preserves_judge_result()
    test_actor_failure_falls_back_to_template()
    test_actor_handles_confront_context()
    test_actor_context_audit_blocks_leaks()
    print("[PASS] DetectiveGameEngine LLM actor test suite")


if __name__ == "__main__":
    main()
