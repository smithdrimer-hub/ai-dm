"""Offline acceptance checks for the fixed script Monsters Halloween Night.

Run from the repository root:
    python -B scripts/acceptance_monsters_halloween.py

This script intentionally avoids the real LLM API. It sets a dummy API key
before importing project modules, then uses FakeDMEngine to stub _call_model().
"""

from __future__ import annotations

import json
import io
import os
import pathlib
import sys
import time
from unittest.mock import patch


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# config.py requires an API key at import time, but these tests never call the API.
os.environ.setdefault("OPENAI_API_KEY", "acceptance-dummy-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1/acceptance-never-called")
os.environ.setdefault("OPENAI_MODEL", "acceptance-dummy-model")

import dm_engine as dm_module  # noqa: E402
from dm_engine import DMEngine  # noqa: E402


EMERGENT_SCHEMA = REPO_ROOT / "scripts" / "schema_examples" / "emergent_resolution_minimal.json"


PRE_CLUE_2_FORBIDDEN = [
    "钥匙",
]

PRE_ENDING_TRUTH_FORBIDDEN = [
    "犯人是狼",
    "真凶是狼",
    "真正的犯人是狼",
    "狼后来撬开",
    "狼把孩童",
    "狼在橱柜里发现孩童并将其吃掉",
    "女巫发现等候室里还有人类后，用钥匙把孩童藏",
    "孩童衣服的碎片",
]

LOW_SPOILER_HINT_MARKERS = [
    "讨论似乎",
    "卡住",
    "停滞",
    "提示",
    "时间线",
    "公开的线索",
    "公开的信息",
    "物件状态",
    "补给橱柜",
    "合页",
]


class FakeDMEngine(DMEngine):
    """DMEngine with deterministic local model behavior for acceptance tests."""

    def __init__(self, *args, **kwargs):
        self.model_call_count = 0
        super().__init__(*args, **kwargs)

    def _call_model(self, user_message: str):
        self.model_call_count += 1
        player_input = self._extract_player_input(user_message)
        input_eval = "ON_TOPIC"
        progress_signal = "UNCHANGED"
        dm_action = "SILENT"
        clean_content = ""

        if any(word in player_input for word in ("股票", "外卖", "天气", "电影票")):
            input_eval = "HARD_OFFTOPIC"
            dm_action = "SPEAK"
        elif any(word in player_input for word in ("没想法", "继续沉默", "没有新的内容", "嗯", "额")):
            progress_signal = "STALLED"
        elif any(word in player_input for word in ("18点", "19点", "20点", "22点", "看到", "进入", "离开", "时间线", "合页")):
            progress_signal = "PROGRESS"

        self._update_state_from_output("UNCHANGED", "UNCHANGED", input_eval, progress_signal)
        clean_content = self._apply_guardrail_response(clean_content, input_eval)
        self.messages.append({"role": "assistant", "content": clean_content or "[DM 本轮保持沉默]"})
        return "" if dm_action == "SILENT" else clean_content

    def _judge_player_honesty(self, conversation_history: str):
        if any(word in conversation_history for word in ("对不起", "抱歉", "坦白", "承认", "我们错了")):
            return "honest"
        return "dishonest"

    @staticmethod
    def _extract_player_input(user_message: str) -> str:
        marker = "【玩家输入】"
        if marker not in user_message:
            return user_message
        tail = user_message.split(marker, 1)[1]
        return tail.split("\n", 1)[0].strip()


class FakeApiAssistDMEngine(FakeDMEngine):
    """Fake the optional progress-assessment API while keeping normal LLM calls stubbed."""

    def __init__(self, api_replies: list[str]):
        self.api_replies = list(api_replies)
        self.api_assist_request_count = 0
        super().__init__()
        self.api_assist_enabled = True
        self.api_assist_max_calls = 10
        self.api_assist_cooldown_turns = 0

    def _request_api_assist(self, messages: list[dict]) -> str:
        self.api_assist_request_count += 1
        if not self.api_replies:
            return "{}"
        reply = self.api_replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def pass_line(name: str):
    print(f"[PASS] {name}")


def require(condition: bool, step: str, detail: str):
    if not condition:
        raise AssertionError(f"{step}: {detail}")


def assert_text(step: str, text: str):
    require(isinstance(text, str) and text.strip(), step, "DM output is empty")


def assert_no_forbidden(step: str, text: str, forbidden: list[str]):
    hits = [word for word in forbidden if word and word in text]
    if hits:
        snippet = text.replace("\n", " ")[:240]
        raise AssertionError(f"{step}: forbidden spoiler {hits} found in output: {snippet}")


def classify_hint_level(text: str) -> str:
    if "钥匙" in text or "合页" in text:
        return "L3"
    if "补给橱柜" in text or "公开的线索" in text or "公开的信息" in text or "物件状态" in text:
        return "L2"
    return "L1"


def assert_hint(step: str, text: str, allowed_levels: set[str]):
    assert_text(step, text)
    require(any(marker in text for marker in LOW_SPOILER_HINT_MARKERS), step, f"not recognized as a hint: {text[:160]}")
    level = classify_hint_level(text)
    require(level in allowed_levels, step, f"unexpected hint level {level}: {text[:160]}")
    return level


def start_discussion(dm: FakeDMEngine):
    opening = dm.start_game()
    assert_text("opening", opening)
    require(dm.game_phase == "opening_rules", "opening", f"phase={dm.game_phase}")
    rules = dm.chat("理解了")
    assert_text("rules confirmation", rules)
    require(dm.game_phase == "discussion", "rules confirmation", f"phase={dm.game_phase}")
    require(dm.designated_speaker == "狼", "rules confirmation", f"speaker={dm.designated_speaker}")
    return opening, rules


def test_basic_flow_smoke():
    dm = FakeDMEngine()
    start_discussion(dm)

    clue1 = dm.release_clue("clue_1")
    assert_text("/clue1", clue1)
    require("clue_1" in dm.released_clues, "/clue1", "clue_1 not released")
    require(dm.game_phase == "discussion", "/clue1", f"phase={dm.game_phase}")
    assert_no_forbidden("/clue1 before clue_2", clue1, PRE_CLUE_2_FORBIDDEN)

    clue2 = dm.release_clue("clue_2")
    assert_text("/clue2", clue2)
    require("clue_2" in dm.released_clues, "/clue2", "clue_2 not released")

    dm.search_system_enabled = True
    search = dm.chat("/search 垃圾桶")
    assert_text("/search", search)
    require(dm.player_search_history, "/search", "search history not recorded")

    vote = dm.start_vote()
    assert_text("/vote", vote)
    require(dm.game_phase == "vote", "/vote", f"phase={dm.game_phase}")
    require(dm.pending_voters == ["狼", "女巫", "吸血鬼", "木乃伊"], "/vote", f"pending={dm.pending_voters}")

    answer = "狼/孩子衣服碎片/女巫用钥匙把孩子藏进橱柜"
    for role in ["狼", "女巫", "吸血鬼", "木乃伊"]:
        reply = dm.chat(answer)
        assert_text(f"vote input {role}", reply)
    require(dm.game_phase == "owner_confrontation", "vote reveal", f"phase={dm.game_phase}")

    round1 = dm.chat("我们愿意坦白，孩子确实是在我们的疏忽下出事的。")
    assert_text("owner confrontation round1", round1)
    require(dm.game_phase == "owner_confrontation", "owner confrontation round1", f"phase={dm.game_phase}")

    ending = dm.chat("对不起，我们错了，我们承认责任，也愿意向业主道歉。")
    assert_text("ending", ending)
    require(dm.game_phase == "postgame_review", "ending", f"phase={dm.game_phase}")
    require("复盘阶段已开启" in ending, "ending", "review prompt missing")

    review = dm.chat("/review")
    assert_text("/review", review)
    require("完整复盘" in review, "/review", "review title missing")
    pass_line("basic flow smoke")


def test_timed_clue_smoke():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.discussion_started_at = time.time() - 11 * 60
    replies = dm.poll_timed_events()
    require(replies, "timed clue1", "no timed event returned")
    require("clue_1" in dm.released_clues, "timed clue1", "clue_1 not released")
    assert_no_forbidden("timed clue1 before clue_2", "\n".join(replies), PRE_CLUE_2_FORBIDDEN)

    dm.discussion_started_at = time.time() - 21 * 60
    replies = dm.poll_timed_events()
    require(any("线索公开" in reply for reply in replies), "timed clue2", f"unexpected replies={replies}")
    require("clue_2" in dm.released_clues, "timed clue2", "clue_2 not released")
    pass_line("timed clue smoke")


def test_normal_progress_no_hint():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.designated_speaker = None
    statements = [
        "我在18点后进入等候室，看到木乃伊像是在找业主。",
        "我在20点前后经过等候室，注意到有人类的气息。",
        "我19点进入过等候室，看见角落里有人影。",
        "我22点回到等候室，屋里已经空了。",
    ]
    outputs = [dm.chat(statement) for statement in statements]
    noisy_outputs = [output for output in outputs if output.strip()]
    require(not noisy_outputs, "normal progress", f"DM interrupted unexpectedly: {noisy_outputs}")
    require(dm.stalled_turn_count == 0, "normal progress", f"stalled_turn_count={dm.stalled_turn_count}")
    pass_line("normal progress no interruption")


def test_semantic_progress_tracking():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.designated_speaker = None
    output = dm.chat("晚上七点吸血鬼到休息室，后来才跑掉；这个顺序和木乃伊先带孩子进屋是能接上的。")
    require(output == "", "semantic progress", f"DM interrupted unexpectedly: {output}")
    snapshot = dm.get_progress_snapshot()
    require(snapshot["new_info_detected"], "semantic progress", f"snapshot={snapshot}")
    require("time_19" in snapshot["semantic_tags"], "semantic progress", f"semantic_tags={snapshot['semantic_tags']}")
    require("location_waiting_room" in snapshot["semantic_tags"], "semantic progress", f"semantic_tags={snapshot['semantic_tags']}")
    require(snapshot["reasoning_threads"], "semantic progress", "reasoning thread not recorded")
    pass_line("semantic progress tracking")


def test_hint_silence_trigger_and_levels():
    dm = FakeDMEngine()
    start_discussion(dm)
    for text in ["额", "没有新的内容", "继续沉默"]:
        output = dm.chat(text)
        require(output == "", "stall setup", f"unexpected early output: {output}")
    hint = dm.chat("没想法")
    level = assert_hint("hint silence trigger L1", hint, {"L1"})
    require(level == "L1", "hint silence trigger L1", f"level={level}")
    assert_no_forbidden("hint L1 before clue_2", hint, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)

    dm2 = FakeDMEngine()
    start_discussion(dm2)
    clue1 = dm2.release_clue("clue_1")
    assert_no_forbidden("manual clue1 before clue_2", clue1, PRE_CLUE_2_FORBIDDEN)
    dm2.stalled_turn_count = dm2.STALLED_THRESHOLD
    early_after_clue = dm2.chat("继续沉默")
    require(early_after_clue == "", "hint after clue1 cooldown", f"unexpected early hint: {early_after_clue}")
    dm2.chat("没有新的内容")
    hint2 = dm2.chat("没想法")
    level2 = assert_hint("hint after clue1", hint2, {"L2", "L3"})
    require(level2 in {"L2", "L3"}, "hint after clue1", f"level={level2}")
    assert_no_forbidden("hint after clue1 before clue_2", hint2, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)
    pass_line("hint silence trigger")


def test_idle_timer_intervention():
    dm = FakeDMEngine()
    start_discussion(dm)
    now = time.time()
    dm.IDLE_INTERVENTION_SECONDS = 5
    dm.IDLE_INTERVENTION_COOLDOWN_SECONDS = 5

    dm.last_player_activity_at = now - 4
    early = dm.poll_idle_intervention(now=now)
    require(early == "", "idle timer early", f"unexpected early output: {early}")

    dm.last_player_activity_at = now - 6
    hint = dm.poll_idle_intervention(now=now)
    assert_hint("idle timer hint", hint, {"L1"})
    assert_no_forbidden("idle timer hint no spoiler", hint, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)

    repeated = dm.poll_idle_intervention(now=now + 1)
    require(repeated == "", "idle timer cooldown", f"cooldown failed: {repeated}")
    pass_line("idle timer intervention")


def test_legacy_load_does_not_count_offline_time():
    legacy_state = {
        "game_phase": "discussion",
        "opening_step": 5,
        "designated_speaker": "狼",
        "released_clues": [],
        "turn_count": 3,
        "discussion_started_at": time.time() - 3600,
        "case_memory": {
            "confirmed_facts": [],
            "open_questions": [],
            "player_claims": [],
            "contradictions": [],
            "summary_notes": [],
        },
    }
    dm = FakeDMEngine()
    payload = json.dumps(legacy_state, ensure_ascii=False)

    def fake_open(path, mode="r", encoding=None, *args, **kwargs):
        if str(path).endswith("offline_old_save.json") and "r" in mode:
            return io.StringIO(payload)
        raise AssertionError(f"unexpected file access in offline time test: {path}")

    with patch("builtins.open", fake_open):
        success, message = dm.load_game("offline_old_save")

    require(success, "legacy offline time", message)
    require(dm.game_phase == "discussion", "legacy offline time", f"phase={dm.game_phase}")
    require(dm.get_elapsed_discussion_minutes() <= 1, "legacy offline time", f"elapsed={dm.get_elapsed_discussion_minutes()}")
    pass_line("legacy offline time ignored")


def test_clue_attention_and_recent_event_suppression():
    dm = FakeDMEngine()
    start_discussion(dm)
    clue1 = dm.release_clue("clue_1")
    assert_no_forbidden("clue attention release", clue1, PRE_CLUE_2_FORBIDDEN)

    first = dm.chat("继续沉默")
    second = dm.chat("没有新的内容")
    require(first == "" and second == "", "clue recent suppression", f"unexpected early outputs: {first!r}, {second!r}")

    hint = dm.chat("没想法")
    assert_hint("ignored clue attention", hint, {"L2"})
    assert_no_forbidden("ignored clue attention no spoiler", hint, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)

    repeated = dm.chat("继续沉默")
    require(repeated == "", "clue attention cooldown", f"cooldown failed: {repeated}")
    pass_line("clue attention cooldown")


def test_search_success_suppresses_immediate_hint():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.search_system_enabled = True
    search = dm.chat("/search 补给橱柜")
    assert_text("search success suppression setup", search)
    require(dm.found_evidence, "search success suppression setup", "no evidence found")

    output = dm.chat("没想法")
    require(output == "", "search success suppression", f"unexpected immediate hint: {output}")
    pass_line("search success suppresses hint")


def test_vote_suggestion_only_suggests():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.designated_speaker = None
    dm.released_clues = ["clue_1", "clue_2"]
    dm._sync_clue_attention_state()
    dm.last_clue_release_turn = -999
    dm.covered_questions = ["culprit", "cabinet"]
    dm.stalled_score = dm.STALLED_THRESHOLD

    suggestion = dm.chat("没想法")
    assert_text("vote suggestion", suggestion)
    require("/vote" in suggestion, "vote suggestion", suggestion)
    require(dm.game_phase == "discussion", "vote suggestion", f"phase changed to {dm.game_phase}")
    assert_no_forbidden("vote suggestion no spoiler", suggestion, PRE_ENDING_TRUTH_FORBIDDEN)

    repeated = dm.chat("继续沉默")
    require(repeated == "", "vote suggestion cooldown", f"cooldown failed: {repeated}")
    pass_line("vote suggestion only")


def test_participation_cooldown():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.turn_count = dm.SILENCE_THRESHOLD
    dm.speaker_last_spoke = {role: 0 for role in dm.ROLE_NAMES}
    dm.speaker_turn_count = {role: 0 for role in dm.ROLE_NAMES}

    first = dm._check_participation()
    second = dm._check_participation()
    assert_text("participation first reminder", first)
    require(second is None, "participation cooldown", f"second reminder should be suppressed: {second}")
    pass_line("participation cooldown")


def test_api_assist_not_used_on_confident_progress():
    dm = FakeApiAssistDMEngine([
        '{"progress_health":"stalled","hint_needed":true,"hint_level":"L1","candidate_hint":"不该被调用","confidence":1}'
    ])
    start_discussion(dm)
    dm.designated_speaker = None
    output = dm.chat("我19点进入等候室，看到吸血鬼。")
    require(output == "", "api assist confident progress", f"unexpected DM output: {output}")
    require(dm.api_assist_request_count == 0, "api assist confident progress", f"api called {dm.api_assist_request_count}")
    pass_line("api assist skips confident progress")


def test_api_assist_candidate_hint_sanitized():
    dm = FakeApiAssistDMEngine([
        json.dumps({
            "intent": "stall",
            "progress_health": "stalled",
            "new_info_detected": False,
            "hint_needed": True,
            "hint_level": "L2",
            "candidate_hint": "[DM] 可以去想想钥匙到底在哪里，这会很关键。",
            "confidence": 0.92,
        }, ensure_ascii=False)
    ])
    start_discussion(dm)
    dm.designated_speaker = None
    output = dm.chat("这个情况太绕了，我现在完全接不上，也不知道下一步该怎么盘。")
    assert_hint("api assist sanitized hint", output, {"L1"})
    assert_no_forbidden("api assist sanitized no clue_2", output, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)
    require(dm.api_assist_request_count == 1, "api assist sanitized", f"api calls={dm.api_assist_request_count}")
    pass_line("api assist sanitized candidate")


def test_api_assist_bad_json_fallback():
    dm = FakeApiAssistDMEngine(["not-json"])
    start_discussion(dm)
    dm.designated_speaker = None
    output = dm.chat("我有点卡住了，但是这段话很长很绕，可能需要判断一下到底有没有进展。")
    require(isinstance(output, str), "api assist bad json", "output is not text")
    require(dm.api_assessment_fail_count >= 1, "api assist bad json", "fail count not recorded")
    require(dm.game_phase == "discussion", "api assist bad json", f"phase changed to {dm.game_phase}")
    assert_no_forbidden("api assist bad json no spoiler", output, PRE_CLUE_2_FORBIDDEN + PRE_ENDING_TRUTH_FORBIDDEN)
    pass_line("api assist bad json fallback")


def test_api_assist_failure_and_bad_fields_fallback():
    dm = FakeApiAssistDMEngine([TimeoutError("fake timeout")])
    start_discussion(dm)
    dm.designated_speaker = None
    output = dm.chat("这个表达很长但是我没有新的判断，只是在反复说自己接不上目前的讨论。")
    require(isinstance(output, str), "api assist exception", "output is not text")
    require(dm.api_assessment_fail_count >= 1, "api assist exception", "exception not recorded")
    require(dm.game_phase == "discussion", "api assist exception", f"phase changed to {dm.game_phase}")

    dm2 = FakeApiAssistDMEngine(['{"progress_health":"ENDING","hint_level":"L9","confidence":"bad"}'])
    start_discussion(dm2)
    dm2.designated_speaker = None
    output2 = dm2.chat("这个表达也很复杂，但是字段异常时应该继续走本地判断而不是崩溃。")
    require(isinstance(output2, str), "api assist bad fields", "output is not text")
    require(dm2.api_assessment_fail_count >= 1, "api assist bad fields", "bad fields not recorded")
    require(dm2.game_phase == "discussion", "api assist bad fields", f"phase changed to {dm2.game_phase}")
    pass_line("api assist failure fallback")


def test_spoiler_guardrails_on_guidance():
    dm = FakeDMEngine()
    start_discussion(dm)
    dm.stalled_turn_count = dm.STALLED_THRESHOLD
    hint = dm.chat("继续沉默")
    assert_no_forbidden("no spoiler before clue_2", hint, PRE_CLUE_2_FORBIDDEN)
    assert_no_forbidden("no truth before ending", hint, PRE_ENDING_TRUTH_FORBIDDEN)

    clue1 = dm.release_clue("clue_1")
    assert_no_forbidden("clue1 output before clue_2", clue1, PRE_CLUE_2_FORBIDDEN)
    dm.stalled_turn_count = dm.STALLED_THRESHOLD
    hint_after_clue1 = dm.chat("没想法")
    assert_no_forbidden("clue1 hint before clue_2", hint_after_clue1, PRE_CLUE_2_FORBIDDEN)
    assert_no_forbidden("clue1 hint no truth", hint_after_clue1, PRE_ENDING_TRUTH_FORBIDDEN)
    pass_line("no spoiler before clue_2")


def test_offtopic_pivot():
    dm = FakeDMEngine()
    start_discussion(dm)
    output = dm.chat("我们先聊聊股票和外卖吧")
    assert_text("offtopic pivot", output)
    require(any(word in output for word in ("回到", "正题", "案子", "真相", "时间线")), "offtopic pivot", output)
    assert_no_forbidden("offtopic pivot no truth", output, PRE_ENDING_TRUTH_FORBIDDEN)
    pass_line("offtopic gentle pivot")


def test_legacy_save_compatibility():
    legacy_state = {
        "game_phase": "discussion",
        "opening_step": 5,
        "designated_speaker": "狼",
        "released_clues": ["clue_1"],
        "turn_count": 3,
        "awaiting_speaker_confirmation": False,
        "pending_interrupt_guess": None,
        "consecutive_offtopic_count": 0,
        "last_input_eval": "ON_TOPIC",
        "stalled_turn_count": 0,
        "last_progress_signal": "UNCHANGED",
        "discussion_started_at": time.time() - 600,
        "auto_release_schedule": {"clue_1": 10, "clue_2": 20},
        "search_system_enabled": False,
        "found_evidence": [],
        "player_search_history": [],
        "search_cooldown_turns": {},
        "case_memory": {
            "confirmed_facts": [],
            "open_questions": [],
            "player_claims": [],
            "contradictions": [],
            "summary_notes": [],
        },
        "rolling_summary": "旧版存档摘要",
        "vote_submissions": {},
        "vote_answer_sheets": {},
        "pending_voters": [],
        "vote_result_summary": "",
        "answer_check_summary": "",
        "tied_roles": [],
        "awaiting_tie_resolution": False,
    }

    dm = FakeDMEngine()
    payload = json.dumps(legacy_state, ensure_ascii=False)

    def fake_open(path, mode="r", encoding=None, *args, **kwargs):
        if str(path).endswith("legacy_save.json") and "r" in mode:
            return io.StringIO(payload)
        raise AssertionError(f"unexpected file access in legacy save test: {path}")

    with patch("builtins.open", fake_open):
        success, message = dm.load_game("legacy_save")

    require(success, "legacy save compatibility", message)
    require(dm.game_phase == "discussion", "legacy save compatibility", f"phase={dm.game_phase}")
    require(getattr(dm, "ending_type", "") == "", "legacy save compatibility", f"ending_type={dm.ending_type}")
    require(getattr(dm, "review_presented", False) is False, "legacy save compatibility", "review_presented default changed")
    require(isinstance(dm.speaker_turn_count, dict), "legacy save compatibility", "speaker_turn_count missing")
    pass_line("legacy save compatibility")


def test_schema_shadow_mode_toggle():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        require(dm.schema_shadow_status == "loaded", "schema shadow on", f"status={dm.schema_shadow_status}")
        opening = dm.start_game()
        assert_text("schema opening", opening)
        require("规则说明" in opening, "schema opening", "schema public_materials not used")
        dm.chat("理解了")
        clue1 = dm.release_clue("clue_1")
        assert_text("schema clue reveal", clue1)
        require("补给橱柜的合页被破坏了" in clue1, "schema clue reveal", clue1[:180])
        hint = dm._generate_stall_guidance(level="L1")
        assert_hint("schema hint rule", hint, {"L1"})
        assert_no_forbidden("schema hint no early clue_2", hint, PRE_CLUE_2_FORBIDDEN)

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "0"}):
        dm = FakeDMEngine()
        require(dm.schema_shadow_status == "disabled", "schema shadow off", f"status={dm.schema_shadow_status}")
        start_discussion(dm)
        clue1 = dm.release_clue("clue_1")
        assert_text("schema off clue reveal", clue1)
        require(dm.game_phase == "discussion", "schema shadow off", f"phase={dm.game_phase}")

    pass_line("schema shadow mode toggle")


def test_second_sample_schema_runtime():
    second_schema = REPO_ROOT / "stories" / "second_sample" / "script_schema_v0_2_1.json"

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1", "AI_DM_SCRIPT_ID": "second_sample"}):
        dm = FakeDMEngine()
        require(dm.schema_shadow_status == "loaded", "second sample load", f"status={dm.schema_shadow_status}")
        require(dm.active_script_id == "second_sample", "second sample load", f"script_id={dm.active_script_id}")
        opening = dm.start_game()
        assert_text("second sample opening", opening)
        require("The Business of Murder" in opening, "second sample opening", opening[:180])
        rules = dm.chat("理解了")
        assert_text("second sample rules", rules)
        require("Louis Cagliostro" in rules, "second sample cast", rules[:240])
        require(dm.designated_speaker == "Louis Cagliostro", "second sample first speaker", f"speaker={dm.designated_speaker}")

        pre_clue_hint = dm._sanitize_hint_for_spoilers("The paperweight is important.", "L2")
        require("paperweight" not in pre_clue_hint.lower(), "second sample spoiler guard", pre_clue_hint)

        clue1 = dm.release_clue("clue_1")
        assert_text("second sample clue1", clue1)
        require("Clue #1: The Body" in clue1, "second sample clue1", clue1[:240])
        require("paperweight" not in clue1.lower(), "second sample clue1 no clue2", clue1[:240])

        clue2 = dm.release_clue("clue_2")
        assert_text("second sample clue2", clue2)
        require("paperweight" in clue2.lower(), "second sample clue2", clue2[:240])

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm_by_path = FakeDMEngine(schema_path=second_schema)
        require(dm_by_path.active_script_id == "second_sample", "second sample schema path", f"script_id={dm_by_path.active_script_id}")
        require("The Business of Murder" in dm_by_path.start_game(), "second sample schema path opening", "wrong opening")

    pass_line("second sample schema runtime")


def _public_knowledge_text(dm: FakeDMEngine) -> str:
    return json.dumps(dm.get_schema_runtime_state().get("schema_public_knowledge", {}), ensure_ascii=False)


def start_emergent_round(dm: FakeDMEngine):
    opening = dm.start_game()
    assert_text("emergent schema opening", opening)
    require(dm.schema_phase_id == "round_1", "emergent schema first phase", dm.schema_phase_id)
    return opening


def test_schema_phase_runtime_demo():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1", "AI_DM_SCRIPT_ID": "monsters_halloween_night_cn"}):
        dm = FakeDMEngine()
        opening = dm.start_game()
        assert_text("schema runtime demo opening", opening)
        state = dm.get_schema_runtime_state()
        require(state["schema_phase_id"] == "intro", "schema runtime demo intro", state["schema_phase_id"])
        require(dm.schema_packet_visibility.get("wolf_intro_private") == "private", "schema runtime demo private packet", str(dm.schema_packet_visibility))
        require(not state["schema_public_knowledge"]["role_packets"], "schema runtime demo public leak", _public_knowledge_text(dm)[:240])
        require(dm.get_unlocked_role_packets("wolf"), "schema runtime demo packet helper", "wolf packet not unlocked")

        dm.chat("理解了")
        require(dm.schema_phase_id == "discussion", "schema runtime demo discussion", dm.schema_phase_id)

        clue1 = dm.advance_schema_phase()
        assert_text("schema runtime demo clue1 phase", clue1)
        require(dm.schema_phase_id == "clue_1_release", "schema runtime demo clue1 phase", dm.schema_phase_id)
        require("clue_1" in dm.schema_released_clue_ids, "schema runtime demo clue1 public", str(dm.schema_released_clue_ids))
        require("clue_2" not in dm.schema_released_clue_ids, "schema runtime demo clue2 premature", str(dm.schema_released_clue_ids))
        assert_no_forbidden("schema runtime demo clue1 no spoiler", clue1, PRE_CLUE_2_FORBIDDEN)

        search_phase = dm.advance_schema_phase()
        assert_text("schema runtime demo search phase", search_phase)
        require(dm.schema_phase_id == "search", "schema runtime demo search phase", dm.schema_phase_id)
        require("clue_2" not in dm.schema_released_clue_ids, "schema runtime demo search no clue2", str(dm.schema_released_clue_ids))

        clue2 = dm.advance_schema_phase()
        assert_text("schema runtime demo clue2 phase", clue2)
        require(dm.schema_phase_id == "clue_2_release", "schema runtime demo clue2 phase", dm.schema_phase_id)
        require("clue_2" in dm.schema_released_clue_ids, "schema runtime demo clue2 public", str(dm.schema_released_clue_ids))
        require("reveal_clue_2" in dm.schema_revealed_rule_ids, "schema runtime demo reveal rule", str(dm.schema_revealed_rule_ids))

    pass_line("schema phase runtime demo")


def test_schema_phase_runtime_second_sample():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1", "AI_DM_SCRIPT_ID": "second_sample"}):
        dm = FakeDMEngine()
        opening = dm.start_game()
        assert_text("schema runtime second opening", opening)
        require(dm.schema_phase_id == "intro", "schema runtime second intro", dm.schema_phase_id)
        louis_packets = dm.get_unlocked_role_packets("Louis Cagliostro")
        require(louis_packets, "schema runtime second content_ref", "Louis packet not unlocked")
        require("Louis" in louis_packets[0].get("content", ""), "schema runtime second content_ref", louis_packets[0].get("content", "")[:120])
        require(not dm.schema_public_knowledge["role_packets"], "schema runtime second private leak", _public_knowledge_text(dm)[:240])

        pre_clue_hint = dm._sanitize_hint_for_spoilers("The paperweight is important.", "L2")
        require("paperweight" not in pre_clue_hint.lower(), "schema runtime second paperweight guard", pre_clue_hint)

        dm.chat("理解了")
        require(dm.schema_phase_id == "discussion", "schema runtime second discussion", dm.schema_phase_id)

        expected = [
            ("clue_1_release", "clue_1"),
            ("clue_2_release", "clue_2"),
            ("clue_3_release", "clue_3"),
            ("clue_4_release", "clue_4"),
        ]
        for phase_id, clue_id in expected:
            reply = dm.advance_schema_phase()
            assert_text(f"schema runtime second {phase_id}", reply)
            require(dm.schema_phase_id == phase_id, f"schema runtime second {phase_id}", dm.schema_phase_id)
            require(clue_id in dm.schema_released_clue_ids, f"schema runtime second {clue_id}", str(dm.schema_released_clue_ids))
        require("reveal_clue_4" in dm.schema_revealed_rule_ids, "schema runtime second reveal rules", str(dm.schema_revealed_rule_ids))

    pass_line("schema phase runtime second sample")


def test_schema_role_packet_visibility_memory_sample():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        dm.start_game()
        schema_copy = json.loads(json.dumps(dm.script_schema, ensure_ascii=False))
        schema_copy["phases"] = [
            {
                "phase_id": "packet_visibility_test",
                "title": "Packet Visibility Test",
                "phase_type": "discovery",
                "order": 1,
                "materials_to_release": [],
                "clues_to_reveal": [],
                "dm_instructions": {"opening_text": "packet visibility test", "pace_notes": "", "transition_condition": "manual"},
            }
        ]
        schema_copy["role_packets"] = [
            {
                "packet_id": "public_read_test",
                "character_id": "wolf",
                "phase_id": "packet_visibility_test",
                "content": "PUBLIC READ TEST",
                "content_ref": "",
                "visibility": "private",
                "recipients": [],
                "after_reveal_visibility": "public",
                "reveal_instruction": "must_read_aloud",
            },
            {
                "packet_id": "secret_keep_test",
                "character_id": "wolf",
                "phase_id": "packet_visibility_test",
                "content": "SECRET KEEP TEST",
                "content_ref": "",
                "visibility": "private",
                "recipients": [],
                "after_reveal_visibility": "private",
                "reveal_instruction": "keep_secret",
            },
        ]
        dm.script_schema = schema_copy
        dm._init_schema_runtime_state()
        reply = dm._enter_schema_phase("packet_visibility_test")
        public_text = _public_knowledge_text(dm)
        assert_text("schema role packet memory sample", reply)
        require("PUBLIC READ TEST" in reply and "PUBLIC READ TEST" in public_text, "schema role packet public", reply)
        require("SECRET KEEP TEST" not in public_text, "schema role packet private public leak", public_text)
        require("SECRET KEEP TEST" not in dm._build_system_prompt(), "schema role packet private prompt leak", "private content leaked into prompt")
        require(any(packet.get("content") == "SECRET KEEP TEST" for packet in dm.get_unlocked_role_packets("wolf")), "schema role packet helper private", "private helper did not expose host packet")

    pass_line("schema role packet visibility memory sample")


class _CapturingStringIO(io.StringIO):
    def __init__(self, store: dict[str, str]):
        super().__init__()
        self._store = store

    def close(self):
        self._store["payload"] = self.getvalue()
        super().close()


def test_schema_save_load_runtime_roundtrip():
    store: dict[str, str] = {}

    def fake_open(path, mode="r", encoding=None):
        if "w" in mode:
            return _CapturingStringIO(store)
        if "r" in mode and "schema_runtime_save.json" in str(path):
            return io.StringIO(store["payload"])
        raise AssertionError(f"unexpected file access in schema roundtrip: {path}")

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        dm.start_game()
        private_content = dm.get_unlocked_role_packets("wolf")[0]["content"]
        dm.chat("理解了")
        dm.advance_schema_phase()
        with patch("builtins.open", fake_open):
            success, message = dm.save_game("schema_runtime_save")
        require(success, "schema save runtime roundtrip", message)

        loaded = FakeDMEngine()
        with patch("builtins.open", fake_open):
            success, message = loaded.load_game("schema_runtime_save")
        require(success, "schema load runtime roundtrip", message)
        require(loaded.schema_phase_id == "clue_1_release", "schema load runtime phase", loaded.schema_phase_id)
        require("clue_1" in loaded.schema_released_clue_ids, "schema load runtime clue", str(loaded.schema_released_clue_ids))
        require("reveal_clue_1" in loaded.schema_revealed_rule_ids, "schema load runtime reveal rule", str(loaded.schema_revealed_rule_ids))
        public_text = _public_knowledge_text(loaded)
        public_clue_ids = [item.get("clue_id") for item in loaded.schema_public_knowledge["clues"]]
        require(public_clue_ids.count("clue_1") == 1, "schema load runtime duplicate clue", public_text)
        require(private_content not in loaded.messages[0]["content"], "schema load runtime prompt privacy", "private role packet leaked into prompt")

    pass_line("schema save/load runtime roundtrip")


def test_schema_duplicate_phase_and_clue_idempotent():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        dm.start_game()
        dm.chat("理解了")
        first = dm.advance_schema_phase()
        assert_text("schema duplicate first release", first)
        before = dm.get_schema_runtime_state()
        duplicate_phase = dm.advance_schema_phase("clue_1_release")
        duplicate_clue = dm.release_clue("clue_1")
        after = dm.get_schema_runtime_state()
        require(after["schema_released_clue_ids"].count("clue_1") == 1, "schema duplicate clue ids", str(after["schema_released_clue_ids"]))
        require(after["schema_revealed_rule_ids"].count("reveal_clue_1") == 1, "schema duplicate reveal rules", str(after["schema_revealed_rule_ids"]))
        require(len(after["schema_public_knowledge"]["clues"]) == len(before["schema_public_knowledge"]["clues"]), "schema duplicate public clues", _public_knowledge_text(dm))
        require("clue_2" not in after["schema_released_clue_ids"], "schema duplicate premature clue2", str(after["schema_released_clue_ids"]))
        assert_text("schema duplicate phase reply", duplicate_phase)
        assert_text("schema duplicate clue reply", duplicate_clue)

    pass_line("schema duplicate phase/clue idempotent")


def test_bad_schema_falls_back_to_demo():
    bad_path = REPO_ROOT / "stories" / "bad_acceptance_schema.json"
    original_loader = dm_module.load_script_schema

    def fake_loader(path):
        if pathlib.Path(path) == bad_path:
            raise dm_module.SchemaValidationError(["forced bad schema"])
        return original_loader(path)

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        with patch("dm_engine.load_script_schema", side_effect=fake_loader):
            dm = FakeDMEngine(schema_path=bad_path)
    require(dm.schema_shadow_status == "fallback_demo", "bad schema fallback", dm.schema_shadow_status)
    require(dm.active_script_id == dm_module.DEFAULT_SCRIPT_ID, "bad schema fallback id", dm.active_script_id)
    opening = dm.start_game()
    assert_text("bad schema fallback opening", opening)
    require(dm.schema_phase_id == "intro", "bad schema fallback phase", dm.schema_phase_id)

    pass_line("bad schema fallback demo")


def test_legacy_load_rebuilds_schema_public_knowledge():
    legacy_state = {
        "game_phase": "discussion",
        "opening_step": 5,
        "designated_speaker": "狼",
        "released_clues": ["clue_1"],
        "turn_count": 3,
        "discussion_elapsed_seconds_accumulated": 30,
    }
    payload = json.dumps(legacy_state, ensure_ascii=False)

    def fake_open(path, mode="r", encoding=None):
        if "r" in mode and "legacy_schema_runtime.json" in str(path):
            return io.StringIO(payload)
        raise AssertionError(f"unexpected file access in schema legacy rebuild: {path}")

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        with patch("builtins.open", fake_open):
            success, message = dm.load_game("legacy_schema_runtime")
        require(success, "legacy schema rebuild", message)
        require(dm.schema_phase_id == "discussion", "legacy schema rebuild phase", dm.schema_phase_id)
        require("clue_1" in dm.schema_released_clue_ids, "legacy schema rebuild clue id", str(dm.schema_released_clue_ids))
        require("reveal_clue_1" in dm.schema_revealed_rule_ids, "legacy schema rebuild reveal", str(dm.schema_revealed_rule_ids))
        require(any(item.get("clue_id") == "clue_1" for item in dm.schema_public_knowledge["clues"]), "legacy schema rebuild public clue", _public_knowledge_text(dm))

    pass_line("legacy load rebuilds schema public knowledge")


def test_bad_save_private_packet_scrubbed_from_prompt():
    bad_state = {
        "game_phase": "discussion",
        "opening_step": 5,
        "designated_speaker": "狼",
        "released_clues": [],
        "schema_phase_id": "discussion",
        "schema_public_knowledge": {
            "materials": [],
            "clues": [],
            "role_packets": [
                {
                    "packet_id": "wolf_intro_private",
                    "character_id": "wolf",
                    "display_name": "狼",
                    "visibility": "private",
                    "after_reveal_visibility": "private",
                    "reveal_instruction": "may_share",
                    "content": "PRIVATE LEAK SENTINEL",
                }
            ],
        },
        "schema_unlocked_role_packets": {
            "wolf_intro_private": {
                "packet_id": "wolf_intro_private",
                "character_id": "wolf",
                "display_name": "狼",
                "visibility": "private",
                "after_reveal_visibility": "private",
                "reveal_instruction": "may_share",
                "content": "PRIVATE LEAK SENTINEL",
            }
        },
        "schema_packet_visibility": {"wolf_intro_private": "private"},
    }
    payload = json.dumps(bad_state, ensure_ascii=False)

    def fake_open(path, mode="r", encoding=None):
        if "r" in mode and "bad_private_save.json" in str(path):
            return io.StringIO(payload)
        raise AssertionError(f"unexpected file access in private scrub: {path}")

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        with patch("builtins.open", fake_open):
            success, message = dm.load_game("bad_private_save")
        require(success, "bad private save load", message)
        public_text = _public_knowledge_text(dm)
        require("PRIVATE LEAK SENTINEL" not in public_text, "bad private save public scrub", public_text)
        require("PRIVATE LEAK SENTINEL" not in dm.messages[0]["content"], "bad private save prompt scrub", "private content leaked into prompt")
        require(dm.get_unlocked_role_packets("wolf")[0]["content"] == "PRIVATE LEAK SENTINEL", "bad private save host helper", "private helper lost packet")

    pass_line("bad save private packet scrubbed")


def test_schema_action_rules_disabled_noop():
    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1"}):
        dm = FakeDMEngine()
        reply = dm.submit_schema_form("wolf", "action_card", {"action": "MURDER", "target": "witch"})
        require("inactive" in reply, "schema action disabled demo", reply)
        start_discussion(dm)
        clue1 = dm.release_clue("clue_1")
        assert_text("schema action disabled old clue", clue1)

    with patch.dict(os.environ, {"AI_DM_SCHEMA_ENABLED": "1", "AI_DM_SCRIPT_ID": "second_sample"}):
        dm = FakeDMEngine()
        reply = dm.resolve_schema_actions()
        require("inactive" in reply, "schema action disabled second sample", reply)

    pass_line("schema action_rules disabled keeps old flow")


def test_schema_action_double_guard_blocks_murder():
    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)
    require(dm.active_script_id == "emergent_resolution_minimal", "schema loader path action test", dm.active_script_id)
    require(dm._schema_actions_enabled(), "schema action enabled", "emergent schema did not enable actions")
    require(dm.character_state["andre"]["alive"] is True, "schema character state init", str(dm.character_state))

    dm.submit_schema_form("Claude", "action_card", {"action": "GUARD", "target": "Andre"})
    dm.submit_schema_form("Andre", "action_card", {"action": "GUARD", "target": "Andre"})
    dm.submit_schema_form("Beatrice", "action_card", {"action": "MURDER", "target": "Andre"})
    result = dm.resolve_schema_actions()
    assert_text("schema double guard resolve", result)
    murder_results = [item for item in dm.schema_action_results if item.get("action_type") == "MURDER"]
    require(murder_results and murder_results[0]["status"] == "blocked", "schema double guard blocks murder", str(dm.schema_action_results))
    require(dm.character_state["andre"]["alive"] is True, "schema blocked murder keeps target alive", str(dm.character_state["andre"]))
    public_events = dm.schema_public_knowledge["resolution_events"]
    require(any(item.get("action_type") == "MURDER" and item.get("status") == "blocked" for item in public_events), "schema blocked murder public event", str(public_events))

    pass_line("schema double guard blocks murder")


def test_schema_action_phase_limits_and_replacement():
    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)

    early_vote = dm.submit_schema_form("Andre", "vote_card", {"vote": "Beatrice"})
    require("only be submitted during phase resolution" in early_vote, "schema vote phase limit", early_vote)
    require(not dm.schema_form_submissions, "schema phase-rejected submission ignored", str(dm.schema_form_submissions))

    first = dm.submit_schema_form("Andre", "action_card", {"action": "GUARD", "target": "Beatrice"})
    assert_text("schema first action submit", first)
    second = dm.submit_schema_form("Andre", "action_card", {"action": "MURDER", "target": "Beatrice"})
    require("Replaced previous submission" in second, "schema replacement message", second)
    active = [item for item in dm.schema_form_submissions if dm._schema_submission_is_active(item)]
    require(len(active) == 1 and active[0]["action_type"] == "MURDER", "schema replacement active set", str(dm.schema_form_submissions))
    require(dm.schema_form_submissions[0]["status"] == "replaced", "schema replacement status", str(dm.schema_form_submissions))

    pass_line("schema phase limit and duplicate replacement")


def test_schema_action_murder_changes_vote_eligibility():
    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)
    dm.submit_schema_form("Beatrice", "action_card", {"action": "MURDER", "target": "Andre"})
    dm.advance_schema_phase("resolution")
    dm.submit_schema_form("Andre", "vote_card", {"vote": "Beatrice"})
    dm.submit_schema_form("Claude", "vote_card", {"vote": "Andre"})
    result = dm.resolve_schema_actions()
    assert_text("schema murder changes state", result)
    andre_state = dm.character_state["andre"]
    require(andre_state["alive"] is False, "schema murder dead", str(andre_state))
    require(andre_state["can_vote"] is False, "schema murder can_vote", str(andre_state))
    require(andre_state["can_be_candidate"] is False, "schema murder candidate", str(andre_state))
    require(dm.schema_vote_tally == {}, "schema invalid votes not tallied", str(dm.schema_vote_tally))
    reasons = {item.get("reason") for item in dm.schema_action_results if item.get("action_type") == "VOTE"}
    require({"actor_cannot_vote", "target_not_candidate"} <= reasons, "schema vote invalid reasons", str(dm.schema_action_results))

    pass_line("schema murder changes vote eligibility")


def test_schema_declare_public_investigate_private():
    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)
    declare = dm.submit_schema_form("Andre", "action_card", {"action": "DECLARE", "declaration": "I claim the floor."})
    assert_text("schema declare submit", declare)
    dm.submit_schema_form("Claude", "action_card", {"action": "INVESTIGATE", "target": "Beatrice"})
    result = dm.resolve_schema_actions()
    assert_text("schema declare investigate resolve", result)
    public_text = _public_knowledge_text(dm)
    require("I claim the floor." in public_text, "schema declaration public knowledge", public_text)
    investigate_results = [item for item in dm.schema_action_results if item.get("action_type") == "INVESTIGATE"]
    require(investigate_results and "private_result" in investigate_results[0], "schema investigate private result", str(dm.schema_action_results))
    require(not any(item.get("action_type") == "INVESTIGATE" for item in dm.schema_public_knowledge["resolution_events"]), "schema investigate not public", str(dm.schema_public_knowledge["resolution_events"]))
    prompt = dm._build_system_prompt()
    require("private_investigation_result" not in prompt and "target_state" not in prompt, "schema investigate private prompt", "private result leaked into prompt")

    pass_line("schema declaration public and investigate private")


def test_schema_action_result_phase_routing():
    murder_dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(murder_dm)
    murder_dm.submit_schema_form("Beatrice", "action_card", {"action": "MURDER", "target": "Andre"})
    murder_result = murder_dm.resolve_schema_actions()
    require(murder_dm.schema_phase_id == "accusation", "schema murder routes to accusation", f"{murder_dm.schema_phase_id}\n{murder_result}")
    require("Next schema phase: accusation" in murder_result, "schema murder route output", murder_result)

    blocked_dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(blocked_dm)
    blocked_dm.submit_schema_form("Claude", "action_card", {"action": "GUARD", "target": "Andre"})
    blocked_dm.submit_schema_form("Andre", "action_card", {"action": "GUARD", "target": "Andre"})
    blocked_dm.submit_schema_form("Beatrice", "action_card", {"action": "MURDER", "target": "Andre"})
    blocked_result = blocked_dm.resolve_schema_actions()
    require(blocked_dm.schema_phase_id == "resolution", "schema blocked murder routes to resolution", f"{blocked_dm.schema_phase_id}\n{blocked_result}")
    require("Next schema phase: resolution" in blocked_result, "schema blocked murder route output", blocked_result)

    recap_dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(recap_dm)
    recap_dm.advance_schema_phase("resolution")
    recap_dm.submit_schema_form("Claude", "vote_card", {"vote": "Beatrice"})
    recap_result = recap_dm.resolve_schema_actions()
    require(recap_dm.schema_phase_id == "recap", "schema no-murder resolution routes to recap", f"{recap_dm.schema_phase_id}\n{recap_result}")
    require("Next schema phase: recap" in recap_result, "schema recap route output", recap_result)

    pass_line("schema action result phase routing")


def test_schema_resolve_idempotent_and_spoiler_declaration_guard():
    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)
    dm.script_schema["forbidden_spoilers"].append(
        {
            "spoiler_id": "test_declaration_secret",
            "spoiler_type": "truth",
            "content": "SECRET DECLARE SPOILER",
            "aliases": [],
            "allowed_after_phase": "",
            "allowed_after_reveal_rule": "",
        }
    )
    declare = dm.submit_schema_form(
        "Andre",
        "action_card",
        {"action": "DECLARE", "declaration": "SECRET DECLARE SPOILER"},
    )
    require("REDACTED" in declare, "schema declaration spoiler redacted response", declare)
    public_text = _public_knowledge_text(dm)
    require("SECRET DECLARE SPOILER" not in public_text, "schema declaration spoiler public guard", public_text)
    require("REDACTED" in public_text, "schema declaration redacted public record", public_text)

    dm.script_schema["action_rules"]["blocking_rules"].append(
        {
            "rule_id": "unsupported_declare_block",
            "blocked_action_type": "DECLARE",
            "blocked_by_action_type": "GUARD",
            "minimum_block_count": 1,
            "same_target_required": True,
        }
    )
    dm.submit_schema_form("Claude", "action_card", {"action": "MURDER", "target": "Beatrice"})
    first = dm.resolve_schema_actions()
    snapshot = (
        json.dumps(dm.character_state, sort_keys=True),
        json.dumps(dm.schema_action_results, sort_keys=True),
        json.dumps(dm.schema_vote_tally, sort_keys=True),
        json.dumps(dm.schema_public_knowledge["resolution_events"], sort_keys=True),
    )
    second = dm.resolve_schema_actions()
    snapshot_after = (
        json.dumps(dm.character_state, sort_keys=True),
        json.dumps(dm.schema_action_results, sort_keys=True),
        json.dumps(dm.schema_vote_tally, sort_keys=True),
        json.dumps(dm.schema_public_knowledge["resolution_events"], sort_keys=True),
    )
    require(first == second and snapshot == snapshot_after, "schema resolve idempotent", f"{first}\n---\n{second}")
    require(any("unsupported blocking_rule" in item for item in dm.schema_runtime_errors), "schema unsupported blocking warning", str(dm.schema_runtime_errors))

    pass_line("schema resolve idempotent and declaration spoiler guard")


def test_schema_action_runtime_save_load_roundtrip():
    store: dict[str, str] = {}

    def fake_open(path, mode="r", encoding=None):
        if "w" in mode:
            return _CapturingStringIO(store)
        if "r" in mode and "schema_action_runtime.json" in str(path):
            return io.StringIO(store["payload"])
        raise AssertionError(f"unexpected file access in action runtime roundtrip: {path}")

    dm = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    start_emergent_round(dm)
    dm.submit_schema_form("Beatrice", "action_card", {"action": "MURDER", "target": "Andre"})
    dm.advance_schema_phase("resolution")
    dm.submit_schema_form("Claude", "vote_card", {"vote": "Beatrice"})
    dm.resolve_schema_actions()
    with patch("builtins.open", fake_open):
        success, message = dm.save_game("schema_action_runtime")
    require(success, "schema action save", message)

    loaded = FakeDMEngine(schema_path=EMERGENT_SCHEMA)
    with patch("builtins.open", fake_open):
        success, message = loaded.load_game("schema_action_runtime")
    require(success, "schema action load", message)
    require(loaded.character_state == dm.character_state, "schema action load character_state", str(loaded.character_state))
    require(loaded.schema_form_submissions == dm.schema_form_submissions, "schema action load submissions", str(loaded.schema_form_submissions))
    require(loaded.schema_action_results == dm.schema_action_results, "schema action load results", str(loaded.schema_action_results))
    require(loaded.schema_vote_tally == dm.schema_vote_tally, "schema action load tally", str(loaded.schema_vote_tally))

    pass_line("schema action runtime save/load")


def main():
    tests = [
        test_basic_flow_smoke,
        test_timed_clue_smoke,
        test_normal_progress_no_hint,
        test_semantic_progress_tracking,
        test_hint_silence_trigger_and_levels,
        test_idle_timer_intervention,
        test_legacy_load_does_not_count_offline_time,
        test_clue_attention_and_recent_event_suppression,
        test_search_success_suppresses_immediate_hint,
        test_vote_suggestion_only_suggests,
        test_participation_cooldown,
        test_api_assist_not_used_on_confident_progress,
        test_api_assist_candidate_hint_sanitized,
        test_api_assist_bad_json_fallback,
        test_api_assist_failure_and_bad_fields_fallback,
        test_spoiler_guardrails_on_guidance,
        test_offtopic_pivot,
        test_legacy_save_compatibility,
        test_schema_shadow_mode_toggle,
        test_second_sample_schema_runtime,
        test_schema_phase_runtime_demo,
        test_schema_phase_runtime_second_sample,
        test_schema_role_packet_visibility_memory_sample,
        test_schema_save_load_runtime_roundtrip,
        test_schema_duplicate_phase_and_clue_idempotent,
        test_bad_schema_falls_back_to_demo,
        test_legacy_load_rebuilds_schema_public_knowledge,
        test_bad_save_private_packet_scrubbed_from_prompt,
        test_schema_action_rules_disabled_noop,
        test_schema_action_double_guard_blocks_murder,
        test_schema_action_phase_limits_and_replacement,
        test_schema_action_murder_changes_vote_eligibility,
        test_schema_declare_public_investigate_private,
        test_schema_action_result_phase_routing,
        test_schema_resolve_idempotent_and_spoiler_declaration_guard,
        test_schema_action_runtime_save_load_roundtrip,
    ]
    for test in tests:
        test()
    print("[PASS] all acceptance checks completed without real API calls")


if __name__ == "__main__":
    main()
