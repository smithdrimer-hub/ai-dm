"""Scripted local playthrough/replay runner for AI-DM.

Run from the repository root:
    python -B scripts/replay_playthrough.py scripts/playthroughs/schema_runtime_replay.json

The runner uses a deterministic fake LLM, so it never needs or calls a real API.
It only exercises existing DMEngine runtime APIs and command handlers.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import sys
from contextlib import contextmanager
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# config.py requires an API key at import time, but replay runs never call the API.
os.environ.setdefault("OPENAI_API_KEY", "replay-dummy-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://127.0.0.1/replay-never-called")
os.environ.setdefault("OPENAI_MODEL", "replay-dummy-model")

from dm_engine import DMEngine  # noqa: E402


class ReplayDMEngine(DMEngine):
    """DMEngine with deterministic local model behavior for replay scripts."""

    def __init__(self, *args, **kwargs):
        self.model_call_count = 0
        super().__init__(*args, **kwargs)

    def _call_model(self, user_message: str):
        self.model_call_count += 1
        player_input = self._extract_player_input(user_message)
        progress_signal = "PROGRESS" if any(
            token in player_input for token in ("18", "19", "20", "22", "timeline", "saw", "entered", "left")
        ) else "UNCHANGED"
        self._update_state_from_output("UNCHANGED", "UNCHANGED", "ON_TOPIC", progress_signal)
        self.messages.append({"role": "assistant", "content": "[Replay fake DM silence]"})
        return ""

    def _judge_player_honesty(self, conversation_history: str):
        return "honest" if any(word in conversation_history for word in ("sorry", "apologize", "truth")) else "dishonest"

    @staticmethod
    def _extract_player_input(user_message: str) -> str:
        marker = "【玩家输入】"
        if marker not in user_message:
            return user_message
        tail = user_message.split(marker, 1)[1]
        return tail.split("\n", 1)[0].strip()


@contextmanager
def temporary_env(updates: dict[str, str]):
    original = {key: os.environ.get(key) for key in updates}
    os.environ.update({key: str(value) for key, value in updates.items()})
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def fail(context: str, message: str, detail: Any = ""):
    if detail:
        snippet = str(detail).replace("\n", " ")[:400]
        raise AssertionError(f"{context}: {message}: {snippet}")
    raise AssertionError(f"{context}: {message}")


def require(condition: bool, context: str, message: str, detail: Any = ""):
    if not condition:
        fail(context, message, detail)


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def text_blob(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def resolve_schema_path(raw_path: str | None) -> pathlib.Path | None:
    if not raw_path:
        return None
    path = pathlib.Path(raw_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def command_to_fields(command: str) -> tuple[str, str, dict[str, str]]:
    tokens = shlex.split(command)
    values: dict[str, str] = {}
    for token in tokens[2:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        values[key.strip().lower()] = value.strip()
    actor = values.pop("actor", "")
    form_id = values.pop("form", values.pop("form_id", ""))
    return actor, form_id, values


def execute_command(dm: ReplayDMEngine, command: str) -> str:
    stripped = command.strip()
    lowered = stripped.lower()
    if lowered.startswith("/phase"):
        parts = stripped.split()
        target = None
        if len(parts) >= 2 and parts[1].lower() != "next":
            target = parts[1]
        return dm.advance_schema_phase(target)

    if lowered.startswith("/packet"):
        parts = stripped.split(maxsplit=1)
        character = parts[1].strip() if len(parts) > 1 else ""
        packets = dm.get_unlocked_role_packets(character)
        return json.dumps(packets, ensure_ascii=False, indent=2, sort_keys=True)

    if lowered.startswith("/schema submit"):
        actor, form_id, fields = command_to_fields(stripped)
        return dm.submit_schema_form(actor, form_id, fields)

    if lowered == "/schema resolve":
        return dm.resolve_schema_actions()

    if lowered.startswith("/schema reveal"):
        tokens = shlex.split(stripped)
        values: dict[str, str] = {}
        positional = []
        for token in tokens[2:]:
            if "=" in token:
                key, value = token.split("=", 1)
                values[key.strip().lower()] = value.strip()
            else:
                positional.append(token)
        code_word = values.get("code_word") or values.get("code") or (positional[0] if positional else "")
        condition = values.get("condition", "")
        return dm.reveal_next_schema_final_step(code_word=code_word, condition=condition)

    if lowered == "/clue1":
        return dm.release_clue("clue_1")
    if lowered == "/clue2":
        return dm.release_clue("clue_2")
    if lowered.startswith("/clue "):
        parts = stripped.split(maxsplit=1)
        return dm.release_clue(parts[1].strip())

    fail("command", "unsupported replay command", command)
    return ""


def dict_matches(actual: dict, expected: dict) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def assert_replay_state(dm: ReplayDMEngine, output: str, assertions: dict, context: str):
    state = dm.get_schema_runtime_state()
    public_knowledge = text_blob(state.get("schema_public_knowledge", {}))
    action_results = state.get("schema_action_results", [])
    prompt = dm.messages[0]["content"] if getattr(dm, "messages", None) else ""

    expected_phase = assertions.get("schema_phase") or assertions.get("schema_phase_id")
    if expected_phase is not None:
        require(state.get("schema_phase_id") == expected_phase, context, "schema_phase mismatch", state.get("schema_phase_id"))
    if "game_phase" in assertions:
        require(dm.game_phase == assertions["game_phase"], context, "game_phase mismatch", dm.game_phase)
    if "active_script_id" in assertions:
        require(dm.active_script_id == assertions["active_script_id"], context, "active_script_id mismatch", dm.active_script_id)

    released = state.get("schema_released_clue_ids", [])
    if "released_clues_exact" in assertions:
        require(released == assertions["released_clues_exact"], context, "released clues mismatch", released)
    for clue_id in as_list(assertions.get("released_clues_contains")):
        require(clue_id in released, context, "released clue missing", released)
    for clue_id in as_list(assertions.get("released_clues_not_contains")):
        require(clue_id not in released, context, "forbidden released clue present", released)

    final_steps = state.get("schema_final_reveal_steps", [])
    if "final_reveal_steps_exact" in assertions:
        require(final_steps == assertions["final_reveal_steps_exact"], context, "final reveal steps mismatch", final_steps)
    for step in as_list(assertions.get("final_reveal_steps_contains")):
        require(step in final_steps, context, "final reveal step missing", final_steps)
    for step in as_list(assertions.get("final_reveal_steps_not_contains")):
        require(step not in final_steps, context, "forbidden final reveal step present", final_steps)

    for needle in as_list(assertions.get("output_contains")):
        require(needle in output, context, "output missing text", output)
    for needle in as_list(assertions.get("output_not_contains")):
        require(needle not in output, context, "output contains forbidden text", output)

    for needle in as_list(assertions.get("public_knowledge_contains")):
        require(needle in public_knowledge, context, "public_knowledge missing text", public_knowledge)
    for needle in as_list(assertions.get("public_knowledge_not_contains")):
        require(needle not in public_knowledge, context, "public_knowledge contains forbidden text", public_knowledge)

    for needle in as_list(assertions.get("prompt_contains")):
        require(needle in prompt, context, "prompt missing text", prompt)
    for needle in as_list(assertions.get("prompt_not_contains")):
        require(needle not in prompt, context, "prompt contains forbidden/private text", prompt)

    for expected in as_list(assertions.get("action_results_include")):
        require(
            any(isinstance(item, dict) and dict_matches(item, expected) for item in action_results),
            context,
            "action_results missing expected subset",
            {"expected": expected, "actual": action_results},
        )
    for expected in as_list(assertions.get("action_results_not_include")):
        require(
            not any(isinstance(item, dict) and dict_matches(item, expected) for item in action_results),
            context,
            "action_results contains forbidden subset",
            {"expected": expected, "actual": action_results},
        )


def execute_step(dm: ReplayDMEngine, step: dict, session_name: str, index: int):
    name = step.get("name") or f"step_{index}"
    context = f"{session_name}/{name}"
    op = step.get("op")
    output = ""
    if op in {"start", "start_game"}:
        output = dm.start_game()
    elif op == "chat" or "input" in step:
        output = dm.chat(step.get("input", ""))
    elif op == "command" or "command" in step:
        output = execute_command(dm, step.get("command", ""))
    else:
        fail(context, "missing op/input/command", step)

    assert_replay_state(dm, output or "", step.get("assert", {}), context)
    print(f"[PASS] {context}")


def run_session(session: dict):
    name = session.get("name") or session.get("script_id") or session.get("schema_path") or "playthrough"
    schema_path = resolve_schema_path(session.get("schema_path"))
    env_updates = {
        "AI_DM_SCHEMA_ENABLED": "1" if session.get("schema_enabled", True) else "0",
    }
    if session.get("script_id"):
        env_updates["AI_DM_SCRIPT_ID"] = session["script_id"]
    with temporary_env(env_updates):
        dm = ReplayDMEngine(script_id=session.get("script_id"), schema_path=schema_path)
        for index, step in enumerate(session.get("steps", []), start=1):
            execute_step(dm, step, name, index)
        require(dm.model_call_count == session.get("expected_model_calls", dm.model_call_count), name, "model call count mismatch", dm.model_call_count)
    print(f"[PASS] {name} completed")


def load_replay(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description="Run an offline AI-DM scripted playthrough.")
    parser.add_argument("replay_json", help="Path to a replay JSON file.")
    args = parser.parse_args()

    replay_path = resolve_schema_path(args.replay_json)
    replay = load_replay(replay_path)
    sessions = replay.get("sessions") if isinstance(replay.get("sessions"), list) else [replay]
    for session in sessions:
        run_session(session)
    print("[PASS] replay completed without real API calls")


if __name__ == "__main__":
    main()
