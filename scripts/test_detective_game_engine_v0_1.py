"""Smoke tests for the minimal DetectiveGameEngine v0.1 runtime."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import ActionResult, DetectiveGameEngine


EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "tiny_detective_case_v0_1.json"
MEDIUM_EXAMPLE_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "medium_detective_case_v0_1.json"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def make_engine() -> DetectiveGameEngine:
    return DetectiveGameEngine(EXAMPLE_PATH)


def make_medium_engine() -> DetectiveGameEngine:
    return DetectiveGameEngine(MEDIUM_EXAMPLE_PATH)


def test_status_initial_state() -> None:
    engine = make_engine()
    result = engine.status_result()
    snapshot = engine.get_progress_snapshot()

    assert_true(isinstance(result, ActionResult), "status_result should return ActionResult")
    assert_equal(result.code, "status_ok", "status result code mismatch")
    assert_equal(result.phase_id, "phase_intro", "initial phase missing from status result")
    assert_true("phase_intro" in result.message, "status message should remain useful for CLI")
    assert_true("scene_lobby" in snapshot["unlocked_scene_ids"], "lobby should be initially unlocked")
    assert_true("scene_archive" in snapshot["unlocked_scene_ids"], "archive should be initially unlocked")
    assert_equal(snapshot["discovered_evidence_ids"], [], "initial discovered evidence should be empty")
    assert_equal(snapshot["turn_index"], 1, "status should be recorded as an action")
    assert_equal(snapshot["last_action_result"]["code"], "status_ok", "last action result not recorded")
    print("[PASS] initial status")


def test_search_and_show_results() -> None:
    engine = make_engine()
    search = engine.search_result("scene_lobby")
    snapshot = engine.get_progress_snapshot()

    assert_equal(search.code, "search_found_evidence", "search should reveal evidence")
    assert_equal(search.new_evidence_ids, ["evidence_visit_log"], "search new evidence mismatch")
    assert_true("evidence_visit_log" in snapshot["discovered_evidence_ids"], "visit log not recorded")
    assert_true("scene_lobby" in snapshot["searched_scene_ids"], "searched scene not recorded")
    assert_equal(snapshot["current_phase_id"], "phase_investigation", "search should advance intro phase")

    shown = engine.show_result("evidence_visit_log")
    snapshot = engine.get_progress_snapshot()
    assert_equal(shown.code, "show_ok", "show should succeed for discovered evidence")
    assert_true("evidence_visit_log" in snapshot["shown_evidence_ids"], "shown evidence not recorded")

    hidden = engine.show_result("evidence_security_log")
    assert_equal(hidden.code, "show_hidden_evidence", "hidden evidence should not be visible")
    assert_true(not hidden.ok, "hidden evidence result should fail")
    print("[PASS] search and show results")


def test_ask_is_plain_dialogue() -> None:
    engine = make_engine()
    engine.search_result("scene_lobby")
    reply = engine.ask_result("qin_yu", "Did you leave the monitoring room?")
    snapshot = engine.get_progress_snapshot()

    assert_equal(reply.code, "ask_ok", "ask should remain plain dialogue")
    assert_equal(reply.new_broken_lie_ids, [], "ask should not break lies")
    assert_true("lie_qin_no_gap" not in snapshot["broken_lie_ids"], "ask should not record broken lies")
    assert_equal(snapshot["current_phase_id"], "phase_investigation", "ask should not unlock confrontation phase")
    assert_true("scene_office" not in snapshot["unlocked_scene_ids"], "ask should not unlock office scene")
    assert_true("qin_yu" in snapshot["asked_character_ids"], "asked character not recorded")
    print("[PASS] ask is plain dialogue")


def test_confront_breaks_lie_and_handles_failures() -> None:
    engine = make_engine()
    engine.search_result("scene_lobby")
    reply = engine.confront_result("qin_yu", "evidence_visit_log")
    snapshot = engine.get_progress_snapshot()

    assert_equal(reply.code, "confront_lie_broken", "confront should break Qin's lie with visit log")
    assert_equal(reply.new_broken_lie_ids, ["lie_qin_no_gap"], "confront broken lie result mismatch")
    assert_true("lie_qin_no_gap" in snapshot["broken_lie_ids"], "confront broken lie not recorded")
    assert_equal(snapshot["current_phase_id"], "phase_confrontation", "confront should unlock confrontation phase")
    assert_true("scene_office" in snapshot["unlocked_scene_ids"], "confront should unlock office scene")

    repeated = engine.confront_result("qin_yu", "evidence_visit_log")
    assert_equal(repeated.code, "confront_lie_already_broken", "repeated confront should be stable")
    assert_true(not repeated.ok, "repeated confront should not be a successful new break")

    engine = make_engine()
    hidden = engine.confront_result("lin_wei", "evidence_security_log")
    assert_equal(hidden.code, "confront_hidden_evidence", "hidden evidence should not be usable for confront")
    assert_true(not hidden.ok, "hidden evidence confront should fail")

    engine.search_result("scene_archive")
    mismatch = engine.confront_result("xu_mo", "evidence_contract")
    assert_equal(mismatch.code, "confront_no_matching_lie", "evidence should not break an unrelated NPC lie")
    assert_true(not mismatch.ok, "mismatched confront should fail")
    print("[PASS] confront breaks lie and handles failures")


def test_office_search_and_lin_lie() -> None:
    engine = make_engine()
    engine.search_result("scene_lobby")
    engine.confront_result("qin_yu", "evidence_visit_log")

    office_reply = engine.search_result("scene_office")
    assert_equal(
        office_reply.new_evidence_ids,
        ["evidence_security_log", "evidence_tea_cup"],
        "office search did not reveal expected evidence",
    )

    ask_reply = engine.ask_result("lin_wei", "Did you enter the office?")
    assert_equal(ask_reply.code, "ask_ok", "Lin ask should not break a lie")

    confront_reply = engine.confront_result("lin_wei", "evidence_security_log")
    snapshot = engine.get_progress_snapshot()
    assert_equal(confront_reply.code, "confront_lie_broken", "Lin's lie should break after security log is confronted")
    assert_true("lie_lin_archive_alibi" in snapshot["broken_lie_ids"], "Lin's broken lie not recorded")
    print("[PASS] office search and Lin lie")


def test_accuse_correct_and_wrong() -> None:
    engine = make_engine()
    correct = engine.accuse_result("lin_wei")
    snapshot = engine.get_progress_snapshot()

    assert_equal(correct.code, "accuse_correct", "correct accusation not accepted")
    assert_true(correct.ok, "correct accusation should be ok")
    assert_equal(correct.data["score"], 3, "legacy accusation should score culprit only")
    assert_equal(correct.data["max_score"], 10, "structured accusation max score mismatch")
    assert_equal(correct.data["missing_required_fields"], ["motive", "method", "evidence_chain"], "legacy accusation should report missing structured fields")
    assert_equal(snapshot["current_phase_id"], "phase_recap", "recap phase not entered")
    assert_true(snapshot["game_over"], "game should be over after accusation")
    assert_true(snapshot["won"], "correct accusation should mark game won")
    assert_equal(snapshot["wrong_accusations"], 0, "correct accusation should not increment wrong count")
    assert_equal(snapshot["accusation_result"]["suspect_id"], "lin_wei", "accusation result missing suspect")

    blocked = engine.handle_command_result("/search scene_lobby")
    assert_equal(blocked.code, "game_already_over", "non-status command after game over should be blocked")
    assert_equal(engine.handle_command_result("/status").code, "status_ok", "status should still work after game over")

    engine = make_engine()
    wrong = engine.handle_command_result("/accuse xu_mo")
    snapshot = engine.get_progress_snapshot()
    assert_equal(wrong.code, "accuse_wrong", "wrong accusation not rejected")
    assert_true(snapshot["game_over"], "wrong accusation should still end game")
    assert_true(not snapshot["won"], "wrong accusation should not mark game won")
    assert_equal(snapshot["wrong_accusations"], 1, "wrong accusation count mismatch")
    assert_equal(len(snapshot["accusation_history"]), 1, "accusation history not recorded")
    print("[PASS] accuse correct and wrong")


def test_structured_accuse_scores_full_solution() -> None:
    engine = make_engine()
    engine.search_result("scene_archive")
    engine.search_result("scene_lobby")
    engine.confront_result("qin_yu", "evidence_visit_log")
    engine.search_result("scene_office")
    engine.confront_result("lin_wei", "evidence_security_log")

    result = engine.handle_command_result(
        "/accuse lin_wei "
        "motive=truth_motive_contract "
        "method=truth_poison_tea "
        "evidence=evidence_contract,evidence_security_log,evidence_tea_cup "
        "lies=lie_lin_archive_alibi"
    )
    snapshot = engine.get_progress_snapshot()

    assert_equal(result.code, "accuse_correct", "structured accusation should identify culprit")
    assert_equal(result.data["score"], 10, "structured accusation should earn full score")
    assert_equal(result.data["max_score"], 10, "structured accusation max score mismatch")
    assert_true(result.data["passed"], "structured accusation should pass")
    assert_true(result.data["perfect"], "structured accusation should be perfect")
    assert_equal(result.data["missing_required_fields"], [], "structured accusation should include required fields")
    assert_equal(snapshot["latest_accusation_result"]["score"], 10, "history should record structured score")
    print("[PASS] structured accuse scores full solution")


def test_npc_action_profile_runtime_and_events() -> None:
    engine = make_medium_engine()
    snapshot = engine.get_progress_snapshot()

    assert_equal(snapshot["npc_runtime_state"]["arden_kai"]["location_scene_id"], "scene_atrium", "Arden initial location mismatch")
    assert_equal(snapshot["npc_runtime_state"]["mira_sun"]["location_scene_id"], "scene_security", "Mira initial location mismatch")
    assert_true(engine._is_npc_reachable("mira_sun"), "Mira should be reachable from initial runtime location")

    result = engine.search_result("scene_security")
    snapshot = engine.get_progress_snapshot()
    event_text = " ".join(event["text"] for event in result.data["npc_events"])
    payload_text = str(result.data)

    assert_true("Mira" in event_text, "Mira visible event missing after security search")
    assert_true("Arden" in event_text, "Arden visible event missing after security search")
    assert_equal(snapshot["npc_runtime_state"]["mira_sun"]["stance"], "nervous", "Mira stance should update")
    assert_equal(snapshot["npc_runtime_state"]["mira_sun"]["stress"], 1, "Mira stress should rise")
    assert_equal(snapshot["npc_runtime_state"]["arden_kai"]["suspicion_target_id"], "liam_chen", "Arden should redirect suspicion")
    assert_true("directive" not in payload_text and "goal_id" not in payload_text, "visible NPC event data should not leak goals")

    engine.npc_runtime_state["mira_sun"]["location_scene_id"] = "scene_rooftop"
    assert_true(not engine._is_npc_reachable("mira_sun"), "runtime movement to locked scene should make NPC unreachable")
    print("[PASS] NPC action profile runtime and events")


def test_npc_action_profile_confront_policy() -> None:
    engine = make_medium_engine()
    engine.search_result("scene_security")
    engine.confront_result("mira_sun", "evidence_camera_gap")
    engine.search_result("scene_rooftop")
    result = engine.confront_result("arden_kai", "evidence_rooftop_keycard")
    snapshot = engine.get_progress_snapshot()

    assert_equal(result.code, "confront_lie_broken", "Arden confront should still break the lie")
    assert_equal(snapshot["npc_runtime_state"]["arden_kai"]["stance"], "cornered", "Arden stance should update after confront")
    assert_equal(snapshot["npc_runtime_state"]["arden_kai"]["location_scene_id"], "scene_atrium", "Arden should withdraw to atrium")
    assert_equal(result.data["selected_action_policy"]["rule_id"], "arden_withdraw_after_rooftop_confront", "selected action policy missing")
    assert_true(result.data["npc_events"], "Arden confront should expose a visible NPC event")
    print("[PASS] NPC action profile confront policy")


def test_command_router_and_compatibility_methods() -> None:
    engine = make_engine()
    assert_equal(engine.handle_command_result("/status").code, "status_ok", "status command failed")
    assert_equal(engine.handle_command_result("/search scene_archive").code, "search_found_evidence", "search command failed")
    assert_equal(engine.handle_command_result("/show evidence_contract").code, "show_ok", "show command failed")
    assert_equal(engine.handle_command_result("/ask lin_wei What about the contract?").code, "ask_ok", "ask command failed")
    assert_equal(engine.handle_command_result("/confront lin_wei evidence_contract").code, "confront_missing_required_evidence", "confront command failed")
    assert_equal(engine.handle_command_result("/dance").code, "command_unknown", "unknown command not handled")

    engine = make_engine()
    assert_true("Current phase" in engine.get_status_text(), "legacy status text failed")
    assert_true("evidence_visit_log" in engine.search("scene_lobby"), "legacy search text failed")
    assert_true("Evidence:" in engine.show("evidence_visit_log"), "legacy show text failed")
    assert_true("Ask:" in engine.ask("qin_yu", "Did you leave?"), "legacy ask text failed")
    assert_true("Confront:" in engine.confront("qin_yu", "evidence_visit_log"), "legacy confront text failed")
    print("[PASS] command router and compatibility")


def main() -> None:
    test_status_initial_state()
    test_search_and_show_results()
    test_ask_is_plain_dialogue()
    test_confront_breaks_lie_and_handles_failures()
    test_office_search_and_lin_lie()
    test_accuse_correct_and_wrong()
    test_structured_accuse_scores_full_solution()
    test_npc_action_profile_runtime_and_events()
    test_npc_action_profile_confront_policy()
    test_command_router_and_compatibility_methods()
    print("[PASS] DetectiveGameEngine v0.1 smoke test suite")


if __name__ == "__main__":
    main()
