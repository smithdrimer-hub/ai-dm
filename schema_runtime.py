"""Schema Runtime - Deterministic game-phase engine for ScriptSchema v0.2.1+

Extracted from dm_engine.py Phase 1 (2026-05-08).

Responsibilities:
- Load and validate ScriptSchema JSON at startup
- Manage phase transitions, clue/material release, role packet unlocking
- Handle schema action resolution (guard/murder/investigate/declare/vote)
- Maintain public knowledge boundary and spoiler guard
- Provide runtime state for save/load serialization

This class holds a back-reference to DMEngine for shared state access.
In Phase 1, schema state fields live on DMEngine and are accessed via self.dm.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from script_data import SCRIPT_DATA
from script_schema import SchemaValidationError, load_script_schema

# Module-level constants (moved from dm_engine.py)
DEFAULT_SCRIPT_ID = "monsters_halloween_night_cn"
_ROOT = Path(__file__).resolve().parent
DEMO_SCHEMA_PATH = _ROOT / "stories" / "Monsters Halloween Night_China" / "script_schema_v0_2_1.json"
SCRIPT_SCHEMA_REGISTRY = {
    DEFAULT_SCRIPT_ID: DEMO_SCHEMA_PATH,
    "second_sample": _ROOT / "stories" / "second_sample" / "script_schema_v0_2_1.json",
}


class SchemaRuntime:
    """Deterministic schema-driven game phase and action engine."""

    def __init__(self, dm):
        """
        Args:
            dm: DMEngine instance (back-reference for shared state access)
        """
        self.dm = dm

    # ---- Schema active guard ----

    def is_schema_active(self) -> bool:
        """Return True only when shadow schema is enabled and validated."""
        return bool(self.dm.schema_shadow_enabled and self.dm.script_schema)


    def _load_schema_shadow(self):
        """
        Phase 3 shadow mode: validate the v0.2.1 demo schema at startup, but keep
        SCRIPT_DATA as the runtime fallback if the switch is off or validation fails.
        """
        if not self.dm.schema_shadow_enabled:
            return
        requested_schema_path = self.dm.requested_schema_path or os.getenv("AI_DM_SCHEMA_PATH", "")
        selected_path = Path(requested_schema_path) if requested_schema_path else SCRIPT_SCHEMA_REGISTRY.get(self.dm.active_script_id, DEMO_SCHEMA_PATH)
        try:
            self.dm.script_schema = load_script_schema(selected_path)
            self.dm.active_schema_path = str(selected_path)
            self.dm.active_script_id = self.dm.script_schema.get("script_info", {}).get("id", self.dm.active_script_id)
            self.dm.schema_shadow_status = "loaded"
        except (OSError, SchemaValidationError, json.JSONDecodeError) as exc:
            # Phase 4 keeps the old fixed demo as the safety net for bad ids or bad paths.
            self.dm.schema_shadow_error = str(exc)
            if selected_path != DEMO_SCHEMA_PATH:
                try:
                    self.dm.script_schema = load_script_schema(DEMO_SCHEMA_PATH)
                    self.dm.active_schema_path = str(DEMO_SCHEMA_PATH)
                    self.dm.active_script_id = DEFAULT_SCRIPT_ID
                    self.dm.schema_shadow_status = "fallback_demo"
                    return
                except (OSError, SchemaValidationError, json.JSONDecodeError) as fallback_exc:
                    self.dm.schema_shadow_error = f"{self.dm.schema_shadow_error}; demo fallback failed: {fallback_exc}"
            self.dm.script_schema = None
            self.dm.active_schema_path = ""
            self.dm.active_script_id = DEFAULT_SCRIPT_ID
            self.dm.schema_shadow_status = "fallback_script_data"


    def _get_schema_role_names(self) -> tuple[str, ...]:
        if not self.is_schema_active():
            return ()
        cast_names = {
            character.get("character_id"): character.get("display_name")
            for character in self.dm.script_schema.get("cast", [])
            if character.get("character_id") and character.get("display_name")
        }
        slots = self.dm.script_schema.get("player_config", {}).get("role_player_slots", [])
        names = [cast_names.get(slot.get("character_id")) for slot in slots if isinstance(slot, dict)]
        names = [name for name in names if name]
        if not names:
            names = [
                character.get("display_name")
                for character in self.dm.script_schema.get("cast", [])
                if character.get("display_name")
            ]
        return tuple(names)


    def get_script_display_title(self) -> str:
        """Title used by the CLI banner and tests; never blocks on schema availability."""
        if self.is_schema_active():
            info = self.dm.script_schema.get("script_info", {})
            return f"{info.get('title', self.dm.active_script_id)} ({self.dm.active_script_id})"
        return "Monsters Halloween Night (legacy fallback)"


    def _schema_public_materials(self) -> dict:
        return self.dm.script_schema.get("public_materials", {}) if self.is_schema_active() else {}


    def _schema_cast(self) -> list[dict]:
        return self.dm.script_schema.get("cast", []) if self.is_schema_active() else []


    def _schema_clues(self) -> dict:
        """Expose schema clues by id while preserving SCRIPT_DATA as fallback."""
        if not self.is_schema_active():
            return {}
        return {
            clue.get("clue_id"): clue
            for clue in self.dm.script_schema.get("clues", [])
            if isinstance(clue, dict) and clue.get("clue_id")
        }


    def _schema_reveal_rules(self) -> list[dict]:
        return self.dm.script_schema.get("reveal_rules", []) if self.is_schema_active() else []


    def _get_reveal_rule_for_clue(self, clue_id: str) -> Optional[dict]:
        """Find the schema reveal rule that publicly announces a clue."""
        for rule in self._schema_reveal_rules():
            if rule.get("target_type") == "clue" and rule.get("target_id") == clue_id:
                return rule
        return None


    def _init_schema_runtime_state(self):
        """Initialize Phase 5 schema runtime fields.

        These fields deliberately separate public knowledge from private role
        packets. The model-facing prompt only receives the public side.
        """
        self.dm.schema_phase_id = ""
        self.dm.schema_entered_phase_ids = []
        self.dm.schema_public_knowledge = {
            "materials": [],
            "clues": [],
            "role_packets": [],
            "final_reveals": [],
        }
        self.dm.schema_released_material_ids = []
        self.dm.schema_released_clue_ids = []
        self.dm.schema_unlocked_role_packets = {}
        self.dm.schema_packet_visibility = {}
        self.dm.schema_revealed_rule_ids = []
        self.dm.schema_runtime_errors = []
        self.dm.character_state = {}
        self.dm.schema_form_submissions = []
        self.dm.schema_action_results = []
        self.dm.schema_vote_tally = {}
        self.dm.schema_last_resolution_route = {}
        self.dm.schema_final_reveal_steps = []
        self._ensure_character_state_defaults()


    def _coerce_schema_runtime_defaults(self):
        """Backfill runtime fields for old saves and schema-disabled sessions."""
        if not isinstance(getattr(self.dm, "schema_public_knowledge", None), dict):
            self.dm.schema_public_knowledge = {"materials": [], "clues": [], "role_packets": []}
        for key in ("materials", "clues", "role_packets", "declarations", "resolution_events", "final_reveals"):
            if not isinstance(self.dm.schema_public_knowledge.get(key), list):
                self.dm.schema_public_knowledge[key] = []
        list_fields = (
            "schema_entered_phase_ids",
            "schema_released_material_ids",
            "schema_released_clue_ids",
            "schema_revealed_rule_ids",
            "schema_runtime_errors",
            "schema_final_reveal_steps",
        )
        for field in list_fields:
            if not isinstance(getattr(self.dm, field, None), list):
                setattr(self.dm, field, [])
        if not isinstance(getattr(self.dm, "schema_unlocked_role_packets", None), dict):
            self.dm.schema_unlocked_role_packets = {}
        if not isinstance(getattr(self.dm, "schema_packet_visibility", None), dict):
            self.dm.schema_packet_visibility = {}
        if not isinstance(getattr(self.dm, "schema_phase_id", None), str):
            self.dm.schema_phase_id = ""
        if not isinstance(getattr(self.dm, "character_state", None), dict):
            self.dm.character_state = {}
        if not isinstance(getattr(self.dm, "schema_form_submissions", None), list):
            self.dm.schema_form_submissions = []
        if not isinstance(getattr(self.dm, "schema_action_results", None), list):
            self.dm.schema_action_results = []
        if not isinstance(getattr(self.dm, "schema_vote_tally", None), dict):
            self.dm.schema_vote_tally = {}
        if not isinstance(getattr(self.dm, "schema_last_resolution_route", None), dict):
            self.dm.schema_last_resolution_route = {}
        for field in list_fields:
            setattr(self.dm, field, self._dedupe_schema_list(getattr(self.dm, field, [])))
        self._ensure_character_state_defaults()
        self._dedupe_schema_public_knowledge()
        self._scrub_private_schema_public_knowledge()


    @staticmethod
    def _dedupe_schema_list(values: list) -> list:
        """Deduplicate JSON-like runtime lists while preserving order."""
        seen = set()
        result = []
        for value in values:
            try:
                key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                key = repr(value)
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return result


    def _dedupe_schema_public_knowledge(self):
        """Keep public knowledge buckets idempotent after repeated phase entry."""
        identity_keys = {
            "materials": "material_id",
            "clues": "clue_id",
            "role_packets": "packet_id",
            "declarations": "declaration_id",
            "resolution_events": "event_id",
            "final_reveals": "step",
        }
        for bucket, identity_key in identity_keys.items():
            cleaned = []
            seen = set()
            for item in self.dm.schema_public_knowledge.get(bucket, []):
                if not isinstance(item, dict):
                    continue
                identity = item.get(identity_key)
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                cleaned.append(item)
            self.dm.schema_public_knowledge[bucket] = cleaned


    def _schema_public_packet_allowed(self, packet: dict) -> bool:
        """Public prompt may include only packets explicitly visible to everyone."""
        if not isinstance(packet, dict):
            return False
        packet_id = packet.get("packet_id", "")
        visibility = self.dm.schema_packet_visibility.get(packet_id, packet.get("visibility", ""))
        if visibility == "public" or packet.get("visibility") == "public":
            return True
        return (
            packet.get("after_reveal_visibility") == "public"
            and packet.get("reveal_instruction") in {"must_read_aloud", "reveal_at_phase_start"}
        )


    def _scrub_private_schema_public_knowledge(self):
        """Remove private role packets from public knowledge after bad/old saves."""
        role_packets = self.dm.schema_public_knowledge.get("role_packets", [])
        self.dm.schema_public_knowledge["role_packets"] = [
            packet for packet in role_packets if self._schema_public_packet_allowed(packet)
        ]


    def _schema_action_rules(self) -> dict:
        if not self.is_schema_active():
            return {}
        rules = self.dm.script_schema.get("action_rules", {})
        return rules if isinstance(rules, dict) else {}


    def _schema_actions_enabled(self) -> bool:
        return bool(self.is_schema_active() and self._schema_action_rules().get("enabled"))


    def _default_character_state(self) -> dict:
        return {"alive": True, "can_vote": True, "can_be_candidate": True}


    def _ensure_character_state_defaults(self):
        """Create/repair character_state only for schema action runtime."""
        if not self._schema_actions_enabled():
            return
        valid_ids = {
            character.get("character_id")
            for character in self._schema_cast()
            if isinstance(character, dict) and character.get("character_id")
        }
        for character_id in valid_ids:
            state = self.dm.character_state.get(character_id)
            if not isinstance(state, dict):
                state = {}
            default = self._default_character_state()
            self.dm.character_state[character_id] = {
                "alive": bool(state.get("alive", default["alive"])),
                "can_vote": bool(state.get("can_vote", state.get("voting_eligible", default["can_vote"]))),
                "can_be_candidate": bool(state.get("can_be_candidate", state.get("candidate_eligible", default["can_be_candidate"]))),
            }
        self.dm.character_state = {
            character_id: state
            for character_id, state in self.dm.character_state.items()
            if character_id in valid_ids and isinstance(state, dict)
        }


    def _reset_character_state_for_resolution(self):
        """Resolution recomputes state from submissions so repeated resolve is stable."""
        self.dm.character_state = {}
        self._ensure_character_state_defaults()

    def _schema_action_types(self) -> set[str]:
        rules = self._schema_action_rules()
        return {
            self._normalize_schema_action_type(action.get("action_type"))
            for action in rules.get("action_types", [])
            if isinstance(action, dict) and action.get("action_type")
        }


    def _normalize_schema_action_type(self, value: str) -> str:
        return str(value or "").strip().upper()


    def _schema_action_resolution_order(self) -> list[str]:
        rules = self._schema_action_rules()
        configured = [
            self._normalize_schema_action_type(action_type)
            for action_type in rules.get("resolution_order", [])
            if action_type
        ]
        fallback = ["GUARD", "MURDER", "INVESTIGATE", "DECLARE", "VOTE"]
        order = []
        for action_type in [*configured, *fallback]:
            if action_type and action_type not in order:
                order.append(action_type)
        return order


    def _schema_action_sort_key(self, submission: dict) -> tuple[int, int]:
        order = self._schema_action_resolution_order()
        action_type = submission.get("action_type", "")
        index = order.index(action_type) if action_type in order else len(order)
        return index, int(submission.get("order", 0))


    def _schema_submission_is_active(self, submission: dict) -> bool:
        """Only active submissions participate in deterministic resolution."""
        return submission.get("status", "submitted") == "submitted"


    def _replace_prior_schema_submission(self, actor_id: str, form_id: str, form: dict) -> list[str]:
        """Per-player forms keep one active answer; newer input replaces older input."""
        scope = form.get("per_player_or_global", "per_player")
        replaced_ids = []
        for submission in self.dm.schema_form_submissions:
            if not self._schema_submission_is_active(submission):
                continue
            if submission.get("form_id") != form_id:
                continue
            if scope == "global" or submission.get("actor_id") == actor_id:
                submission["status"] = "replaced"
                replaced_ids.append(submission.get("submission_id", ""))
        return [item for item in replaced_ids if item]


    def _remove_public_declarations_for_submissions(self, submission_ids: list[str]):
        """When a DECLARE form is replaced, remove its superseded public text."""
        if not submission_ids:
            return
        blocked = set(submission_ids)
        self.dm.schema_public_knowledge["declarations"] = [
            item
            for item in self.dm.schema_public_knowledge.get("declarations", [])
            if item.get("submission_id") not in blocked
        ]


    def _schema_form_phase_error(self, form: dict) -> str:
        """Reject form submissions outside their declared submit_phase."""
        submit_phase = form.get("submit_phase")
        if not submit_phase:
            return ""
        current_phase = self.dm.schema_phase_id or ""
        if current_phase == submit_phase:
            return ""
        return (
            f"Form {form.get('form_id', '')} can only be submitted during phase "
            f"{submit_phase}; current phase is {current_phase or 'not_started'}."
        )


    def _ensure_schema_clue_public_state(self, clue_id: str):
        """Rebuild public clue bookkeeping for old saves or duplicate releases."""
        clue = self.dm._get_clue_record(clue_id)
        if not clue:
            return
        if clue_id not in self.dm.released_clues:
            self.dm.released_clues.append(clue_id)
        if self.is_schema_active() and clue_id in self._schema_clues():
            if clue_id not in self.dm.schema_released_clue_ids:
                self.dm.schema_released_clue_ids.append(clue_id)
            self._append_public_knowledge(
                "clues",
                {
                    "clue_id": clue_id,
                    "title": clue["name"],
                    "content": clue["content"],
                    "phase_id": self.dm.schema_phase_id,
                },
                "clue_id",
            )
            self._mark_schema_reveal_rules_for_target("clue", clue_id)
        if clue_id not in self.dm.clue_attention:
            self.dm._register_clue_release(clue_id)


    def _sync_schema_runtime_after_load(self):
        """Normalize schema runtime fields after save/load without advancing flow."""
        self._coerce_schema_runtime_defaults()
        if not self.is_schema_active():
            return
        valid_phase_ids = {phase.get("phase_id") for phase in self._schema_phases_sorted()}
        if self.dm.schema_phase_id and self.dm.schema_phase_id not in valid_phase_ids:
            self.dm.schema_runtime_errors.append(f"invalid loaded schema_phase_id: {self.dm.schema_phase_id}")
            self.dm.schema_phase_id = ""
        if not self.dm.schema_phase_id:
            if self.dm.game_phase == "discussion":
                self.dm.schema_phase_id = self._find_schema_phase_by_type("free_discussion") or self._first_schema_phase_id()
            elif self.dm.game_phase in {"opening", "opening_rules"}:
                self.dm.schema_phase_id = self._first_schema_phase_id()
        for clue_id in self._dedupe_schema_list([*self.dm.schema_released_clue_ids, *self.dm.released_clues]):
            if clue_id in self._schema_clues():
                self._ensure_schema_clue_public_state(clue_id)
        for packet_id, packet in list(self.dm.schema_unlocked_role_packets.items()):
            if not isinstance(packet, dict):
                self.dm.schema_unlocked_role_packets.pop(packet_id, None)
                self.dm.schema_packet_visibility.pop(packet_id, None)
                continue
            self.dm.schema_packet_visibility.setdefault(packet_id, packet.get("visibility", "private"))
        self._coerce_schema_runtime_defaults()


    def _schema_phases_sorted(self) -> list[dict]:
        if not self.is_schema_active():
            return []
        phases = [phase for phase in self.dm.script_schema.get("phases", []) if isinstance(phase, dict)]
        return sorted(phases, key=lambda item: (item.get("order", 0), item.get("phase_id", "")))


    def _get_schema_phase(self, phase_id: str) -> Optional[dict]:
        for phase in self._schema_phases_sorted():
            if phase.get("phase_id") == phase_id:
                return phase
        return None


    def _first_schema_phase_id(self) -> str:
        phases = self._schema_phases_sorted()
        return phases[0].get("phase_id", "") if phases else ""


    def _find_schema_phase_by_type(self, phase_type: str) -> str:
        for phase in self._schema_phases_sorted():
            if phase.get("phase_type") == phase_type:
                return phase.get("phase_id", "")
        return ""


    def _find_schema_phase_by_type_after(self, phase_type: str, current_phase_id: str = "") -> str:
        """Find the next phase of a type after the current phase, falling back to any match."""
        current_order = self._schema_phase_order(current_phase_id) if current_phase_id else -1
        fallback = ""
        for phase in self._schema_phases_sorted():
            if phase.get("phase_type") != phase_type:
                continue
            phase_id = phase.get("phase_id", "")
            if not fallback:
                fallback = phase_id
            if self._schema_phase_order(phase_id) > current_order:
                return phase_id
        return fallback


    def _schema_phase_order(self, phase_id: str) -> int:
        phase = self._get_schema_phase(phase_id)
        if not phase:
            return -1
        return int(phase.get("order", -1) or -1)


    def _schema_character_name(self, character_id: str) -> str:
        for character in self._schema_cast():
            if character.get("character_id") == character_id:
                return character.get("display_name", character_id)
        return character_id


    def _schema_character_id_from_name(self, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        for character in self._schema_cast():
            character_id = character.get("character_id", "")
            display_name = character.get("display_name", "")
            if normalized in {str(character_id).casefold(), str(display_name).casefold()}:
                return character_id
        return str(value or "").strip()


    def _schema_assets_by_id(self) -> dict:
        if not self.is_schema_active():
            return {}
        return {
            asset.get("asset_id"): asset
            for asset in self.dm.script_schema.get("assets", [])
            if isinstance(asset, dict) and asset.get("asset_id")
        }


    def _schema_forms_by_id(self) -> dict:
        if not self.is_schema_active():
            return {}
        return {
            form.get("form_id"): form
            for form in self.dm.script_schema.get("forms", [])
            if isinstance(form, dict) and form.get("form_id")
        }


    def _schema_known_character_ids(self) -> set[str]:
        return {
            character.get("character_id")
            for character in self._schema_cast()
            if isinstance(character, dict) and character.get("character_id")
        }


    def _normalize_schema_character_ref(self, value: str) -> str:
        character_id = self._schema_character_id_from_name(value)
        return character_id if character_id in self._schema_known_character_ids() else ""


    def _public_declaration_record(self, submission: dict) -> dict:
        return {
            "declaration_id": f"declaration_{submission['submission_id']}",
            "submission_id": submission["submission_id"],
            "actor_id": submission["actor_id"],
            "actor_name": submission["actor_name"],
            "declaration": submission.get("declaration", ""),
        }


    def _public_resolution_event(self, result: dict) -> dict:
        return {
            "event_id": f"event_{result['result_id']}",
            "result_id": result["result_id"],
            "action_type": result.get("action_type", ""),
            "actor_id": result.get("actor_id", ""),
            "target_id": result.get("target_id", ""),
            "status": result.get("status", ""),
            "reason": result.get("reason", ""),
        }


    def _append_public_knowledge(self, bucket: str, record: dict, identity_key: str):
        """Add one public record once; this is the anti-leak boundary."""
        self._coerce_schema_runtime_defaults()
        identity = record.get(identity_key)
        if not identity:
            return
        items = self.dm.schema_public_knowledge.setdefault(bucket, [])
        if any(item.get(identity_key) == identity for item in items if isinstance(item, dict)):
            return
        items.append(record)


    def _warn_schema_runtime_once(self, message: str):
        """Store schema runtime warnings once so bad optional rules are visible."""
        self._coerce_schema_runtime_defaults()
        if message not in self.dm.schema_runtime_errors:
            self.dm.schema_runtime_errors.append(message)


    def _schema_public_text_forbidden_hits(self, text: str) -> list[str]:
        """Check public user-supplied text with the same local anti-spoiler boundary."""
        content = str(text or "")
        forbidden = self.dm._get_schema_forbidden_words()
        if "clue_1" not in self.dm.released_clues:
            forbidden.extend(("合页", "撬痕"))
        if "clue_2" not in self.dm.released_clues:
            forbidden.extend(("钥匙", "画框后的钥匙"))
        forbidden.extend((
            "犯人是狼", "真凶是狼", "真正的犯人是狼", "狼后来撬开",
            "狼把孩童", "孩童衣服的碎片", "女巫发现等候室里还有人类后，用钥匙把孩童藏",
        ))
        return [word for word in forbidden if word and word in content]


    def _sanitize_schema_public_text(self, text: str, context: str) -> str:
        """Redact forbidden spoiler text before it enters public knowledge."""
        content = str(text or "").strip()
        hits = self._schema_public_text_forbidden_hits(content)
        if not hits:
            return content
        self._warn_schema_runtime_once(f"{context}: public text blocked by forbidden_spoilers ({len(hits)} hit)")
        return "[REDACTED: forbidden spoiler blocked]"


    def _matching_schema_reveal_rules(
        self,
        target_type: str,
        target_id: str,
        phase_id: Optional[str] = None,
    ) -> list[dict]:
        rules = []
        for rule in self._schema_reveal_rules():
            if rule.get("target_type") != target_type or rule.get("target_id") != target_id:
                continue
            if phase_id and rule.get("phase_id") not in {"", None, phase_id}:
                continue
            rules.append(rule)
        return rules


    def _mark_schema_reveal_rules_for_target(
        self,
        target_type: str,
        target_id: str,
        phase_id: Optional[str] = None,
    ):
        self._coerce_schema_runtime_defaults()
        for rule in self._matching_schema_reveal_rules(target_type, target_id, phase_id):
            rule_id = rule.get("rule_id")
            if rule_id and rule_id not in self.dm.schema_revealed_rule_ids:
                self.dm.schema_revealed_rule_ids.append(rule_id)


    def _read_schema_workspace_text_ref(self, content_ref: str) -> str:
        """Read a workspace-local text ref; never follows paths outside the repo."""
        repo_root = Path(__file__).resolve().parent
        candidate = (repo_root / content_ref).resolve()
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            self.dm.schema_runtime_errors.append(f"content_ref outside workspace: {content_ref}")
            return ""
        if candidate.suffix.lower() not in {".txt", ".md", ".text"}:
            self.dm.schema_runtime_errors.append(f"unsupported content_ref type: {content_ref}")
            return ""
        try:
            return candidate.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            self.dm.schema_runtime_errors.append(f"failed to read content_ref {content_ref}: {exc}")
            return ""


    def _resolve_role_packet_content(self, packet: dict) -> str:
        """Read inline content or a workspace-local text content_ref only."""
        content = packet.get("content")
        if isinstance(content, str) and content.strip():
            return content
        content_ref = (packet.get("content_ref") or "").strip()
        if not content_ref:
            return ""
        return self._read_schema_workspace_text_ref(content_ref)


    def _unlock_schema_role_packet(self, packet: dict, phase_id: str) -> tuple[str, str]:
        """Unlock a packet without leaking private text into public output."""
        self._coerce_schema_runtime_defaults()
        packet_id = packet.get("packet_id")
        if not packet_id:
            return "", ""
        if packet_id in self.dm.schema_unlocked_role_packets:
            return "", ""

        rules = self._matching_schema_reveal_rules("role_packet", packet_id, phase_id)
        rule_after_visibility = next((rule.get("after_reveal_visibility") for rule in rules if rule.get("after_reveal_visibility")), "")
        for rule in rules:
            rule_id = rule.get("rule_id")
            if rule_id and rule_id not in self.dm.schema_revealed_rule_ids:
                self.dm.schema_revealed_rule_ids.append(rule_id)

        content = self._resolve_role_packet_content(packet)
        character_id = packet.get("character_id", "")
        display_name = self._schema_character_name(character_id)
        visibility = packet.get("visibility", "private")
        after_visibility = rule_after_visibility or packet.get("after_reveal_visibility", visibility)
        reveal_instruction = packet.get("reveal_instruction", "may_share")
        recipients = packet.get("recipients", []) or []
        public_now = (
            visibility == "public"
            or after_visibility == "public"
            and reveal_instruction in {"must_read_aloud", "reveal_at_phase_start"}
        )

        record = {
            "packet_id": packet_id,
            "character_id": character_id,
            "display_name": display_name,
            "phase_id": phase_id,
            "visibility": visibility,
            "after_reveal_visibility": after_visibility,
            "reveal_instruction": reveal_instruction,
            "recipients": recipients,
            "content": content,
            "content_ref": packet.get("content_ref", ""),
        }
        self.dm.schema_unlocked_role_packets[packet_id] = record
        self.dm.schema_packet_visibility[packet_id] = "public" if public_now else visibility

        if public_now:
            public_record = dict(record)
            self._append_public_knowledge("role_packets", public_record, "packet_id")
            return f"[Role Packet Public] {display_name}: {content}", ""

        if packet.get("content_ref") and not content:
            return "", f"[Private Packet] {display_name}: content_ref exists but could not be read."
        return "", f"[Private Packet] {display_name}: unlocked for host/private delivery ({reveal_instruction})."


    def _release_schema_material(self, material_id: str) -> str:
        self._coerce_schema_runtime_defaults()
        if not material_id or material_id in self.dm.schema_released_material_ids:
            return ""
        self.dm.schema_released_material_ids.append(material_id)
        assets = self._schema_assets_by_id()
        forms = self._schema_forms_by_id()
        if material_id in assets:
            asset = assets[material_id]
            record = {
                "material_id": material_id,
                "material_type": "asset",
                "asset_type": asset.get("asset_type", ""),
                "path": asset.get("path", ""),
                "description": asset.get("description", ""),
                "linked_clue_id": asset.get("linked_clue_id"),
                "visibility": asset.get("visibility", ""),
            }
            self._append_public_knowledge("materials", record, "material_id")
            self._mark_schema_reveal_rules_for_target("asset", material_id, self.dm.schema_phase_id)
            return f"[Material] {material_id}: {record['description'] or record['path']}"
        if material_id in forms:
            form = forms[material_id]
            record = {
                "material_id": material_id,
                "material_type": "form",
                "form_type": form.get("form_type", ""),
                "title": form.get("title", material_id),
                "visibility": "public",
            }
            self._append_public_knowledge("materials", record, "material_id")
            self._mark_schema_reveal_rules_for_target("form", material_id, self.dm.schema_phase_id)
            return f"[Form] {record['title']} is available for manual use."
        record = {"material_id": material_id, "material_type": "public_material", "visibility": "public"}
        self._append_public_knowledge("materials", record, "material_id")
        self._mark_schema_reveal_rules_for_target("public_material", material_id, self.dm.schema_phase_id)
        return f"[Material] {material_id} is marked released."


    def _release_schema_clue(self, clue_id: str, update_game_phase: bool = True, duplicate_text: bool = True) -> str:
        clue = self.dm._get_clue_record(clue_id)
        if not clue:
            return "未找到对应线索。"
        self._coerce_schema_runtime_defaults()
        already_released = clue_id in self.dm.released_clues or clue_id in self.dm.schema_released_clue_ids
        if already_released:
            self._ensure_schema_clue_public_state(clue_id)
            self.dm._refresh_system_prompt()
            return f"{clue['name']} 已经公开过了。" if duplicate_text else ""

        self._ensure_schema_clue_public_state(clue_id)
        self.dm._register_clue_release(clue_id)
        self.dm.last_clue_release_turn = self.dm.turn_count
        self.dm._mark_player_activity()
        if update_game_phase:
            self.dm._set_game_phase("discussion")
        self.dm._refresh_system_prompt()
        return self.dm._build_clue_reveal_text(clue_id)


    def _legacy_phase_for_schema_phase(self, phase: dict) -> str:
        phase_type = phase.get("phase_type")
        if phase_type == "intro":
            return "opening_rules"
        if phase_type in {"free_discussion", "search", "discovery", "examination", "accusation"}:
            return "discussion"
        if phase_type in {"resolution", "confession_chain"}:
            return "owner_confrontation"
        if phase_type == "recap":
            return "postgame_review"
        return self.dm.game_phase


    def _enter_schema_phase(
        self,
        phase_id: str,
        emit_text: bool = True,
        update_legacy_phase: bool = True,
    ) -> str:
        """Enter one schema phase and apply release side effects once."""
        if not self.is_schema_active():
            return ""
        self._coerce_schema_runtime_defaults()
        phase = self._get_schema_phase(phase_id)
        if not phase:
            return f"未找到 schema 阶段：{phase_id}"

        self.dm.schema_phase_id = phase_id
        if phase_id not in self.dm.schema_entered_phase_ids:
            self.dm.schema_entered_phase_ids.append(phase_id)
        if update_legacy_phase:
            self.dm._set_game_phase(self._legacy_phase_for_schema_phase(phase))

        public_lines = []
        private_lines = []
        if emit_text:
            public_lines.append(f"[Schema Phase] {phase.get('title', phase_id)}")
            instructions = phase.get("dm_instructions", {}) if isinstance(phase.get("dm_instructions"), dict) else {}
            opening_text = instructions.get("opening_text")
            pace_notes = instructions.get("pace_notes")
            if opening_text:
                public_lines.append(str(opening_text))
            if pace_notes:
                public_lines.append(f"DM pace note: {pace_notes}")

        for material_id in phase.get("materials_to_release", []) or []:
            line = self._release_schema_material(material_id)
            if emit_text and line:
                public_lines.append(line)

        for packet in self.dm.script_schema.get("role_packets", []):
            if isinstance(packet, dict) and packet.get("phase_id") == phase_id:
                public_text, private_notice = self._unlock_schema_role_packet(packet, phase_id)
                if emit_text and public_text:
                    public_lines.append(public_text)
                if emit_text and private_notice:
                    private_lines.append(private_notice)

        for clue_id in phase.get("clues_to_reveal", []) or []:
            clue_text = self._release_schema_clue(clue_id, update_game_phase=False, duplicate_text=False)
            if emit_text and clue_text:
                public_lines.append(clue_text)

        if emit_text and phase.get("phase_type") == "accusation":
            public_lines.append("当前只开放人工收束：如需进入旧流程最终答案录入，请输入 /vote。")

        self.dm._refresh_system_prompt()
        return "\n\n".join([*public_lines, *private_lines]).strip()


    def advance_schema_phase(self, target_phase_id: Optional[str] = None) -> str:
        """Operator entry point for Phase 5: /phase next or /phase <phase_id>."""
        if not self.is_schema_active():
            return "当前没有启用可运行的 ScriptSchema，仍使用旧流程。"
        phases = self._schema_phases_sorted()
        if not phases:
            return "当前 schema 没有阶段定义。"
        if target_phase_id and target_phase_id != "next":
            if not self._get_schema_phase(target_phase_id):
                return f"未找到 schema 阶段：{target_phase_id}"
            return self._enter_schema_phase(target_phase_id)

        current_id = self.dm.schema_phase_id or self._first_schema_phase_id()
        current_index = next((index for index, phase in enumerate(phases) if phase.get("phase_id") == current_id), -1)
        next_index = current_index + 1
        if current_index < 0:
            next_index = 0
        if next_index >= len(phases):
            return "已经是 schema 的最后一个阶段。"
        return self._enter_schema_phase(phases[next_index].get("phase_id"))


    def submit_schema_form(self, actor: str, form_id: str, fields: dict) -> str:
        """Submit one deterministic schema form; no LLM interpretation is used."""
        if not self.is_schema_active():
            return "Schema runtime is not active; using legacy flow."
        if not self._schema_actions_enabled():
            return "This script does not enable action_rules; schema action runtime is inactive."
        self._coerce_schema_runtime_defaults()
        forms = self._schema_forms_by_id()
        form = forms.get(form_id)
        if not form:
            return f"Unknown schema form: {form_id}"
        actor_id = self._normalize_schema_character_ref(actor)
        if not actor_id:
            return f"Unknown actor: {actor}"
        phase_error = self._schema_form_phase_error(form)
        if phase_error:
            return phase_error
        fields = fields if isinstance(fields, dict) else {}
        action_type = self._normalize_schema_action_type(fields.get("action") or fields.get("decisive_action") or "")
        vote_target = fields.get("vote", "")
        declaration = (fields.get("declaration") or "").strip()
        if not action_type:
            if vote_target or form.get("form_type") == "vote_card":
                action_type = "VOTE"
            elif declaration:
                action_type = "DECLARE"
        if not action_type:
            return "Missing action/decisive_action, vote, or declaration field."

        allowed_actions = self._schema_action_types() | {"MURDER", "GUARD", "INVESTIGATE", "VOTE", "DECLARE"}
        if action_type not in allowed_actions:
            return f"Unsupported schema action type: {action_type}"

        target_value = fields.get("target") or vote_target
        target_id = self._normalize_schema_character_ref(target_value) if target_value else ""
        if action_type in {"MURDER", "GUARD", "INVESTIGATE", "VOTE"} and not target_id:
            return f"{action_type} requires a valid target/vote character."
        if action_type == "DECLARE" and not declaration:
            return "DECLARE requires a declaration field."
        if action_type == "DECLARE":
            declaration = self._sanitize_schema_public_text(declaration, "schema declaration")
            fields = dict(fields)
            fields["declaration"] = declaration

        replaced_ids = self._replace_prior_schema_submission(actor_id, form_id, form)
        self._remove_public_declarations_for_submissions(replaced_ids)
        submission_id = f"submission_{len(self.dm.schema_form_submissions) + 1}"
        submission = {
            "submission_id": submission_id,
            "order": len(self.dm.schema_form_submissions) + 1,
            "actor_id": actor_id,
            "actor_name": self._schema_character_name(actor_id),
            "form_id": form_id,
            "form_type": form.get("form_type", ""),
            "action_type": action_type,
            "target_id": target_id,
            "target_name": self._schema_character_name(target_id) if target_id else "",
            "declaration": declaration,
            "fields": dict(fields),
            "status": "submitted",
        }
        if replaced_ids:
            submission["replaces"] = replaced_ids
        self.dm.schema_form_submissions.append(submission)
        if action_type == "DECLARE":
            self._append_public_knowledge("declarations", self._public_declaration_record(submission), "declaration_id")
        self.dm._refresh_system_prompt()
        replacement_note = f" Replaced previous submission(s): {', '.join(replaced_ids)}." if replaced_ids else ""
        if action_type == "DECLARE":
            return f"Declaration submitted by {submission['actor_name']}: {declaration}.{replacement_note}"
        target_text = f" -> {submission['target_name']}" if submission["target_name"] else ""
        return f"Schema form submitted: {submission['actor_name']} {action_type}{target_text}.{replacement_note}"


    def resolve_schema_actions(self) -> str:
        """Resolve generic schema actions in resolution_order before tallying votes."""
        if not self.is_schema_active():
            return "Schema runtime is not active; using legacy flow."
        if not self._schema_actions_enabled():
            return "This script does not enable action_rules; schema action runtime is inactive."
        self._coerce_schema_runtime_defaults()
        active_submissions = [item for item in self.dm.schema_form_submissions if self._schema_submission_is_active(item)]
        if not active_submissions:
            return "No schema form submissions to resolve."

        self._reset_character_state_for_resolution()
        self.dm.schema_action_results = []
        self.dm.schema_vote_tally = {}
        self.dm.schema_public_knowledge["resolution_events"] = []

        submissions = sorted(active_submissions, key=self._schema_action_sort_key)
        route_phase_before = self.dm.schema_phase_id
        for submission in submissions:
            action_type = submission.get("action_type")
            if action_type == "GUARD":
                self._record_schema_action_result(submission, "resolved", "guard_recorded")
            elif action_type == "MURDER":
                self._resolve_schema_murder(submission, submissions)
            elif action_type == "INVESTIGATE":
                self._resolve_schema_investigate(submission)
            elif action_type == "DECLARE":
                self._resolve_schema_declare(submission)
            elif action_type == "VOTE":
                self._resolve_schema_vote(submission)
            else:
                self._record_schema_action_result(submission, "invalid", "unsupported_action")

        route_line = self._apply_schema_resolution_phase_route(submissions, route_phase_before)
        self.dm._refresh_system_prompt()
        tally_text = ", ".join(f"{self._schema_character_name(target)}={count}" for target, count in sorted(self.dm.schema_vote_tally.items()))
        result_lines = [
            f"{result.get('action_type')} {result.get('actor_id')}->{result.get('target_id')}: {result.get('status')} ({result.get('reason')})"
            for result in self.dm.schema_action_results
            if result.get("action_type") != "INVESTIGATE"
        ]
        if tally_text:
            result_lines.append(f"Vote tally: {tally_text}")
        if route_line:
            result_lines.append(route_line)
        return "Schema actions resolved.\n" + "\n".join(result_lines)


    def _schema_final_reveal_sequence(self) -> list[dict]:
        """Return the configured final reveal sequence sorted by numeric step."""
        if not self.is_schema_active():
            return []
        sequence = self.dm.script_schema.get("ending_rules", {}).get("final_reveal_sequence", [])
        items = [item for item in sequence if isinstance(item, dict)]
        return sorted(items, key=lambda item: int(item.get("step", 0) or 0))


    def _schema_final_reveal_phase_allowed(self) -> bool:
        """Final reveal is only public once the game has reached a terminal-facing phase."""
        phase = self._get_schema_phase(self.dm.schema_phase_id)
        phase_type = phase.get("phase_type") if phase else ""
        if phase_type in {"accusation", "resolution", "confession_chain", "recap"}:
            return True
        return self.dm.game_phase in {"vote", "owner_confrontation", "ending", "postgame_review"}


    def _next_schema_final_reveal_step(self) -> Optional[dict]:
        revealed = {int(step) for step in getattr(self.dm, "schema_final_reveal_steps", []) if str(step).isdigit()}
        for item in self._schema_final_reveal_sequence():
            step = int(item.get("step", 0) or 0)
            if step not in revealed:
                return item
        return None


    def _resolve_schema_final_reveal_content(self, content_ref: str) -> tuple[str, str, str]:
        """Resolve final reveal content_ref from schema ids or workspace text files."""
        ref = str(content_ref or "").strip()
        if not ref:
            return "unknown", "", ""

        for node in self.dm.script_schema.get("truth_model", {}).get("truth_nodes", []):
            if isinstance(node, dict) and node.get("node_id") == ref:
                return "truth_node", ref, str(node.get("content", ""))

        clue = self._schema_clues().get(ref)
        if clue:
            title = clue.get("title", ref)
            return "clue", title, str(clue.get("content", ""))

        for packet in self.dm.script_schema.get("role_packets", []):
            if isinstance(packet, dict) and packet.get("packet_id") == ref:
                return "role_packet", ref, self._resolve_role_packet_content(packet)

        asset = self._schema_assets_by_id().get(ref)
        if asset:
            content = asset.get("description") or asset.get("path") or ref
            return "asset", ref, str(content)

        if ref.startswith("ending_text"):
            for condition in self.dm.script_schema.get("ending_rules", {}).get("conditions", []):
                if isinstance(condition, dict) and condition.get("ending_text_ref") == ref:
                    return "ending_text", condition.get("ending_title", ref), str(condition.get("ending_title", ref))
            return "ending_text", ref, ref

        if Path(ref).suffix.lower() in {".txt", ".md", ".text"}:
            return "text_file", ref, self._read_schema_workspace_text_ref(ref)

        self._warn_schema_runtime_once(f"final_reveal content_ref could not be resolved: {ref}")
        return "unknown", ref, ""


    def reveal_next_schema_final_step(self, code_word: str = "", condition: str = "") -> str:
        """Reveal one final_reveal_sequence step; no scoring or LLM judgement is involved."""
        if not self.is_schema_active():
            return "Schema runtime is not active; using legacy flow."
        self._coerce_schema_runtime_defaults()
        if not self._schema_final_reveal_phase_allowed():
            return "Final reveal is only available after accusation, resolution, confession_chain, or recap has begun."

        step = self._next_schema_final_reveal_step()
        if not step:
            return "Final reveal sequence complete."

        expected_code = str(step.get("required_code_word") or "").strip()
        supplied_code = str(code_word or "").strip()
        if expected_code and supplied_code.casefold() != expected_code.casefold():
            return f"Final reveal step {step.get('step')} requires code_word: {expected_code}"

        ref_type, title, content = self._resolve_schema_final_reveal_content(step.get("content_ref", ""))
        if not content:
            return f"Final reveal step {step.get('step')} has no readable content for ref: {step.get('content_ref')}"

        step_number = int(step.get("step", 0) or 0)
        speaker_id = step.get("speaker_character_id")
        record = {
            "step": step_number,
            "trigger": step.get("trigger", ""),
            "speaker_character_id": speaker_id,
            "speaker_name": self._schema_character_name(speaker_id) if speaker_id else "",
            "required_code_word": expected_code,
            "content_ref": step.get("content_ref", ""),
            "content_type": ref_type,
            "title": title,
            "content": content,
            "next_step_condition": step.get("next_step_condition"),
            "condition_note": condition or "",
        }
        if step_number not in self.dm.schema_final_reveal_steps:
            self.dm.schema_final_reveal_steps.append(step_number)
        self._append_public_knowledge("final_reveals", record, "step")
        if ref_type == "truth_node":
            self._mark_schema_reveal_rules_for_target("truth_node", str(step.get("content_ref", "")), self.dm.schema_phase_id)
        self.dm._refresh_system_prompt()

        lines = [
            f"[Final Reveal Step {step_number}] {title}",
            content,
        ]
        if speaker_id:
            lines.insert(1, f"Speaker: {record['speaker_name']}")
        if step.get("next_step_condition"):
            lines.append(f"Next step condition: {step.get('next_step_condition')}")
        return "\n".join(line for line in lines if line)


    def _schema_resolution_signature(self, submissions: list[dict]) -> str:
        """Stable signature so repeated /schema resolve does not keep advancing phases."""
        signature_payload = [
            {
                "submission_id": item.get("submission_id", ""),
                "actor_id": item.get("actor_id", ""),
                "form_id": item.get("form_id", ""),
                "action_type": item.get("action_type", ""),
                "target_id": item.get("target_id", ""),
                "declaration": item.get("declaration", ""),
            }
            for item in submissions
        ]
        return json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)


    def _schema_resolution_target_phase(self, phase_before: str) -> tuple[str, str]:
        """Minimal local routing: murder creates accusation, otherwise continue cleanly."""
        murder_success = any(
            result.get("action_type") == "MURDER"
            and result.get("status") == "resolved"
            and result.get("reason") == "murder_success"
            for result in self.dm.schema_action_results
        )
        if murder_success:
            return self._find_schema_phase_by_type_after("accusation", phase_before), "murder_resolved"

        before_phase = self._get_schema_phase(phase_before) or {}
        if before_phase.get("phase_type") != "resolution":
            resolution_phase = self._find_schema_phase_by_type_after("resolution", phase_before)
            if resolution_phase:
                return resolution_phase, "no_murder_continue_to_resolution"
        recap_phase = self._find_schema_phase_by_type_after("recap", phase_before)
        if recap_phase:
            return recap_phase, "no_murder_continue_to_recap"
        return "", ""


    def _apply_schema_resolution_phase_route(self, submissions: list[dict], phase_before: str) -> str:
        """Apply deterministic action-result phase routing without touching ending/scoring."""
        signature = self._schema_resolution_signature(submissions)
        previous = self.dm.schema_last_resolution_route if isinstance(self.dm.schema_last_resolution_route, dict) else {}
        target_phase = ""
        reason = ""
        if previous.get("signature") == signature and previous.get("phase_id"):
            target_phase = previous.get("phase_id", "")
            reason = previous.get("reason", "")
        else:
            target_phase, reason = self._schema_resolution_target_phase(phase_before)
            if target_phase:
                self.dm.schema_last_resolution_route = {
                    "signature": signature,
                    "phase_id": target_phase,
                    "reason": reason,
                }

        if not target_phase:
            return ""
        if self.dm.schema_phase_id != target_phase:
            self._enter_schema_phase(target_phase, emit_text=False)
        return f"Next schema phase: {target_phase} ({reason})."


    def _record_schema_action_result(
        self,
        submission: dict,
        status: str,
        reason: str,
        *,
        private_result: Optional[dict] = None,
        public_event: bool = True,
    ) -> dict:
        result = {
            "result_id": f"result_{len(self.dm.schema_action_results) + 1}",
            "submission_id": submission.get("submission_id", ""),
            "actor_id": submission.get("actor_id", ""),
            "target_id": submission.get("target_id", ""),
            "action_type": submission.get("action_type", ""),
            "status": status,
            "reason": reason,
        }
        if private_result is not None:
            result["private_for"] = submission.get("actor_id", "")
            result["private_result"] = private_result
        self.dm.schema_action_results.append(result)
        if public_event:
            self._append_public_knowledge("resolution_events", self._public_resolution_event(result), "event_id")
        return result


    def _schema_murder_block_rule(self, submission: dict, submissions: list[dict]) -> Optional[dict]:
        supported_keys = {
            "rule_id",
            "blocked_action_type",
            "blocked_when",
            "blocked_by_action_type",
            "minimum_block_count",
            "same_target_required",
            "result",
        }
        for rule in self._schema_action_rules().get("blocking_rules", []):
            if not isinstance(rule, dict):
                self._warn_schema_runtime_once("unsupported blocking_rule: non-object rule ignored")
                continue
            unsupported_keys = sorted(set(rule) - supported_keys)
            if unsupported_keys:
                self._warn_schema_runtime_once(
                    f"unsupported blocking_rule fields ignored in {rule.get('rule_id', 'unnamed')}: {', '.join(unsupported_keys)}"
                )
            blocked_action = self._normalize_schema_action_type(rule.get("blocked_action_type", ""))
            if blocked_action != "MURDER":
                self._warn_schema_runtime_once(
                    f"unsupported blocking_rule target ignored in {rule.get('rule_id', 'unnamed')}: {blocked_action or 'missing'}"
                )
                continue
            blocked_by = self._normalize_schema_action_type(rule.get("blocked_by_action_type", ""))
            if not blocked_by:
                self._warn_schema_runtime_once(
                    f"unsupported blocking_rule ignored in {rule.get('rule_id', 'unnamed')}: missing blocked_by_action_type"
                )
                continue
            try:
                minimum = max(1, int(rule.get("minimum_block_count", 1) or 1))
            except (TypeError, ValueError):
                self._warn_schema_runtime_once(
                    f"unsupported blocking_rule value in {rule.get('rule_id', 'unnamed')}: minimum_block_count"
                )
                minimum = 1
            same_target = bool(rule.get("same_target_required", False))
            count = 0
            for candidate in submissions:
                if candidate.get("action_type") != blocked_by:
                    continue
                if same_target and candidate.get("target_id") != submission.get("target_id"):
                    continue
                count += 1
            if count >= minimum:
                return rule
        return None


    def _schema_murder_payload(self) -> dict:
        for outcome in self._schema_action_rules().get("outcomes", []):
            if not isinstance(outcome, dict):
                continue
            trigger = str(outcome.get("trigger_condition", "")).upper()
            if "MURDER" in trigger and isinstance(outcome.get("result_payload"), dict):
                return outcome["result_payload"]
        return {"state": "dead", "voting_eligible": False, "candidate_eligible": False}


    def _apply_schema_character_payload(self, character_id: str, payload: dict):
        state = self.dm.character_state.setdefault(character_id, self._default_character_state())
        if "alive" in payload:
            state["alive"] = bool(payload["alive"])
        if payload.get("state") == "dead":
            state["alive"] = False
        if "can_vote" in payload:
            state["can_vote"] = bool(payload["can_vote"])
        if "voting_eligible" in payload:
            state["can_vote"] = bool(payload["voting_eligible"])
        if "can_be_candidate" in payload:
            state["can_be_candidate"] = bool(payload["can_be_candidate"])
        if "candidate_eligible" in payload:
            state["can_be_candidate"] = bool(payload["candidate_eligible"])


    def _resolve_schema_murder(self, submission: dict, submissions: list[dict]):
        block_rule = self._schema_murder_block_rule(submission, submissions)
        if block_rule:
            self._record_schema_action_result(submission, "blocked", block_rule.get("result", block_rule.get("rule_id", "blocked")))
            return
        target_id = submission.get("target_id", "")
        self._apply_schema_character_payload(target_id, self._schema_murder_payload())
        self._record_schema_action_result(submission, "resolved", "murder_success")


    def _resolve_schema_investigate(self, submission: dict):
        target_id = submission.get("target_id", "")
        target_state = dict(self.dm.character_state.get(target_id, self._default_character_state()))
        self._record_schema_action_result(
            submission,
            "resolved",
            "private_investigation_result",
            private_result={"target_id": target_id, "target_state": target_state},
            public_event=False,
        )


    def _resolve_schema_declare(self, submission: dict):
        self._append_public_knowledge("declarations", self._public_declaration_record(submission), "declaration_id")
        self._record_schema_action_result(submission, "resolved", "declaration_public")


    def _resolve_schema_vote(self, submission: dict):
        actor_state = self.dm.character_state.get(submission.get("actor_id"), self._default_character_state())
        target_state = self.dm.character_state.get(submission.get("target_id"), self._default_character_state())
        if not actor_state.get("can_vote", True):
            self._record_schema_action_result(submission, "invalid", "actor_cannot_vote")
            return
        if not target_state.get("can_be_candidate", True):
            self._record_schema_action_result(submission, "invalid", "target_not_candidate")
            return
        target_id = submission.get("target_id", "")
        self.dm.schema_vote_tally[target_id] = int(self.dm.schema_vote_tally.get(target_id, 0)) + 1
        self._record_schema_action_result(submission, "resolved", "vote_counted")


    def get_unlocked_role_packets(self, character_id_or_name: str) -> list[dict]:
        """Host/private-channel helper; never marks packets as public."""
        self._coerce_schema_runtime_defaults()
        character_id = self._schema_character_id_from_name(character_id_or_name)
        packets = []
        for packet in self.dm.schema_unlocked_role_packets.values():
            if packet.get("character_id") == character_id or packet.get("display_name") == character_id_or_name:
                packets.append(dict(packet))
        return packets


    def get_schema_runtime_state(self) -> dict:
        self._coerce_schema_runtime_defaults()
        return {
            "schema_phase_id": self.dm.schema_phase_id,
            "schema_entered_phase_ids": list(self.dm.schema_entered_phase_ids),
            "schema_public_knowledge": self.dm.schema_public_knowledge,
            "schema_released_material_ids": list(self.dm.schema_released_material_ids),
            "schema_released_clue_ids": list(self.dm.schema_released_clue_ids),
            "schema_unlocked_role_packets": self.dm.schema_unlocked_role_packets,
            "schema_packet_visibility": dict(self.dm.schema_packet_visibility),
            "schema_revealed_rule_ids": list(self.dm.schema_revealed_rule_ids),
            "schema_runtime_errors": list(self.dm.schema_runtime_errors),
            "character_state": self.dm.character_state,
            "schema_form_submissions": list(self.dm.schema_form_submissions),
            "schema_action_results": list(self.dm.schema_action_results),
            "schema_vote_tally": dict(self.dm.schema_vote_tally),
            "schema_last_resolution_route": dict(self.dm.schema_last_resolution_route),
            "schema_final_reveal_steps": list(self.dm.schema_final_reveal_steps),
        }


    def _build_schema_shadow_payload(self) -> dict:
        """Model-facing schema payload: public runtime data only."""
        if not self.is_schema_active():
            return {}
        self._coerce_schema_runtime_defaults()
        public_cast = [
            {
                "character_id": character.get("character_id"),
                "display_name": character.get("display_name"),
                "public_profile": character.get("public_profile"),
            }
            for character in self.dm.script_schema.get("cast", [])
            if isinstance(character, dict)
        ]
        public_clues = [
            {"clue_id": item.get("clue_id"), "title": item.get("title"), "content": item.get("content")}
            for item in self.dm.schema_public_knowledge.get("clues", [])
            if isinstance(item, dict)
        ]
        return {
            "schema_version": self.dm.script_schema.get("schema_version"),
            "script_info": self.dm.script_schema.get("script_info", {}),
            "current_phase": self.dm.schema_phase_id,
            "public_materials": self.dm.script_schema.get("public_materials", {}),
            "cast_public": public_cast,
            "phases": self.dm.script_schema.get("phases", []),
            "public_knowledge": {
                "materials": self.dm.schema_public_knowledge.get("materials", []),
                "clues": public_clues,
                "role_packets": self.dm.schema_public_knowledge.get("role_packets", []),
                "declarations": self.dm.schema_public_knowledge.get("declarations", []),
                "resolution_events": self.dm.schema_public_knowledge.get("resolution_events", []),
                "final_reveals": self.dm.schema_public_knowledge.get("final_reveals", []),
            },
            "released_clue_ids": list(getattr(self.dm, "schema_released_clue_ids", [])),
            "released_material_ids": list(getattr(self.dm, "schema_released_material_ids", [])),
            "revealed_rule_ids": list(getattr(self.dm, "schema_revealed_rule_ids", [])),
            "reveal_rules": self.dm.script_schema.get("reveal_rules", []),
            "hint_rules": self.dm.script_schema.get("hint_rules", []),
            "action_runtime": {
                "enabled": self._schema_actions_enabled(),
                "character_state": self.dm.character_state if self._schema_actions_enabled() else {},
                "vote_tally": self.dm.schema_vote_tally if self._schema_actions_enabled() else {},
            },
            "spoiler_guard": {
                "mode": "local_runtime_filter",
                "note": "Forbidden spoiler contents are filtered locally and are not shown in this prompt.",
            },
        }

