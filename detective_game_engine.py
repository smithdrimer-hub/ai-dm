"""Minimal single-player detective game runtime.

This engine runs GameSchema v0.1 without calling an LLM. It deliberately keeps
the program as the judge: evidence discovery, lie breaking, phase unlocks, and
accusation results are all deterministic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from game_schema import load_game_schema as load_game_schema_v0_1
from game_schema_v0_3 import load_game_schema_v0_3


@dataclass
class ActionResult:
    """Stable structured result for one detective engine action."""

    ok: bool
    action: str
    code: str
    message: str
    phase_id: str
    turn_index: int
    command: str = ""
    target_id: str = ""
    new_evidence_ids: list[str] = field(default_factory=list)
    new_truth_ids: list[str] = field(default_factory=list)
    new_broken_lie_ids: list[str] = field(default_factory=list)
    new_unlocked_scene_ids: list[str] = field(default_factory=list)
    score_delta: int = 0
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.new_evidence_ids = sorted(self.new_evidence_ids)
        self.new_truth_ids = sorted(self.new_truth_ids)
        self.new_broken_lie_ids = sorted(self.new_broken_lie_ids)
        self.new_unlocked_scene_ids = sorted(self.new_unlocked_scene_ids)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of this result."""
        return {
            "ok": self.ok,
            "action": self.action,
            "code": self.code,
            "message": self.message,
            "phase_id": self.phase_id,
            "turn_index": self.turn_index,
            "command": self.command,
            "target_id": self.target_id,
            "new_evidence_ids": list(self.new_evidence_ids),
            "new_truth_ids": list(self.new_truth_ids),
            "new_broken_lie_ids": list(self.new_broken_lie_ids),
            "new_unlocked_scene_ids": list(self.new_unlocked_scene_ids),
            "score_delta": self.score_delta,
            "data": dict(self.data),
        }


class DetectiveGameEngine:
    """Command-oriented runtime for one GameSchema v0.1 detective case."""

    @staticmethod
    def _load_supported_schema(schema_path: Path) -> dict[str, Any]:
        raw = json.loads(schema_path.read_text(encoding="utf-8-sig"))
        version = raw.get("schema_version")
        if version == "game_schema_v0.3":
            return load_game_schema_v0_3(schema_path)
        return load_game_schema_v0_1(schema_path)

    def __init__(self, schema_path: str | Path, *, require_confirmed: bool = True, npc_actor: Any = None):
        self.schema_path = Path(schema_path)
        self.schema = self._load_supported_schema(self.schema_path)
        review_status = self.schema.get("review", {}).get("status")
        if require_confirmed and review_status != "confirmed":
            raise ValueError("GameSchema must be manually confirmed before play.")

        self.npcs_by_id = {item["character_id"]: item for item in self.schema.get("npc_characters", [])}
        self.scenes_by_id = {item["scene_id"]: item for item in self.schema.get("scenes", [])}
        self.evidence_by_id = {item["evidence_id"]: item for item in self.schema.get("evidence", [])}
        self.lies_by_id = {item["lie_id"]: item for item in self.schema.get("lies", [])}
        self.truth_by_id = {item["truth_id"]: item for item in self.schema.get("truth_model", {}).get("truth_nodes", [])}
        self.phases_by_id = {item["phase_id"]: item for item in self.schema.get("phases", [])}
        self.phase_order = sorted(self.schema.get("phases", []), key=lambda item: item.get("order", 0))

        self.current_phase_id = self.schema.get("mechanics", {}).get("starting_phase_id", "")
        self.unlocked_scene_ids: set[str] = set(self.schema.get("public_case", {}).get("initial_available_scene_ids", []))
        self.discovered_evidence_ids: set[str] = {
            item["evidence_id"]
            for item in self.schema.get("evidence", [])
            if item.get("initially_discovered")
        }
        self.clue_state_by_id = self._build_initial_clue_state()
        for evidence_id in self.discovered_evidence_ids:
            self.clue_state_by_id[evidence_id] = "discovered"
        self.unlocked_truth_ids: set[str] = {
            item["truth_id"]
            for item in self.schema.get("truth_model", {}).get("truth_nodes", [])
            if item.get("revealed_by_default")
        }
        self.broken_lie_ids: set[str] = set()
        self.asked_character_ids: set[str] = set()
        self.searched_scene_ids: set[str] = set()
        self.shown_evidence_ids: set[str] = set()

        self.accusation_result: Optional[dict[str, Any]] = None
        self.accusation_history: list[dict[str, Any]] = []
        self.wrong_accusations = 0
        self.game_over = False
        self.won = False
        self.turn_index = 0
        self.action_history: list[dict[str, Any]] = []
        self.history = self.action_history
        self.last_action_result: Optional[ActionResult] = None
        self.npc_actor = npc_actor
        self.conversation_history_by_character: dict[str, list[dict[str, Any]]] = {}
        self.npc_runtime_state = self._build_initial_npc_runtime_state()
        self.npc_action_history: list[dict[str, Any]] = []
        self.visible_npc_events: list[dict[str, Any]] = []
        self._npc_executed_rule_ids: dict[str, set[str]] = {
            character_id: set()
            for character_id in self.npcs_by_id
        }
        self._npc_rule_fire_counts: dict[str, dict[str, int]] = {
            character_id: {}
            for character_id in self.npcs_by_id
        }
        self._npc_rule_last_fired_turn: dict[str, dict[str, int]] = {
            character_id: {}
            for character_id in self.npcs_by_id
        }

        self._apply_phase_unlocks(self.current_phase_id)
        self._refresh_discoverable_clues()
        self._refresh_unlocked_scenes()
        for evidence_id in list(self.discovered_evidence_ids):
            self._unlock_truths_for_evidence(evidence_id)
        self._refresh_truth_unlocks()

    def status_result(self, *, command: str = "/status") -> ActionResult:
        """Return a structured player-facing status summary."""
        phase = self._current_phase()
        discovered = self._format_evidence_list(sorted(self.discovered_evidence_ids)) or "none"
        searchable = self._format_scene_list(sorted(self.unlocked_scene_ids)) or "none"
        searched = self._format_scene_list(sorted(self.searched_scene_ids)) or "none"
        broken = self._format_lie_list(sorted(self.broken_lie_ids)) or "none"
        reachable = self._format_npc_list(self._reachable_npc_ids()) or "none"
        recent_events = self._format_visible_npc_events(self.visible_npc_events[-3:]) or "none"
        message = (
            f"Current phase: {phase.get('title', self.current_phase_id)} ({self.current_phase_id})\n"
            f"Searchable scenes: {searchable}\n"
            f"Searched scenes: {searched}\n"
            f"Discovered evidence: {discovered}\n"
            f"Broken lies: {broken}\n"
            f"Reachable NPCs: {reachable}\n"
            f"Recent NPC events: {recent_events}\n"
            f"Game over: {self._yes_no(self.game_over)}\n"
            f"Won: {self._yes_no(self.won)}\n"
            f"Wrong accusations: {self.wrong_accusations}"
        )
        return self._finalize_result(
            ok=True,
            action="status",
            code="status_ok",
            message=message,
            command=command,
        )

    def get_status_text(self) -> str:
        """Return a compact player-facing status summary."""
        return self.status_result().message

    def search_result(self, area_id: str, *, command: str = "") -> ActionResult:
        """Search one unlocked scene and reveal its evidence."""
        if self.game_over:
            return self._game_already_over_result("search", command=command, target_id=area_id)

        area_id = area_id.strip()
        before = self._state_marker()
        scene = self.scenes_by_id.get(area_id)
        if not scene:
            return self._finalize_result(
                ok=False,
                action="search",
                code="search_area_not_found",
                message=f"Area not found: {area_id}",
                command=command,
                target_id=area_id,
            )
        if area_id not in self.unlocked_scene_ids:
            return self._finalize_result(
                ok=False,
                action="search",
                code="search_scene_locked",
                message=f"Scene is locked: {scene.get('title', area_id)} ({area_id})",
                command=command,
                target_id=area_id,
            )

        self._refresh_discoverable_clues()
        self.searched_scene_ids.add(area_id)
        for evidence_id in scene.get("evidence_ids", []) or []:
            if self._can_discover_evidence(evidence_id, area_id):
                self._discover_evidence(evidence_id)
        self._refresh_truth_unlocks()
        self._refresh_unlocked_scenes()

        self._advance_after_basic_action("search")
        changes = self._changes_since(before)
        if changes["new_evidence_ids"]:
            code = "search_found_evidence"
            lines = [
                f"Search: {scene.get('title', area_id)} ({area_id})",
                str(scene.get("description", "")),
                "Found evidence:",
            ]
            lines.extend(f"- {self._evidence_title(evidence_id)} ({evidence_id})" for evidence_id in changes["new_evidence_ids"])
            message = "\n".join(line for line in lines if line)
        else:
            code = "search_no_new_evidence"
            message = f"Search: {scene.get('title', area_id)} ({area_id})\nNo new evidence found."

        npc_tick = self._run_npc_autonomy_tick(
            {
                "action": "search",
                "area_id": area_id,
                "result_code": code,
                **changes,
            }
        )
        message = self._append_visible_npc_events(message, npc_tick["visible_events"])
        return self._finalize_result(
            ok=True,
            action="search",
            code=code,
            message=message,
            command=command,
            target_id=area_id,
            data={"scene_id": area_id, **npc_tick},
            **changes,
        )

    def search(self, area_id: str) -> str:
        """Search one unlocked scene and reveal its evidence."""
        return self.search_result(area_id).message

    def show_result(self, evidence_id: str, *, command: str = "") -> ActionResult:
        """Show a discovered evidence item."""
        if self.game_over:
            return self._game_already_over_result("show", command=command, target_id=evidence_id)

        evidence_id = evidence_id.strip()
        item = self.evidence_by_id.get(evidence_id)
        if not item:
            return self._finalize_result(
                ok=False,
                action="show",
                code="show_evidence_not_found",
                message=f"Evidence not found: {evidence_id}",
                command=command,
                target_id=evidence_id,
            )
        if evidence_id not in self.discovered_evidence_ids:
            return self._finalize_result(
                ok=False,
                action="show",
                code="show_hidden_evidence",
                message=f"Evidence has not been discovered: {self._evidence_title(evidence_id)} ({evidence_id})",
                command=command,
                target_id=evidence_id,
            )

        self.shown_evidence_ids.add(evidence_id)
        self.clue_state_by_id[evidence_id] = "revealed"
        self._refresh_truth_unlocks()
        confront_lies = item.get("can_confront_lie_ids", []) or []
        confront_text = self._format_lie_list(confront_lies) if confront_lies else "none"
        message = (
            f"Evidence: {item.get('title', evidence_id)} ({evidence_id})\n"
            f"Type: {item.get('evidence_type', 'unknown')}\n"
            f"Content: {item.get('content', '')}\n"
            f"Can break: {confront_text}"
        )
        return self._finalize_result(
            ok=True,
            action="show",
            code="show_ok",
            message=message,
            command=command,
            target_id=evidence_id,
            data={"evidence_id": evidence_id, "can_confront_lie_ids": sorted(confront_lies)},
        )

    def show(self, evidence_id: str) -> str:
        """Show a discovered evidence item."""
        return self.show_result(evidence_id).message

    def ask_result(self, character_id: str, question: str, *, command: str = "") -> ActionResult:
        """Ask an NPC a question and return the judged response."""
        if self.game_over:
            return self._game_already_over_result("ask", command=command, target_id=character_id)

        character_id = character_id.strip()
        npc = self.npcs_by_id.get(character_id)
        if not npc:
            return self._finalize_result(
                ok=False,
                action="ask",
                code="ask_character_not_found",
                message=f"Character not found: {character_id}",
                command=command,
                target_id=character_id,
            )
        if not self._is_npc_reachable(character_id):
            return self._finalize_result(
                ok=False,
                action="ask",
                code="ask_character_unreachable",
                message=f"Character is not reachable: {npc.get('display_name', character_id)} ({character_id})",
                command=command,
                target_id=character_id,
            )

        self.asked_character_ids.add(character_id)
        broken_now: list[dict[str, Any]] = []
        visible_truths = self._visible_truths_for_npc(npc)
        deterministic_response = self._build_npc_response(npc, question, visible_truths, broken_now)

        self._advance_after_basic_action("ask")
        code = "ask_ok"
        npc_tick = self._run_npc_autonomy_tick(
            {
                "action": "ask",
                "character_id": character_id,
                "target_character_id": character_id,
                "question": question,
                "result_code": code,
            }
        )
        selected_action_policy = self._selected_action_policy_for_character(npc_tick["npc_action_policies"], character_id)
        actor_context = self._build_npc_actor_context(
            npc=npc,
            question=question,
            visible_truths=visible_truths,
            broken_now=broken_now,
            judge_result_code=code,
            deterministic_message=deterministic_response,
            selected_action_policy=selected_action_policy,
        )
        response, actor_data = self._render_npc_actor_response(actor_context, deterministic_response)
        response = self._append_visible_npc_events(response, npc_tick["visible_events"])
        self._record_npc_conversation(character_id, question, response, code, actor_data.get("actor_mode", "template"))
        return self._finalize_result(
            ok=True,
            action="ask",
            code=code,
            message=response,
            command=command,
            target_id=character_id,
            data={
                "character_id": character_id,
                "question": question,
                "visible_truth_ids": sorted(truth.get("truth_id", "") for truth in visible_truths),
                "actor_mode": actor_data.get("actor_mode", "template"),
                "actor_error": actor_data.get("actor_error", ""),
                "selected_action_policy": selected_action_policy,
                **npc_tick,
            },
        )

    def ask(self, character_id: str, question: str) -> str:
        """Ask an NPC a question and return text for legacy callers."""
        return self.ask_result(character_id, question).message

    def confront_result(self, character_id: str, evidence_id: str, *, command: str = "") -> ActionResult:
        """Present discovered evidence to an NPC and judge whether it breaks a lie."""
        target_id = f"{character_id.strip()} {evidence_id.strip()}".strip()
        if self.game_over:
            return self._game_already_over_result("confront", command=command, target_id=target_id)

        character_id = character_id.strip()
        evidence_id = evidence_id.strip()
        target_id = f"{character_id} {evidence_id}".strip()
        before = self._state_marker()
        npc = self.npcs_by_id.get(character_id)
        if not npc:
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_character_not_found",
                message=f"Character not found: {character_id}",
                command=command,
                target_id=target_id,
            )
        if not self._is_npc_reachable(character_id):
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_character_unreachable",
                message=f"Character is not reachable: {npc.get('display_name', character_id)} ({character_id})",
                command=command,
                target_id=target_id,
            )

        evidence = self.evidence_by_id.get(evidence_id)
        if not evidence:
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_evidence_not_found",
                message=f"Evidence not found: {evidence_id}",
                command=command,
                target_id=target_id,
            )
        if evidence_id not in self.discovered_evidence_ids:
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_hidden_evidence",
                message=f"Evidence has not been discovered: {self._evidence_title(evidence_id)} ({evidence_id})",
                command=command,
                target_id=target_id,
            )

        npc_lie_ids = set(npc.get("conversation_rules", {}).get("lie_ids", []) or [])
        evidence_lie_ids = set(evidence.get("can_confront_lie_ids", []) or [])
        required_by_lie_ids = {
            lie_id
            for lie_id in npc_lie_ids
            if evidence_id in (self.lies_by_id.get(lie_id, {}).get("required_evidence_ids", []) or [])
        }
        relevant_lie_ids = evidence_lie_ids | required_by_lie_ids
        candidate_lie_ids = sorted(npc_lie_ids & relevant_lie_ids)
        if not candidate_lie_ids:
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_no_matching_lie",
                message=(
                    f"Confront: {npc.get('display_name', character_id)} ({character_id})\n"
                    f"Evidence {self._evidence_title(evidence_id)} ({evidence_id}) does not match an active lie for this character."
                ),
                command=command,
                target_id=target_id,
                data={
                    "character_id": character_id,
                    "evidence_id": evidence_id,
                    "evidence_lie_ids": sorted(evidence_lie_ids),
                    "npc_lie_ids": sorted(npc_lie_ids),
                    "required_by_lie_ids": sorted(required_by_lie_ids),
                },
            )

        open_lie_ids = [lie_id for lie_id in candidate_lie_ids if lie_id not in self.broken_lie_ids]
        if not open_lie_ids:
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_lie_already_broken",
                message=(
                    f"Confront: {npc.get('display_name', character_id)} ({character_id})\n"
                    f"This evidence has already broken the matching lie: {self._format_lie_list(candidate_lie_ids)}"
                ),
                command=command,
                target_id=target_id,
                data={
                    "character_id": character_id,
                    "evidence_id": evidence_id,
                    "candidate_lie_ids": candidate_lie_ids,
                },
            )

        missing_by_lie: dict[str, list[str]] = {}
        breakable_lies = []
        for lie_id in open_lie_ids:
            lie = self.lies_by_id.get(lie_id)
            if not lie:
                continue
            required = set(lie.get("required_evidence_ids", []) or [])
            missing = sorted(required - self.discovered_evidence_ids)
            if missing:
                missing_by_lie[lie_id] = missing
                continue
            breakable_lies.append(lie)

        if not breakable_lies:
            missing_evidence_ids = sorted({item for values in missing_by_lie.values() for item in values})
            return self._finalize_result(
                ok=False,
                action="confront",
                code="confront_missing_required_evidence",
                message=(
                    f"Confront: {npc.get('display_name', character_id)} ({character_id})\n"
                    f"{self._evidence_title(evidence_id)} ({evidence_id}) is relevant, but more evidence is needed."
                ),
                command=command,
                target_id=target_id,
                data={
                    "character_id": character_id,
                    "evidence_id": evidence_id,
                    "candidate_lie_ids": candidate_lie_ids,
                    "missing_evidence_ids": missing_evidence_ids,
                    "missing_by_lie": missing_by_lie,
                },
            )

        broken_now = []
        for lie in breakable_lies:
            if self._break_lie(lie):
                broken_now.append(lie)

        visible_truths = self._visible_truths_for_npc(npc)
        deterministic_response = self._build_confront_response(npc, evidence, broken_now)

        self._advance_after_basic_action("confront")
        changes = self._changes_since(before)
        code = "confront_lie_broken"
        npc_tick = self._run_npc_autonomy_tick(
            {
                "action": "confront",
                "character_id": character_id,
                "target_character_id": character_id,
                "evidence_id": evidence_id,
                "result_code": code,
                **changes,
            }
        )
        selected_action_policy = self._selected_action_policy_for_character(npc_tick["npc_action_policies"], character_id)
        presented_evidence = {
            "evidence_id": evidence_id,
            "title": evidence.get("title", evidence_id),
            "evidence_type": evidence.get("evidence_type", "unknown"),
            "content": evidence.get("content", ""),
        }
        actor_context = self._build_npc_actor_context(
            npc=npc,
            question=f"Detective presents evidence {evidence.get('title', evidence_id)} ({evidence_id}).",
            visible_truths=visible_truths,
            broken_now=broken_now,
            judge_result_code=code,
            deterministic_message=deterministic_response,
            interaction_type="confront",
            presented_evidence=presented_evidence,
            selected_action_policy=selected_action_policy,
        )
        response, actor_data = self._render_npc_actor_response(actor_context, deterministic_response)
        response = self._append_visible_npc_events(response, npc_tick["visible_events"])
        self._record_npc_conversation(character_id, f"[confront] {evidence_id}", response, code, actor_data.get("actor_mode", "template"))
        return self._finalize_result(
            ok=True,
            action="confront",
            code=code,
            message=response,
            command=command,
            target_id=target_id,
            data={
                "character_id": character_id,
                "evidence_id": evidence_id,
                "candidate_lie_ids": candidate_lie_ids,
                "broken_lie_ids": sorted(lie.get("lie_id", "") for lie in broken_now),
                "visible_truth_ids": sorted(truth.get("truth_id", "") for truth in visible_truths),
                "actor_mode": actor_data.get("actor_mode", "template"),
                "actor_error": actor_data.get("actor_error", ""),
                "selected_action_policy": selected_action_policy,
                **npc_tick,
            },
            **changes,
        )

    def confront(self, character_id: str, evidence_id: str) -> str:
        """Present discovered evidence to an NPC and return text for legacy callers."""
        return self.confront_result(character_id, evidence_id).message

    def accuse_result(
        self,
        suspect_id: str,
        *,
        motive_truth_id: str = "",
        method_truth_id: str = "",
        evidence_chain_ids: Optional[list[str]] = None,
        lie_ids: Optional[list[str]] = None,
        truth_ids: Optional[list[str]] = None,
        command: str = "",
    ) -> ActionResult:
        """Submit an accusation and score culprit, motive, method, and evidence chain."""
        if self.game_over:
            return self._game_already_over_result("accuse", command=command, target_id=suspect_id)

        suspect_id = suspect_id.strip()
        before = self._state_marker()
        suspect = self.npcs_by_id.get(suspect_id)
        if not suspect:
            return self._finalize_result(
                ok=False,
                action="accuse",
                code="accuse_suspect_not_found",
                message=f"Suspect not found: {suspect_id}",
                command=command,
                target_id=suspect_id,
            )

        culprit_id = self.schema.get("truth_model", {}).get("culprit_character_id")
        correct = suspect_id == culprit_id
        culprit_name = self._npc_name(culprit_id)
        suspect_name = self._npc_name(suspect_id)
        submission = self._build_accusation_submission(
            suspect_id=suspect_id,
            motive_truth_id=motive_truth_id,
            method_truth_id=method_truth_id,
            evidence_chain_ids=evidence_chain_ids or [],
            lie_ids=lie_ids or [],
            truth_ids=truth_ids or [],
        )
        score_result = self._score_accusation_submission(submission)
        score = score_result["score"]
        max_score = score_result["max_score"]
        thresholds = self.schema.get("accusation_rules", {}).get("score_thresholds", {}) or {}
        pass_threshold = int(thresholds.get("pass", 0) or 0)
        perfect_threshold = int(thresholds.get("perfect", max_score) or max_score)
        accusation = {
            "turn_index": self.turn_index + 1,
            "suspect_id": suspect_id,
            "suspect_name": suspect_name,
            "correct": correct,
            "score": score,
            "max_score": max_score,
            "passed": score >= pass_threshold if pass_threshold else correct,
            "perfect": score >= perfect_threshold if perfect_threshold else score == max_score,
            "submission": dict(submission),
            "score_breakdown": [dict(item) for item in score_result["breakdown"]],
            "missing_required_fields": list(score_result["missing_required_fields"]),
        }
        self.accusation_result = accusation
        self.accusation_history.append(dict(accusation))
        if not correct:
            self.wrong_accusations += 1
        self.game_over = True
        self.won = correct
        self.current_phase_id = self._phase_id_by_type("recap") or self.current_phase_id
        self._apply_phase_unlocks(self.current_phase_id)

        changes = self._changes_since(before)
        verdict = "correct" if correct else "wrong"
        recap = self.schema.get("recap", {})
        missed = self._build_missed_summary()
        message = (
            f"Final accusation: {verdict}\n"
            f"Your accusation: {suspect_name} ({suspect_id})\n"
            f"True culprit: {culprit_name} ({culprit_id})\n"
            f"Score: {score}/{max_score}\n"
            f"Passed: {self._yes_no(accusation['passed'])}\n"
            f"Score breakdown: {self._format_score_breakdown(score_result['breakdown'])}\n\n"
            f"Truth: {recap.get('truth_summary', '')}\n"
            f"Timeline: {recap.get('timeline_summary', '')}\n"
            f"Missed: {missed}"
        )
        return self._finalize_result(
            ok=True,
            action="accuse",
            code="accuse_correct" if correct else "accuse_wrong",
            message=message,
            command=command,
            target_id=suspect_id,
            score_delta=score,
            data={
                "suspect_id": suspect_id,
                "culprit_id": culprit_id,
                "correct": correct,
                "score": score,
                "max_score": max_score,
                "passed": accusation["passed"],
                "perfect": accusation["perfect"],
                "submission": dict(submission),
                "score_breakdown": [dict(item) for item in score_result["breakdown"]],
                "missing_required_fields": list(score_result["missing_required_fields"]),
                "invalid_submission": dict(score_result["invalid_submission"]),
                "missed_summary": missed,
            },
            **changes,
        )

    def accuse(
        self,
        suspect_id: str,
        *,
        motive_truth_id: str = "",
        method_truth_id: str = "",
        evidence_chain_ids: Optional[list[str]] = None,
        lie_ids: Optional[list[str]] = None,
        truth_ids: Optional[list[str]] = None,
    ) -> str:
        """Submit an accusation and return text for legacy callers."""
        return self.accuse_result(
            suspect_id,
            motive_truth_id=motive_truth_id,
            method_truth_id=method_truth_id,
            evidence_chain_ids=evidence_chain_ids,
            lie_ids=lie_ids,
            truth_ids=truth_ids,
        ).message

    def handle_command_result(self, raw_command: str) -> ActionResult:
        """Parse and execute one simple slash command with a structured result."""
        raw_command = raw_command.strip()
        if not raw_command:
            return self._finalize_result(
                ok=False,
                action="command",
                code="command_empty",
                message="Please enter a command.",
                command=raw_command,
            )
        if raw_command == "/status":
            return self.status_result(command=raw_command)
        if self.game_over:
            return self._game_already_over_result("command", command=raw_command)
        if raw_command.startswith("/search "):
            return self.search_result(raw_command.split(maxsplit=1)[1], command=raw_command)
        if raw_command.startswith("/show "):
            return self.show_result(raw_command.split(maxsplit=1)[1], command=raw_command)
        if raw_command.startswith("/ask "):
            parts = raw_command.split(maxsplit=2)
            if len(parts) < 3:
                return self._finalize_result(
                    ok=False,
                    action="ask",
                    code="ask_usage_error",
                    message="Usage: /ask <character_id> <question>",
                    command=raw_command,
                )
            return self.ask_result(parts[1], parts[2], command=raw_command)
        if raw_command.startswith("/confront "):
            parts = raw_command.split(maxsplit=2)
            if len(parts) < 3:
                return self._finalize_result(
                    ok=False,
                    action="confront",
                    code="confront_usage_error",
                    message="Usage: /confront <character_id> <evidence_id>",
                    command=raw_command,
                )
            return self.confront_result(parts[1], parts[2], command=raw_command)
        if raw_command.startswith("/accuse "):
            parts = raw_command.split()
            suspect_id = parts[1]
            fields, errors = self._parse_accusation_tokens(parts[2:])
            if errors:
                return self._finalize_result(
                    ok=False,
                    action="accuse",
                    code="accuse_usage_error",
                    message=(
                        "Usage: /accuse <suspect_id> "
                        "motive=<truth_id> method=<truth_id> evidence=<evidence_id,...> "
                        "lies=<lie_id,...> [truths=<truth_id,...>]\n"
                        f"Errors: {', '.join(errors)}"
                    ),
                    command=raw_command,
                    target_id=suspect_id,
                    data={"errors": errors},
                )
            return self.accuse_result(suspect_id, command=raw_command, **fields)
        return self._finalize_result(
            ok=False,
            action="command",
            code="command_unknown",
            message="Unknown command. Available: /status, /search <area_id>, /show <clue_id>, /ask <character_id> <question>, /confront <character_id> <evidence_id>, /accuse <suspect_id> [motive=<truth_id> method=<truth_id> evidence=<ids> lies=<ids>]",
            command=raw_command,
        )

    def handle_command(self, raw_command: str) -> str:
        """Parse and execute one simple slash command."""
        return self.handle_command_result(raw_command).message

    def get_progress_snapshot(self) -> dict[str, Any]:
        """Return structured runtime state for tests or future UI layers."""
        return {
            "current_phase_id": self.current_phase_id,
            "unlocked_scene_ids": sorted(self.unlocked_scene_ids),
            "searched_scene_ids": sorted(self.searched_scene_ids),
            "discovered_evidence_ids": sorted(self.discovered_evidence_ids),
            "shown_evidence_ids": sorted(self.shown_evidence_ids),
            "clue_state_by_id": {
                evidence_id: self.clue_state_by_id.get(evidence_id, "")
                for evidence_id in sorted(self.evidence_by_id)
            },
            "unlocked_truth_ids": sorted(self.unlocked_truth_ids),
            "broken_lie_ids": sorted(self.broken_lie_ids),
            "asked_character_ids": sorted(self.asked_character_ids),
            "wrong_accusations": self.wrong_accusations,
            "game_over": self.game_over,
            "won": self.won,
            "turn_index": self.turn_index,
            "accusation_result": dict(self.accusation_result) if self.accusation_result else None,
            "latest_accusation_result": dict(self.accusation_history[-1]) if self.accusation_history else None,
            "accusation_history": [dict(item) for item in self.accusation_history],
            "action_history": [dict(item) for item in self.action_history],
            "npc_runtime_state": {
                character_id: dict(state)
                for character_id, state in sorted(self.npc_runtime_state.items())
            },
            "npc_action_history": [dict(item) for item in self.npc_action_history],
            "visible_npc_events": [dict(item) for item in self.visible_npc_events],
            "conversation_history_by_character": {
                character_id: [dict(item) for item in history]
                for character_id, history in self.conversation_history_by_character.items()
            },
            "npc_actor_enabled": self.npc_actor is not None,
            "last_action_result": self.last_action_result.to_dict() if self.last_action_result else None,
        }

    def _current_phase(self) -> dict[str, Any]:
        return self.phases_by_id.get(self.current_phase_id, {})

    def _apply_phase_unlocks(self, phase_id: str) -> None:
        phase = self.phases_by_id.get(phase_id, {})
        for scene_id in phase.get("unlocked_scene_ids", []) or []:
            scene = self.scenes_by_id.get(scene_id, {})
            if "entry_condition" not in scene or self._scene_entry_condition_met(scene_id):
                self.unlocked_scene_ids.add(scene_id)
        for evidence_id in phase.get("unlocked_evidence_ids", []) or []:
            self._discover_evidence(evidence_id)
        self._refresh_discoverable_clues()
        self._refresh_unlocked_scenes()
        self._refresh_truth_unlocks()

    def _advance_after_basic_action(self, action: str) -> None:
        phase = self._current_phase()
        if phase.get("phase_type") == "intro" and action in {"search", "ask", "confront"}:
            investigation_phase = self._phase_id_by_type("investigation")
            if investigation_phase:
                self.current_phase_id = investigation_phase
                self._apply_phase_unlocks(investigation_phase)
        self._refresh_discoverable_clues()
        self._refresh_unlocked_scenes()
        self._refresh_truth_unlocks()

    def _enter_phase_if_later(self, phase_id: str) -> None:
        target = self.phases_by_id.get(phase_id)
        current = self._current_phase()
        if not target:
            return
        if not self._condition_met(target.get("entry_condition")):
            return
        if target.get("order", 0) >= current.get("order", 0):
            self.current_phase_id = phase_id
            self._apply_phase_unlocks(phase_id)

    def _phase_id_by_type(self, phase_type: str) -> str:
        for phase in self.phase_order:
            if phase.get("phase_type") == phase_type:
                return phase.get("phase_id", "")
        return ""

    def _build_initial_clue_state(self) -> dict[str, str]:
        states = {}
        for evidence_id, item in sorted(self.evidence_by_id.items()):
            lifecycle = item.get("lifecycle", {}) if isinstance(item.get("lifecycle"), dict) else {}
            state = lifecycle.get("initial_state")
            if not state:
                state = "discovered" if item.get("initially_discovered") else "discoverable"
            if item.get("initially_discovered"):
                state = "discovered"
            states[evidence_id] = state
        return states

    def _can_discover_evidence(self, evidence_id: str, scene_id: str) -> bool:
        if evidence_id in self.discovered_evidence_ids:
            return False
        item = self.evidence_by_id.get(evidence_id, {})
        if item.get("scene_id") != scene_id and item.get("source_scene_id") != scene_id:
            return False
        state = self.clue_state_by_id.get(evidence_id, "discoverable")
        if state == "locked":
            return False
        if state == "hidden":
            lifecycle = item.get("lifecycle", {}) if isinstance(item.get("lifecycle"), dict) else {}
            if not self._condition_met(lifecycle.get("discoverable_when")):
                return False
            self.clue_state_by_id[evidence_id] = "discoverable"
            state = "discoverable"
        return state == "discoverable"

    def _discover_evidence(self, evidence_id: str) -> None:
        if evidence_id not in self.evidence_by_id:
            return
        self.discovered_evidence_ids.add(evidence_id)
        if self.clue_state_by_id.get(evidence_id) != "revealed":
            self.clue_state_by_id[evidence_id] = "discovered"
        self._unlock_truths_for_evidence(evidence_id)

    def _refresh_discoverable_clues(self) -> None:
        for evidence_id, item in sorted(self.evidence_by_id.items()):
            if self.clue_state_by_id.get(evidence_id) != "hidden":
                continue
            lifecycle = item.get("lifecycle", {}) if isinstance(item.get("lifecycle"), dict) else {}
            if self._condition_met(lifecycle.get("discoverable_when")):
                self.clue_state_by_id[evidence_id] = "discoverable"

    def _refresh_unlocked_scenes(self) -> None:
        for scene_id in sorted(self.scenes_by_id):
            if scene_id in self.unlocked_scene_ids:
                continue
            if "entry_condition" not in self.scenes_by_id.get(scene_id, {}):
                continue
            if self._scene_entry_condition_met(scene_id):
                self.unlocked_scene_ids.add(scene_id)

    def _scene_entry_condition_met(self, scene_id: str) -> bool:
        scene = self.scenes_by_id.get(scene_id, {})
        if "entry_condition" not in scene:
            return scene_id in self.unlocked_scene_ids or bool(scene.get("initially_unlocked"))
        condition = scene.get("entry_condition")
        if condition in (None, {}):
            return True
        return self._condition_met(condition)

    def _refresh_truth_unlocks(self) -> None:
        if self.schema.get("schema_version") != "game_schema_v0.3":
            return
        for truth_id in sorted(self.truth_by_id):
            self._unlock_truth_by_id(truth_id)

    def _unlock_truth_by_id(self, truth_id: str) -> None:
        if truth_id in self.unlocked_truth_ids:
            return
        if self._truth_unlock_condition_met(truth_id):
            self.unlocked_truth_ids.add(truth_id)

    def _truth_unlock_condition_met(self, truth_id: str) -> bool:
        truth = self.truth_by_id.get(truth_id, {})
        if truth.get("revealed_by_default"):
            return True
        required = set(truth.get("required_clue_ids", []) or [])
        if required and not required.issubset(self.discovered_evidence_ids):
            return False
        condition = truth.get("unlock_condition")
        if condition not in (None, {}):
            return self._condition_met(condition)
        related = set(truth.get("related_evidence_ids", []) or [])
        if related:
            return bool(related.intersection(self.discovered_evidence_ids))
        return False

    def _condition_met(self, condition: Any) -> bool:
        if condition in (None, {}):
            return True
        if not isinstance(condition, dict):
            return False
        scalar_sources = {
            "phase_id_is": self.current_phase_id,
            "phase_type_is": self._current_phase().get("phase_type", ""),
        }
        for key, actual in scalar_sources.items():
            if key in condition and not self._condition_value_matches(actual, condition.get(key)):
                return False
        if "turn_index_min" in condition and self.turn_index < int(condition.get("turn_index_min", 0) or 0):
            return False
        if "action_count_min" in condition and len(self.action_history) < int(condition.get("action_count_min", 0) or 0):
            return False
        boolean_sources = {
            "game_over": self.game_over,
            "accusation_submitted": bool(self.accusation_history),
            "manual": True,
        }
        for key, actual in boolean_sources.items():
            if key in condition and bool(condition.get(key)) != actual:
                return False
        list_sources = (
            ("unlocked_scene_ids_all", self.unlocked_scene_ids, True),
            ("unlocked_scene_ids_any", self.unlocked_scene_ids, False),
            ("searched_scene_ids_all", self.searched_scene_ids, True),
            ("searched_scene_ids_any", self.searched_scene_ids, False),
            ("discovered_evidence_ids_all", self.discovered_evidence_ids, True),
            ("discovered_evidence_ids_any", self.discovered_evidence_ids, False),
            ("revealed_evidence_ids_all", self.shown_evidence_ids, True),
            ("revealed_evidence_ids_any", self.shown_evidence_ids, False),
            ("broken_lie_ids_all", self.broken_lie_ids, True),
            ("broken_lie_ids_any", self.broken_lie_ids, False),
            ("unlocked_truth_ids_all", self.unlocked_truth_ids, True),
            ("unlocked_truth_ids_any", self.unlocked_truth_ids, False),
        )
        for key, actual_values, require_all in list_sources:
            if key not in condition:
                continue
            expected = set(self._as_list(condition.get(key)))
            if require_all and not expected.issubset(actual_values):
                return False
            if not require_all and expected and not expected.intersection(actual_values):
                return False
        return True

    def _unlock_truths_for_evidence(self, evidence_id: str) -> None:
        item = self.evidence_by_id.get(evidence_id, {})
        for truth_id in item.get("related_truth_ids", []) or []:
            self._unlock_truth_by_id(truth_id)

    def _break_available_lies_for_npc(self, character_id: str) -> list[dict[str, Any]]:
        broken_now = []
        npc = self.npcs_by_id.get(character_id, {})
        for lie_id in npc.get("conversation_rules", {}).get("lie_ids", []) or []:
            if lie_id in self.broken_lie_ids:
                continue
            lie = self.lies_by_id.get(lie_id)
            if not lie:
                continue
            required = set(lie.get("required_evidence_ids", []) or [])
            if required and required.issubset(self.discovered_evidence_ids):
                if self._break_lie(lie):
                    broken_now.append(lie)
        return broken_now

    def _break_lie(self, lie: dict[str, Any]) -> bool:
        lie_id = lie.get("lie_id", "")
        if not lie_id or lie_id in self.broken_lie_ids:
            return False
        self.broken_lie_ids.add(lie_id)
        result = lie.get("break_result", {})
        for truth_id in result.get("unlocked_truth_ids", []) or []:
            self._unlock_truth_by_id(truth_id)
        for phase_id in result.get("phase_unlock_ids", []) or []:
            self._enter_phase_if_later(phase_id)
        self._refresh_discoverable_clues()
        self._refresh_unlocked_scenes()
        self._refresh_truth_unlocks()
        return True

    def _visible_truths_for_npc(self, npc: dict[str, Any]) -> list[dict[str, Any]]:
        forbidden = set(npc.get("conversation_rules", {}).get("forbidden_truth_ids", []) or [])
        visible = []
        for truth_id in npc.get("known_truth_ids", []) or []:
            if truth_id in forbidden:
                continue
            if truth_id in self.unlocked_truth_ids:
                truth = self.truth_by_id.get(truth_id)
                if truth:
                    visible.append(truth)
        return visible

    def _build_npc_response(
        self,
        npc: dict[str, Any],
        question: str,
        visible_truths: list[dict[str, Any]],
        broken_now: list[dict[str, Any]],
    ) -> str:
        name = npc.get("display_name", npc.get("character_id", "NPC"))
        lines = [f"Ask: {name}", f"Question: {question}", f"Attitude: {npc.get('initial_attitude', '')}"]
        if broken_now:
            for lie in broken_now:
                result = lie.get("break_result", {})
                lines.append(f"Lie broken: {lie.get('claim', '')}")
                lines.append(f"{name}: {result.get('response_guidance', '')}")
                if result.get("attitude_shift"):
                    lines.append(f"Attitude shift: {result.get('attitude_shift')}")
            return "\n".join(line for line in lines if line)

        rules = npc.get("conversation_rules", {})
        active_lies = [
            self.lies_by_id[lie_id]
            for lie_id in rules.get("lie_ids", []) or []
            if lie_id in self.lies_by_id and lie_id not in self.broken_lie_ids
        ]
        if active_lies and rules.get("can_lie"):
            lines.append(f"{name}: {active_lies[0].get('claim', '')}")
            lines.append(f"{name}: {rules.get('fallback_style', '')}")
            return "\n".join(line for line in lines if line)

        if visible_truths:
            lines.append(f"{name}: I can confirm:")
            lines.extend(f"- {truth.get('content', '')}" for truth in visible_truths)
            return "\n".join(line for line in lines if line)

        lines.append(f"{name}: I can only speak to public facts. {npc.get('public_profile', '')}")
        if rules.get("fallback_style"):
            lines.append(f"{name}: {rules.get('fallback_style')}")
        return "\n".join(line for line in lines if line)

    def _build_confront_response(
        self,
        npc: dict[str, Any],
        evidence: dict[str, Any],
        broken_now: list[dict[str, Any]],
    ) -> str:
        name = npc.get("display_name", npc.get("character_id", "NPC"))
        evidence_id = evidence.get("evidence_id", "")
        lines = [
            f"Confront: {name}",
            f"Evidence: {evidence.get('title', evidence_id)} ({evidence_id})",
            f"Content: {evidence.get('content', '')}",
        ]
        for lie in broken_now:
            result = lie.get("break_result", {})
            lines.append(f"Lie broken: {lie.get('claim', '')}")
            lines.append(f"{name}: {result.get('response_guidance', '')}")
            if result.get("attitude_shift"):
                lines.append(f"Attitude shift: {result.get('attitude_shift')}")
        return "\n".join(line for line in lines if line)

    def _build_npc_actor_context(
        self,
        *,
        npc: dict[str, Any],
        question: str,
        visible_truths: list[dict[str, Any]],
        broken_now: list[dict[str, Any]],
        judge_result_code: str,
        deterministic_message: str,
        interaction_type: str = "ask",
        presented_evidence: Optional[dict[str, Any]] = None,
        selected_action_policy: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build a spoiler-limited, single-NPC perspective context for an optional actor."""
        character_id = npc.get("character_id", "")
        rules = npc.get("conversation_rules", {})
        active_lies = [
            {
                "lie_id": lie_id,
                "claim": self.lies_by_id[lie_id].get("claim", ""),
            }
            for lie_id in rules.get("lie_ids", []) or []
            if lie_id in self.lies_by_id and lie_id not in self.broken_lie_ids
        ]
        broken_lies = [
            {
                "lie_id": lie.get("lie_id", ""),
                "claim": lie.get("claim", ""),
                "response_guidance": lie.get("break_result", {}).get("response_guidance", ""),
                "attitude_shift": lie.get("break_result", {}).get("attitude_shift", ""),
                "required_evidence_ids": sorted(lie.get("required_evidence_ids", []) or []),
            }
            for lie in broken_now
        ]
        discovered_evidence = [
            {
                "evidence_id": evidence_id,
                "title": item.get("title", evidence_id),
                "evidence_type": item.get("evidence_type", "unknown"),
                "content": item.get("content", ""),
            }
            for evidence_id, item in sorted(self.evidence_by_id.items())
            if evidence_id in self.discovered_evidence_ids
        ]
        other_characters_public = [
            {
                "character_id": other_id,
                "display_name": other.get("display_name", other_id),
                "public_profile": other.get("public_profile", ""),
            }
            for other_id, other in sorted(self.npcs_by_id.items())
            if other_id != character_id
        ]
        phase = self._current_phase()
        context = {
            "viewer_character_id": character_id,
            "interaction_type": interaction_type,
            "case_public": {
                "title": self.schema.get("game_info", {}).get("title", ""),
                "setting": self.schema.get("public_case", {}).get("setting", ""),
            },
            "self_view": {
                "character_id": character_id,
                "display_name": npc.get("display_name", character_id),
                "public_profile": npc.get("public_profile", ""),
                "initial_attitude": npc.get("initial_attitude", ""),
                "fallback_style": rules.get("fallback_style", ""),
            },
            "other_characters_public": other_characters_public,
            "npc_runtime": dict(self.npc_runtime_state.get(character_id, {})),
            "selected_action_policy": dict(selected_action_policy or {}),
            "player_known": {
                "phase": {
                    "phase_id": self.current_phase_id,
                    "title": phase.get("title", self.current_phase_id),
                    "phase_type": phase.get("phase_type", ""),
                },
                "discovered_evidence": discovered_evidence,
                "broken_lie_ids": sorted(self.broken_lie_ids),
            },
            "question": question,
            "judge_result": {
                "code": judge_result_code,
                "new_broken_lie_ids": sorted(lie.get("lie_id", "") for lie in broken_now),
                "deterministic_message": deterministic_message,
            },
            "allowed_truths": [
                {
                    "truth_id": truth.get("truth_id", ""),
                    "truth_type": truth.get("truth_type", ""),
                    "content": truth.get("content", ""),
                }
                for truth in visible_truths
            ],
            "active_lies": active_lies,
            "broken_lies_this_turn": broken_lies,
            "conversation_history": [
                dict(item)
                for item in self.conversation_history_by_character.get(character_id, [])[-6:]
            ],
            "guardrails": [
                "Speak only as the viewer_character_id NPC using this context.",
                "Treat case_public, self_view, other_characters_public, npc_runtime, selected_action_policy, player_known, allowed_truths, active_lies, broken_lies_this_turn, and presented_evidence as the complete knowledge boundary.",
                "Do not reveal hidden truths, culprit identity, forbidden facts, private profiles, undiscovered evidence, schema internals, or future phase information.",
                "For ask interactions, answer normally in character and do not treat the question as proof.",
                "For confront interactions, follow judge_result and broken_lies_this_turn; do not decide whether a lie is broken.",
            ],
        }
        if presented_evidence:
            context["presented_evidence"] = dict(presented_evidence)
        return context

    def _render_npc_actor_response(self, context: dict[str, Any], deterministic_message: str) -> tuple[str, dict[str, str]]:
        """Let the optional actor rewrite a judged response, with safe fallback."""
        if self.npc_actor is None:
            return deterministic_message, {"actor_mode": "template", "actor_error": ""}
        audit_error = self._audit_npc_actor_context(context)
        if audit_error:
            return deterministic_message, {"actor_mode": "fallback", "actor_error": f"context_audit_failed:{audit_error}"}
        try:
            rendered = self.npc_actor.render_response(context, deterministic_message)
        except Exception as exc:
            return deterministic_message, {"actor_mode": "fallback", "actor_error": str(exc)}
        rendered = (rendered or "").strip()
        if not rendered:
            return deterministic_message, {"actor_mode": "fallback", "actor_error": "empty_actor_response"}
        return rendered, {"actor_mode": "llm", "actor_error": ""}

    def _audit_npc_actor_context(self, context: dict[str, Any]) -> str:
        """Return a reason string if the actor context leaks hidden or schema-only facts."""
        forbidden_keys = {
            "private_profile",
            "culprit_character_id",
            "truth_model",
            "accusation_rules",
            "recap",
            "schema",
            "forbidden_truth_ids",
            "action_profile",
            "goals",
            "directive",
            "conditions",
        }
        leaked_key = self._find_forbidden_context_key(context, forbidden_keys)
        if leaked_key:
            return f"forbidden_key:{leaked_key}"

        blob = self._context_blob(context)
        viewer_id = str(context.get("viewer_character_id", ""))
        allowed_truth_ids = {
            str(item.get("truth_id", ""))
            for item in context.get("allowed_truths", [])
            if isinstance(item, dict)
        }
        allowed_truth_ids.update(
            str(item.get("truth_id", ""))
            for item in self.truth_by_id.values()
            if item.get("revealed_by_default")
        )
        for truth_id in sorted(self.truth_by_id):
            if truth_id not in allowed_truth_ids and truth_id in blob:
                return f"locked_truth:{truth_id}"

        npc = self.npcs_by_id.get(viewer_id, {})
        forbidden_truth_ids = set(npc.get("conversation_rules", {}).get("forbidden_truth_ids", []) or [])
        for truth_id in sorted(forbidden_truth_ids):
            if truth_id in blob:
                return f"forbidden_truth:{truth_id}"

        allowed_evidence_ids = set(self.discovered_evidence_ids)
        presented = context.get("presented_evidence")
        if isinstance(presented, dict):
            evidence_id = str(presented.get("evidence_id", ""))
            if evidence_id:
                allowed_evidence_ids.add(evidence_id)
        for evidence_id in sorted(self.evidence_by_id):
            if evidence_id not in allowed_evidence_ids and evidence_id in blob:
                return f"hidden_evidence:{evidence_id}"
        return ""

    def _find_forbidden_context_key(self, value: Any, forbidden_keys: set[str]) -> str:
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key) in forbidden_keys:
                    return str(key)
                found = self._find_forbidden_context_key(nested, forbidden_keys)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_forbidden_context_key(item, forbidden_keys)
                if found:
                    return found
        return ""

    @staticmethod
    def _context_blob(context: dict[str, Any]) -> str:
        return str(context)

    def _record_npc_conversation(
        self,
        character_id: str,
        question: str,
        response: str,
        result_code: str,
        actor_mode: str,
    ) -> None:
        self.conversation_history_by_character.setdefault(character_id, []).append(
            {
                "turn_index": self.turn_index + 1,
                "question": question,
                "response": response,
                "result_code": result_code,
                "actor_mode": actor_mode,
            }
        )

    def _build_initial_npc_runtime_state(self) -> dict[str, dict[str, Any]]:
        runtime = {}
        for character_id, npc in sorted(self.npcs_by_id.items()):
            profile = npc.get("action_profile", {}) or {}
            runtime[character_id] = {
                "location_scene_id": profile.get("initial_location_scene_id") or self._initial_scene_for_npc(character_id),
                "stance": profile.get("initial_stance", "default"),
                "stress": int(profile.get("initial_stress", 0) or 0),
                "suspicion_target_id": profile.get("initial_suspicion_target_id", ""),
                "last_action_id": "",
            }
        return runtime

    def _initial_scene_for_npc(self, character_id: str) -> str:
        for scene_id, scene in sorted(self.scenes_by_id.items()):
            if character_id in (scene.get("npc_ids", []) or []):
                return scene_id
        return ""

    def _run_npc_autonomy_tick(self, action_context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        action_records = []
        visible_events = []
        if self.game_over:
            return {"npc_action_policies": action_records, "npc_events": visible_events, "visible_events": visible_events}

        for character_id, npc in sorted(self.npcs_by_id.items()):
            profile = npc.get("action_profile", {}) or {}
            rule = self._select_npc_action_rule(character_id, profile, action_context)
            if not rule:
                continue
            record, event = self._apply_npc_action_rule(character_id, rule, action_context)
            action_records.append(record)
            self.npc_action_history.append(dict(record))
            if event:
                visible_events.append(event)
                self.visible_npc_events.append(dict(event))
            if rule.get("once", True):
                self._npc_executed_rule_ids.setdefault(character_id, set()).add(rule.get("rule_id", ""))
            rule_id = rule.get("rule_id", "")
            self._npc_rule_fire_counts.setdefault(character_id, {})[rule_id] = self._npc_rule_fire_counts.setdefault(character_id, {}).get(rule_id, 0) + 1
            self._npc_rule_last_fired_turn.setdefault(character_id, {})[rule_id] = self.turn_index + 1

        return {"npc_action_policies": action_records, "npc_events": visible_events, "visible_events": visible_events}

    def _select_npc_action_rule(
        self,
        character_id: str,
        profile: dict[str, Any],
        action_context: dict[str, Any],
    ) -> dict[str, Any]:
        rules = [
            rule
            for rule in profile.get("rules", []) or []
            if isinstance(rule, dict) and self._npc_rule_matches(character_id, rule, action_context)
        ]
        if not rules:
            return {}
        return sorted(rules, key=lambda item: (-int(item.get("priority", 0) or 0), item.get("rule_id", "")))[0]

    def _npc_rule_matches(self, character_id: str, rule: dict[str, Any], action_context: dict[str, Any]) -> bool:
        rule_id = rule.get("rule_id", "")
        fire_count = self._npc_rule_fire_counts.get(character_id, {}).get(rule_id, 0)
        if rule.get("max_times") is not None:
            if fire_count >= int(rule.get("max_times", 0) or 0):
                return False
        elif rule.get("once", True) and rule_id in self._npc_executed_rule_ids.get(character_id, set()):
            return False
        cooldown_turns = int(rule.get("cooldown_turns", 0) or 0)
        last_fired = self._npc_rule_last_fired_turn.get(character_id, {}).get(rule_id)
        if cooldown_turns and last_fired is not None and (self.turn_index + 1 - last_fired) <= cooldown_turns:
            return False
        if not self._trigger_matches(rule.get("trigger", ""), action_context.get("action", "")):
            return False

        conditions = rule.get("conditions", {}) or {}
        state = self.npc_runtime_state.get(character_id, {})
        checks = (
            ("phase_id_is", self.current_phase_id),
            ("phase_type_is", self._current_phase().get("phase_type", "")),
            ("area_id_is", action_context.get("area_id", "")),
            ("target_character_id_is", action_context.get("target_character_id", "")),
            ("character_id_is", action_context.get("character_id", "")),
            ("evidence_id_is", action_context.get("evidence_id", "")),
            ("result_code_is", action_context.get("result_code", "")),
            ("npc_stance_is", state.get("stance", "")),
            ("npc_location_scene_id_is", state.get("location_scene_id", "")),
        )
        for key, actual in checks:
            if key in conditions and not self._condition_value_matches(actual, conditions.get(key)):
                return False

        min_stress = conditions.get("min_stress")
        if min_stress is not None and int(state.get("stress", 0) or 0) < int(min_stress):
            return False
        max_stress = conditions.get("max_stress")
        if max_stress is not None and int(state.get("stress", 0) or 0) > int(max_stress):
            return False

        list_checks = (
            ("discovered_evidence_ids_all", self.discovered_evidence_ids, True),
            ("discovered_evidence_ids_any", self.discovered_evidence_ids, False),
            ("broken_lie_ids_all", self.broken_lie_ids, True),
            ("broken_lie_ids_any", self.broken_lie_ids, False),
            ("new_evidence_ids_all", set(action_context.get("new_evidence_ids", []) or []), True),
            ("new_evidence_ids_any", set(action_context.get("new_evidence_ids", []) or []), False),
            ("new_broken_lie_ids_all", set(action_context.get("new_broken_lie_ids", []) or []), True),
            ("new_broken_lie_ids_any", set(action_context.get("new_broken_lie_ids", []) or []), False),
        )
        for key, actual_values, require_all in list_checks:
            if key not in conditions:
                continue
            expected = set(self._as_list(conditions.get(key)))
            if require_all and not expected.issubset(actual_values):
                return False
            if not require_all and expected and not expected.intersection(actual_values):
                return False
        return True

    def _trigger_matches(self, trigger: str, action: str) -> bool:
        trigger = trigger or "after_any_player_action"
        aliases = {
            "after_any_player_action": {"search", "ask", "confront"},
            "after_search": {"search"},
            "after_ask": {"ask"},
            "after_confront": {"confront"},
        }
        if trigger in aliases:
            return action in aliases[trigger]
        return trigger == action

    def _apply_npc_action_rule(
        self,
        character_id: str,
        rule: dict[str, Any],
        action_context: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self.npc_runtime_state.setdefault(
            character_id,
            {
                "location_scene_id": self._initial_scene_for_npc(character_id),
                "stance": "default",
                "stress": 0,
                "suspicion_target_id": "",
                "last_action_id": "",
            },
        )
        before_scene_id = state.get("location_scene_id", "")
        action = rule.get("action", {}) or {}
        action_type = action.get("type", "stay")

        if action_type in {"move_to_scene", "withdraw"}:
            target_scene_id = action.get("target_scene_id", "")
            if target_scene_id in self.scenes_by_id:
                state["location_scene_id"] = target_scene_id
            if action_type == "withdraw":
                state["stance"] = action.get("stance", "withdrawn")
        if action_type == "change_stance" and action.get("stance"):
            state["stance"] = action.get("stance", "")
        if action_type == "raise_stress":
            state["stress"] = max(0, int(state.get("stress", 0) or 0) + int(action.get("amount", 1) or 0))
        if action_type == "redirect_suspicion":
            state["suspicion_target_id"] = action.get("target_character_id", "")
        if action_type == "ask_player_question" and action.get("stance"):
            state["stance"] = action.get("stance", "")

        if action.get("stance") and action_type not in {"withdraw", "change_stance", "ask_player_question"}:
            state["stance"] = action.get("stance", "")
        if action.get("stress_delta") is not None:
            state["stress"] = max(0, int(state.get("stress", 0) or 0) + int(action.get("stress_delta", 0) or 0))
        if action.get("suspicion_target_id"):
            state["suspicion_target_id"] = action.get("suspicion_target_id", "")

        rule_id = rule.get("rule_id", "")
        state["last_action_id"] = rule_id
        record = {
            "turn_index": self.turn_index + 1,
            "npc_id": character_id,
            "rule_id": rule_id,
            "trigger": rule.get("trigger", ""),
            "action_type": action_type,
            "from_scene_id": before_scene_id,
            "to_scene_id": state.get("location_scene_id", ""),
            "stance": state.get("stance", ""),
            "stress": int(state.get("stress", 0) or 0),
            "suspicion_target_id": state.get("suspicion_target_id", ""),
            "visible_event": self._visible_event_text(rule.get("visible_event")),
            "matched_conditions": self._matched_npc_rule_conditions(character_id, rule, action_context),
            "failed_conditions": self._failed_npc_rule_conditions(character_id, rule, action_context),
            "source_action": action_context.get("action", ""),
            "reason": f"selected priority {int(rule.get('priority', 0) or 0)} after {rule.get('trigger', 'after_any_player_action')}",
        }
        event = self._build_visible_npc_event(character_id, rule, record, action_context)
        return record, event

    def _matched_npc_rule_conditions(
        self,
        character_id: str,
        rule: dict[str, Any],
        action_context: dict[str, Any],
    ) -> list[str]:
        conditions = rule.get("conditions", {}) or {}
        state = self.npc_runtime_state.get(character_id, {})
        matched = []
        scalar_sources = {
            "phase_id_is": self.current_phase_id,
            "phase_type_is": self._current_phase().get("phase_type", ""),
            "area_id_is": action_context.get("area_id", ""),
            "target_character_id_is": action_context.get("target_character_id", ""),
            "character_id_is": action_context.get("character_id", ""),
            "evidence_id_is": action_context.get("evidence_id", ""),
            "result_code_is": action_context.get("result_code", ""),
            "npc_stance_is": state.get("stance", ""),
            "npc_location_scene_id_is": state.get("location_scene_id", ""),
        }
        for key, actual in scalar_sources.items():
            if key in conditions and self._condition_value_matches(actual, conditions.get(key)):
                matched.append(key)
        if "min_stress" in conditions and int(state.get("stress", 0) or 0) >= int(conditions.get("min_stress", 0) or 0):
            matched.append("min_stress")
        if "max_stress" in conditions and int(state.get("stress", 0) or 0) <= int(conditions.get("max_stress", 0) or 0):
            matched.append("max_stress")

        list_sources = {
            "discovered_evidence_ids_all": (self.discovered_evidence_ids, True),
            "discovered_evidence_ids_any": (self.discovered_evidence_ids, False),
            "broken_lie_ids_all": (self.broken_lie_ids, True),
            "broken_lie_ids_any": (self.broken_lie_ids, False),
            "new_evidence_ids_all": (set(action_context.get("new_evidence_ids", []) or []), True),
            "new_evidence_ids_any": (set(action_context.get("new_evidence_ids", []) or []), False),
            "new_broken_lie_ids_all": (set(action_context.get("new_broken_lie_ids", []) or []), True),
            "new_broken_lie_ids_any": (set(action_context.get("new_broken_lie_ids", []) or []), False),
        }
        for key, (actual_values, require_all) in list_sources.items():
            if key not in conditions:
                continue
            expected = set(self._as_list(conditions.get(key)))
            if require_all and expected.issubset(actual_values):
                matched.append(key)
            elif not require_all and expected and expected.intersection(actual_values):
                matched.append(key)
        return sorted(matched)

    def _failed_npc_rule_conditions(
        self,
        character_id: str,
        rule: dict[str, Any],
        action_context: dict[str, Any],
    ) -> list[str]:
        conditions = rule.get("conditions", {}) or {}
        if not isinstance(conditions, dict):
            return ["conditions_not_object"]
        matched = set(self._matched_npc_rule_conditions(character_id, rule, action_context))
        return sorted(key for key in conditions if key not in matched)

    def _build_visible_npc_event(
        self,
        character_id: str,
        rule: dict[str, Any],
        record: dict[str, Any],
        action_context: dict[str, Any],
    ) -> dict[str, Any]:
        event = rule.get("visible_event")
        text = self._visible_event_text(event)
        if not text:
            return {}
        event_payload = {
            "turn_index": self.turn_index + 1,
            "npc_id": character_id,
            "rule_id": record.get("rule_id", ""),
            "action_type": record.get("action_type", ""),
            "text": text,
            "source_action": action_context.get("action", ""),
        }
        if isinstance(event, dict):
            for key in ("scene_id", "visibility"):
                if event.get(key):
                    event_payload[key] = event.get(key)
        return event_payload

    def _selected_action_policy_for_character(
        self,
        action_policies: list[dict[str, Any]],
        character_id: str,
    ) -> dict[str, Any]:
        for item in action_policies:
            if item.get("npc_id") == character_id:
                return dict(item)
        return {}

    def _append_visible_npc_events(self, message: str, visible_events: list[dict[str, Any]]) -> str:
        if not visible_events:
            return message
        lines = [message, "", "NPC events:"]
        lines.extend(f"- {event.get('text', '')}" for event in visible_events if event.get("text"))
        return "\n".join(line for line in lines if line)

    def _visible_event_text(self, event: Any) -> str:
        if isinstance(event, str):
            return event
        if isinstance(event, dict):
            return str(event.get("text", ""))
        return ""

    def _reachable_npc_ids(self) -> list[str]:
        return [
            character_id
            for character_id in sorted(self.npcs_by_id)
            if self._is_npc_reachable(character_id)
        ]

    def _condition_value_matches(self, actual: Any, expected: Any) -> bool:
        expected_values = self._as_list(expected)
        return str(actual) in {str(item) for item in expected_values}

    @staticmethod
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _parse_accusation_tokens(self, tokens: list[str]) -> tuple[dict[str, Any], list[str]]:
        fields: dict[str, Any] = {
            "motive_truth_id": "",
            "method_truth_id": "",
            "evidence_chain_ids": [],
            "lie_ids": [],
            "truth_ids": [],
        }
        errors = []
        key_map = {
            "motive": "motive_truth_id",
            "method": "method_truth_id",
            "evidence": "evidence_chain_ids",
            "evidence_chain": "evidence_chain_ids",
            "lies": "lie_ids",
            "lie": "lie_ids",
            "truths": "truth_ids",
            "truth": "truth_ids",
        }
        list_fields = {"evidence_chain_ids", "lie_ids", "truth_ids"}
        for token in tokens:
            if "=" not in token:
                errors.append(f"expected key=value token: {token}")
                continue
            raw_key, raw_value = token.split("=", 1)
            key = key_map.get(raw_key.strip())
            if not key:
                errors.append(f"unknown accusation field: {raw_key}")
                continue
            value = raw_value.strip()
            if key in list_fields:
                fields[key].extend(self._split_id_list(value))
            else:
                fields[key] = value
        for key in list_fields:
            fields[key] = sorted(set(fields[key]))
        return fields, errors

    def _build_accusation_submission(
        self,
        *,
        suspect_id: str,
        motive_truth_id: str,
        method_truth_id: str,
        evidence_chain_ids: list[str],
        lie_ids: list[str],
        truth_ids: list[str],
    ) -> dict[str, Any]:
        submitted_truth_ids = set(truth_ids)
        if motive_truth_id:
            submitted_truth_ids.add(motive_truth_id)
        if method_truth_id:
            submitted_truth_ids.add(method_truth_id)
        return {
            "culprit": suspect_id,
            "motive_truth_id": motive_truth_id,
            "method_truth_id": method_truth_id,
            "evidence_chain_ids": sorted(set(evidence_chain_ids)),
            "lie_ids": sorted(set(lie_ids)),
            "truth_ids": sorted(submitted_truth_ids),
        }

    def _score_accusation_submission(self, submission: dict[str, Any]) -> dict[str, Any]:
        scoring_items = self.schema.get("accusation_rules", {}).get("scoring_items", []) or []
        required_fields = self.schema.get("accusation_rules", {}).get("required_fields", []) or []
        submitted_evidence_ids = set(submission.get("evidence_chain_ids", []) or [])
        submitted_lie_ids = set(submission.get("lie_ids", []) or [])
        submitted_truth_ids = set(submission.get("truth_ids", []) or [])

        usable_evidence_ids = submitted_evidence_ids & set(self.evidence_by_id) & self.discovered_evidence_ids
        usable_lie_ids = submitted_lie_ids & set(self.lies_by_id) & self.broken_lie_ids
        usable_truth_ids = submitted_truth_ids & set(self.truth_by_id) & self.unlocked_truth_ids

        invalid_submission = {
            "unknown_evidence_ids": sorted(submitted_evidence_ids - set(self.evidence_by_id)),
            "hidden_evidence_ids": sorted((submitted_evidence_ids & set(self.evidence_by_id)) - self.discovered_evidence_ids),
            "unknown_lie_ids": sorted(submitted_lie_ids - set(self.lies_by_id)),
            "unbroken_lie_ids": sorted((submitted_lie_ids & set(self.lies_by_id)) - self.broken_lie_ids),
            "unknown_truth_ids": sorted(submitted_truth_ids - set(self.truth_by_id)),
            "locked_truth_ids": sorted((submitted_truth_ids & set(self.truth_by_id)) - self.unlocked_truth_ids),
        }

        score = 0
        max_score = 0
        breakdown = []
        for item in scoring_items:
            points = int(item.get("points", 0) or 0)
            max_score += points
            field_id = item.get("field_id", "")
            expected_character_id = item.get("expected_character_id")
            expected_truth_ids = set(item.get("expected_truth_ids", []) or [])
            expected_evidence_ids = set(item.get("expected_evidence_ids", []) or [])
            expected_lie_ids = set(item.get("expected_lie_ids", []) or [])

            if field_id == "culprit":
                truth_pool = set()
                evidence_pool = set()
                lie_pool = set()
            elif field_id == "evidence_chain":
                truth_pool = set(self.unlocked_truth_ids)
                evidence_pool = usable_evidence_ids
                lie_pool = usable_lie_ids
            else:
                truth_pool = usable_truth_ids
                evidence_pool = usable_evidence_ids
                lie_pool = usable_lie_ids

            missing_character_id = ""
            if expected_character_id and submission.get("culprit") != expected_character_id:
                missing_character_id = expected_character_id

            missing_truth_ids = sorted(expected_truth_ids - truth_pool)
            missing_evidence_ids = sorted(expected_evidence_ids - evidence_pool)
            missing_lie_ids = sorted(expected_lie_ids - lie_pool)
            if field_id == "culprit":
                missing_truth_ids = []
                missing_evidence_ids = []
                missing_lie_ids = []

            awarded = not missing_character_id and not missing_truth_ids and not missing_evidence_ids and not missing_lie_ids
            earned = points if awarded else 0
            score += earned
            breakdown.append(
                {
                    "score_id": item.get("score_id", ""),
                    "field_id": field_id,
                    "points": points,
                    "earned": earned,
                    "awarded": awarded,
                    "missing_character_id": missing_character_id,
                    "missing_truth_ids": missing_truth_ids,
                    "missing_evidence_ids": missing_evidence_ids,
                    "missing_lie_ids": missing_lie_ids,
                    "prompt": item.get("prompt", ""),
                }
            )

        missing_required_fields = []
        if "culprit" in required_fields and not submission.get("culprit"):
            missing_required_fields.append("culprit")
        if "motive" in required_fields and not submission.get("motive_truth_id"):
            missing_required_fields.append("motive")
        if "method" in required_fields and not submission.get("method_truth_id"):
            missing_required_fields.append("method")
        if "evidence_chain" in required_fields and not submission.get("evidence_chain_ids"):
            missing_required_fields.append("evidence_chain")

        return {
            "score": score,
            "max_score": max_score,
            "breakdown": breakdown,
            "missing_required_fields": missing_required_fields,
            "invalid_submission": invalid_submission,
        }

    def _format_score_breakdown(self, breakdown: list[dict[str, Any]]) -> str:
        if not breakdown:
            return "none"
        return ", ".join(
            f"{item.get('field_id', 'unknown')} {item.get('earned', 0)}/{item.get('points', 0)}"
            for item in breakdown
        )

    @staticmethod
    def _split_id_list(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def _is_npc_reachable(self, character_id: str) -> bool:
        runtime = self.npc_runtime_state.get(character_id, {})
        runtime_scene_id = runtime.get("location_scene_id", "")
        if runtime_scene_id:
            return runtime_scene_id in self.unlocked_scene_ids
        for scene_id in self.unlocked_scene_ids:
            scene = self.scenes_by_id.get(scene_id, {})
            if character_id in (scene.get("npc_ids", []) or []):
                return True
        return False

    def _score_culprit_only(self, suspect_id: str) -> int:
        score = 0
        for item in self.schema.get("accusation_rules", {}).get("scoring_items", []) or []:
            if item.get("field_id") == "culprit" and item.get("expected_character_id") == suspect_id:
                score += int(item.get("points", 0) or 0)
        return score

    def _culprit_score_max(self) -> int:
        total = 0
        for item in self.schema.get("accusation_rules", {}).get("scoring_items", []) or []:
            if item.get("field_id") == "culprit":
                total += int(item.get("points", 0) or 0)
        return total

    def _build_missed_summary(self) -> str:
        missed_evidence = [item for item in self.evidence_by_id if item not in self.discovered_evidence_ids]
        missed_lies = [item for item in self.lies_by_id if item not in self.broken_lie_ids]
        parts = []
        if missed_evidence:
            parts.append("undiscovered evidence: " + ", ".join(self._evidence_title(item) for item in missed_evidence))
        if missed_lies:
            parts.append("unbroken lies: " + ", ".join(self.lies_by_id[item].get("claim", item) for item in missed_lies))
        return "; ".join(parts) if parts else "no key content missed"

    def _state_marker(self) -> dict[str, set[str]]:
        return {
            "evidence": set(self.discovered_evidence_ids),
            "truth": set(self.unlocked_truth_ids),
            "lies": set(self.broken_lie_ids),
            "scenes": set(self.unlocked_scene_ids),
        }

    def _changes_since(self, before: dict[str, set[str]]) -> dict[str, list[str]]:
        return {
            "new_evidence_ids": sorted(self.discovered_evidence_ids - before["evidence"]),
            "new_truth_ids": sorted(self.unlocked_truth_ids - before["truth"]),
            "new_broken_lie_ids": sorted(self.broken_lie_ids - before["lies"]),
            "new_unlocked_scene_ids": sorted(self.unlocked_scene_ids - before["scenes"]),
        }

    def _finalize_result(
        self,
        *,
        ok: bool,
        action: str,
        code: str,
        message: str,
        command: str = "",
        target_id: str = "",
        new_evidence_ids: Optional[list[str]] = None,
        new_truth_ids: Optional[list[str]] = None,
        new_broken_lie_ids: Optional[list[str]] = None,
        new_unlocked_scene_ids: Optional[list[str]] = None,
        score_delta: int = 0,
        data: Optional[dict[str, Any]] = None,
    ) -> ActionResult:
        self.turn_index += 1
        result = ActionResult(
            ok=ok,
            action=action,
            code=code,
            message=message,
            phase_id=self.current_phase_id,
            turn_index=self.turn_index,
            command=command,
            target_id=target_id,
            new_evidence_ids=new_evidence_ids or [],
            new_truth_ids=new_truth_ids or [],
            new_broken_lie_ids=new_broken_lie_ids or [],
            new_unlocked_scene_ids=new_unlocked_scene_ids or [],
            score_delta=score_delta,
            data=data or {},
        )
        self.last_action_result = result
        self.action_history.append(result.to_dict())
        return result

    def _game_already_over_result(self, action: str, *, command: str = "", target_id: str = "") -> ActionResult:
        return self._finalize_result(
            ok=False,
            action=action,
            code="game_already_over",
            message="Game is already over. Use /status to inspect the final state.",
            command=command,
            target_id=target_id,
        )

    def _npc_name(self, character_id: Optional[str]) -> str:
        if not character_id:
            return "unknown"
        return self.npcs_by_id.get(character_id, {}).get("display_name", character_id)

    def _evidence_title(self, evidence_id: str) -> str:
        return self.evidence_by_id.get(evidence_id, {}).get("title", evidence_id)

    def _format_evidence_list(self, evidence_ids: list[str]) -> str:
        return ", ".join(f"{self._evidence_title(evidence_id)}({evidence_id})" for evidence_id in evidence_ids)

    def _format_scene_list(self, scene_ids: list[str]) -> str:
        return ", ".join(f"{self.scenes_by_id.get(scene_id, {}).get('title', scene_id)}({scene_id})" for scene_id in scene_ids)

    def _format_lie_list(self, lie_ids: list[str]) -> str:
        return ", ".join(self.lies_by_id.get(lie_id, {}).get("claim", lie_id) for lie_id in lie_ids)

    def _format_npc_list(self, character_ids: list[str]) -> str:
        return ", ".join(f"{self._npc_name(character_id)}({character_id})" for character_id in character_ids)

    def _format_visible_npc_events(self, visible_events: list[dict[str, Any]]) -> str:
        return " | ".join(event.get("text", "") for event in visible_events if event.get("text"))

    @staticmethod
    def _yes_no(value: bool) -> str:
        return "yes" if value else "no"


__all__ = ["ActionResult", "DetectiveGameEngine"]
