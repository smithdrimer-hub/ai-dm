"""Optional LLM actor layer for DetectiveGameEngine NPC replies.

The detective engine remains the judge. This module only rewrites an already
judged template response into a more natural in-character NPC reply.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol


class NPCActor(Protocol):
    """Protocol for optional NPC response renderers."""

    def render_response(self, context: dict[str, Any], deterministic_message: str) -> str:
        """Return an in-character NPC reply for a judged engine action."""


class OpenAINPCActor:
    """OpenAI-compatible chat-completions actor for NPC performance only."""

    def __init__(
        self,
        *,
        client: Any,
        model: str,
        timeout: int = 60,
        temperature: float = 0.65,
        max_tokens: int = 240,
    ):
        self.client = client
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls) -> "OpenAINPCActor":
        """Build an OpenAI-compatible actor from environment variables."""
        try:
            from dotenv import load_dotenv
        except ImportError:
            load_dotenv = None
        if load_dotenv is not None:
            load_dotenv()

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Missing openai dependency. Install requirements.txt first.") from exc

        provider = os.getenv("API_PROVIDER", "ecnu").lower()
        if provider == "custom":
            api_key = os.getenv("CUSTOM_API_KEY")
            base_url = os.getenv("CUSTOM_BASE_URL")
            model = os.getenv("AI_DETECTIVE_LLM_MODEL") or os.getenv("CUSTOM_MODEL", "gpt-3.5-turbo")
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = os.getenv("OPENAI_BASE_URL", "https://chat.ecnu.edu.cn/open/api/v1")
            model = os.getenv("AI_DETECTIVE_LLM_MODEL") or os.getenv("OPENAI_MODEL", "ecnu-max[1m]")

        if not api_key or not base_url:
            raise ValueError("LLM actor requires API key and base URL environment variables.")

        timeout = int(os.getenv("AI_DETECTIVE_LLM_TIMEOUT_SECONDS", os.getenv("OPENAI_TIMEOUT_SECONDS", "60")))
        temperature = float(os.getenv("AI_DETECTIVE_LLM_TEMPERATURE", "0.65"))
        max_tokens = int(os.getenv("AI_DETECTIVE_LLM_MAX_TOKENS", "240"))
        return cls(
            client=OpenAI(api_key=api_key, base_url=base_url),
            model=model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def render_response(self, context: dict[str, Any], deterministic_message: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an NPC actor in a single-player detective game. "
                    "The game engine is the judge; you are only the performer. "
                    "You know only the JSON perspective packet provided by the engine. "
                    "Speak only as viewer_character_id using self_view, case_public, "
                    "other_characters_public, npc_runtime, selected_action_policy, player_known, "
                    "allowed_truths, active_lies, broken_lies_this_turn, presented_evidence, "
                    "and conversation_history. "
                    "Never reveal hidden truths, culprit identity, private profiles, forbidden facts, "
                    "undiscovered evidence, schema internals, future phase information, or anything not in the packet. "
                    "For ask interactions, answer normally in character and do not treat the question as proof. "
                    "For confront interactions, follow judge_result and broken_lies_this_turn exactly; "
                    "do not decide whether a lie is broken, whether evidence is valid, or whether the player is correct. "
                    "Never score accusations or advance the game. Keep the answer concise, dramatic, and natural."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Allowed context JSON:\n"
                    f"{json.dumps(context, ensure_ascii=False, sort_keys=True)}\n\n"
                    "Deterministic judge/template response:\n"
                    f"{deterministic_message}\n\n"
                    "Write only the NPC's spoken response. Do not add analysis."
                ),
            },
        ]
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=False,
            timeout=self.timeout,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        try:
            return (response.choices[0].message.content or "").strip()
        except (AttributeError, IndexError, KeyError, TypeError):
            return ""


__all__ = ["NPCActor", "OpenAINPCActor"]
