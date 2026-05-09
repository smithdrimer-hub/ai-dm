"""Text/Markdown to ScriptSchema v0.2.1 draft importer.

This is a semi-automatic draft tool, not a gameplay launcher. It reads a local
.txt/.md script, extracts coarse candidates, writes a schema draft and reports,
then validates the draft with the local lightweight validator.

Writing output requires --confirm-manual-review so imported drafts cannot be
mistaken for production-ready scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_schema_v0_3 import build_npc_author_questions, validate_game_schema_v0_3  # noqa: E402
from script_schema import validate_script_schema  # noqa: E402


SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown"}
IMPORTER_NAME = "import_text_script_v0_1"
KEY_VALUE_RE = re.compile("^\\s*([A-Za-z][A-Za-z0-9 _-]{1,40})\\s*(?::|\uff1a)\\s*(.+?)\\s*$")


@dataclass
class Chunk:
    index: int
    title: str
    level: int
    text: str
    line_start: int
    line_end: int


def slugify(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or fallback


def first_part_value(parts: list[str], keys: tuple[str, ...], default: str = "") -> str:
    key_set = {key.casefold() for key in keys}
    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        if key.strip().casefold() in key_set:
            return value.strip()
    return default


def split_csv_like(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，;；/|]", value or "") if item.strip()]


def normalize_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def split_chunks(text: str) -> list[Chunk]:
    """Split markdown by headings; plain text falls back to paragraph chunks."""
    lines = normalize_lines(text)
    heading_rows: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            heading_rows.append((i, len(match.group(1)), match.group(2).strip()))

    chunks: list[Chunk] = []
    if heading_rows:
        for idx, (line_no, level, title) in enumerate(heading_rows):
            next_line = heading_rows[idx + 1][0] if idx + 1 < len(heading_rows) else len(lines) + 1
            body = "\n".join(lines[line_no: next_line - 1]).strip()
            chunks.append(Chunk(idx + 1, title, level, body, line_no, next_line - 1))
        return chunks

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    for idx, paragraph in enumerate(paragraphs, start=1):
        chunks.append(Chunk(idx, f"Paragraph {idx}", 1, paragraph, idx, idx))
    return chunks


def section_key(title: str) -> str:
    value = title.strip().casefold()
    if any(token in value for token in ("cast", "characters", "roles", "角色")):
        return "cast"
    if any(token in value for token in ("clue", "evidence", "线索", "证据")):
        return "clues"
    if any(token in value for token in ("truth", "solution", "reveal", "真相", "结局")):
        return "truth"
    if any(token in value for token in ("setting", "background", "intro", "story", "背景", "开场")):
        return "intro"
    if any(token in value for token in ("rule", "规则")):
        return "rules"
    if any(token in value for token in ("action", "mechanic", "declaration", "vote", "murder", "guard", "investigate", "行动", "投票")):
        return "actions"
    if any(token in value for token in ("secret", "private", "秘密")):
        return "secrets"
    return "other"


def parse_key_value_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in normalize_lines(text):
        match = KEY_VALUE_RE.match(line)
        if match:
            values[match.group(1).strip().casefold()] = match.group(2).strip()
    return values


def strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*+]|\d+[.)])\s*", "", line).strip()


def extract_bullets(text: str) -> list[str]:
    bullets = []
    for line in normalize_lines(text):
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            item = strip_bullet(line)
            if item:
                bullets.append(item)
    return bullets


def split_label_content(item: str, fallback_label: str) -> tuple[str, str]:
    if ":" in item:
        left, right = item.split(":", 1)
        return left.strip() or fallback_label, right.strip()
    if " - " in item:
        left, right = item.split(" - ", 1)
        return left.strip() or fallback_label, right.strip()
    return fallback_label, item.strip()


def detect_language(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return "zh-CN" if chinese_chars >= 20 else "en"


def make_line_trace(source_path: Path, field: str, line_no: int | None, evidence: str = "") -> dict[str, Any]:
    return {
        "field": field,
        "source": str(source_path),
        "line_start": line_no,
        "line_end": line_no,
        "chunk_index": None,
        "heading": None,
        "evidence": evidence[:160],
    }


def make_chunk_trace(source_path: Path, field: str, chunk: Chunk | None, evidence: str = "") -> dict[str, Any]:
    if chunk is None:
        return make_line_trace(source_path, field, None, evidence)
    return {
        "field": field,
        "source": str(source_path),
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "chunk_index": chunk.index,
        "heading": chunk.title,
        "evidence": evidence[:160],
    }


def find_key_value_trace(source_text: str, source_path: Path, field: str, keys: set[str]) -> dict[str, Any] | None:
    for line_no, line in enumerate(normalize_lines(source_text), start=1):
        match = KEY_VALUE_RE.match(line)
        if match and match.group(1).strip().casefold() in keys:
            return make_line_trace(source_path, field, line_no, line.strip())
    return None


def build_candidates(chunks: list[Chunk], source_text: str, source_path: Path) -> dict[str, Any]:
    all_key_values = parse_key_value_lines(source_text)
    title = all_key_values.get("title") or all_key_values.get("name")
    title_trace = find_key_value_trace(source_text, source_path, "script_info.title", {"title", "name"})
    if not title:
        heading = chunks[0].title if chunks else source_path.stem
        title = heading if section_key(heading) == "other" else source_path.stem.replace("_", " ").title()
        title_trace = make_chunk_trace(source_path, "script_info.title", chunks[0] if chunks else None, title)

    sections: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        sections.setdefault(section_key(chunk.title), []).append(chunk)

    intro_text = "\n\n".join(chunk.text for chunk in sections.get("intro", [])).strip()
    rules_text = "\n\n".join(chunk.text for chunk in sections.get("rules", [])).strip()
    intro_trace = make_chunk_trace(source_path, "public_materials.public_intro", sections.get("intro", [None])[0], intro_text)
    rules_trace = make_chunk_trace(source_path, "public_materials.rules_text", sections.get("rules", [None])[0], rules_text)
    setting_trace = find_key_value_trace(source_text, source_path, "public_materials.setting", {"setting"})

    cast = []
    cast_trace = []
    for chunk in sections.get("cast", []):
        for idx, item in enumerate(extract_bullets(chunk.text), start=1):
            name, body = split_label_content(item, f"Character {idx}")
            parts = [part.strip() for part in re.split(r"\s+\|\s+", body) if part.strip()]
            public_profile = parts[0] if parts else body
            secret = first_part_value(parts, ("secret", "private", "hidden", "秘密", "私密"))
            goal = first_part_value(parts, ("goal", "objective", "want", "目标", "目的"), "Find the truth.")
            attitude = first_part_value(parts, ("attitude", "stance", "personality", "性格", "态度"))
            voice = first_part_value(parts, ("voice", "style", "speaking", "tone", "语气", "说话方式"))
            knows = split_csv_like(first_part_value(parts, ("knows", "known", "知道", "知情")))
            forbidden = split_csv_like(first_part_value(parts, ("forbidden", "must not reveal", "不能说", "禁止透露")))
            cast.append({
                "name": name,
                "public_profile": public_profile,
                "secret": secret,
                "goal": goal,
                "attitude": attitude,
                "voice": voice,
                "knows": knows,
                "forbidden": forbidden,
                "_trace": make_chunk_trace(source_path, f"cast.{name}", chunk, item),
            })
            cast_trace.append(make_chunk_trace(source_path, f"cast.{name}", chunk, item))
    if not cast:
        cast = [
            {
                "name": "Character A",
                "public_profile": "Public profile needs manual review.",
                "secret": "",
                "goal": "Find the truth.",
                "_trace": make_line_trace(source_path, "cast.Character A", None, "fallback character"),
            },
            {
                "name": "Character B",
                "public_profile": "Public profile needs manual review.",
                "secret": "",
                "goal": "Find the truth.",
                "_trace": make_line_trace(source_path, "cast.Character B", None, "fallback character"),
            },
        ]
        cast_trace = [item["_trace"] for item in cast]

    clues = []
    clue_trace = []
    for chunk in sections.get("clues", []):
        for idx, item in enumerate(extract_bullets(chunk.text), start=1):
            title_part, content = split_label_content(item, f"Clue {idx}")
            trace = make_chunk_trace(source_path, f"clues.{title_part}", chunk, item)
            clues.append({"title": title_part, "content": content or item, "_trace": trace})
            clue_trace.append(trace)

    truth_items = []
    truth_trace = []
    for chunk in sections.get("truth", []):
        for idx, item in enumerate(extract_bullets(chunk.text), start=1):
            code_match = re.search(r"\[code\s*:\s*([^\]]+)\]", item, flags=re.IGNORECASE)
            code_word = code_match.group(1).strip() if code_match else ""
            clean = re.sub(r"\[code\s*:\s*[^\]]+\]\s*", "", item, flags=re.IGNORECASE).strip()
            label, content = split_label_content(clean, f"Truth {idx}")
            trace = make_chunk_trace(source_path, f"truth_model.{label}", chunk, item)
            truth_items.append({"title": label, "content": content or clean, "code_word": code_word, "_trace": trace})
            truth_trace.append(trace)
    if not truth_items:
        trace = make_line_trace(source_path, "truth_model.Truth 1", None, "fallback truth")
        truth_items = [{"title": "Truth 1", "content": "Truth content requires manual review.", "code_word": "", "_trace": trace}]
        truth_trace = [trace]

    return {
        "title": title,
        "author": all_key_values.get("author"),
        "language": detect_language(source_text),
        "intro": intro_text or "Public introduction requires manual review.",
        "setting": all_key_values.get("setting") or intro_text or "Setting requires manual review.",
        "rules": rules_text or "Discuss, reveal clues, then accuse.",
        "cast": cast,
        "clues": clues,
        "truth_items": truth_items,
        "sections": {key: [chunk.title for chunk in value] for key, value in sections.items()},
        "source_trace": {
            "title": title_trace,
            "author": find_key_value_trace(source_text, source_path, "script_info.author", {"author"}),
            "setting": setting_trace,
            "public_intro": intro_trace,
            "rules_text": rules_trace,
            "cast": cast_trace,
            "clues": clue_trace,
            "truth_items": truth_trace,
        },
    }


def make_character_id(name: str, used: set[str], index: int) -> str:
    base = slugify(name, f"char_{index}")
    if not base.startswith("char_"):
        base = f"char_{base}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def build_schema(candidates: dict[str, Any], script_id: str, source_path: Path) -> dict[str, Any]:
    used_character_ids: set[str] = set()
    character_records = []
    cast_public = []
    role_slots = []
    role_packets = []
    for index, item in enumerate(candidates["cast"], start=1):
        character_id = make_character_id(item["name"], used_character_ids, index)
        goal_text = item.get("goal") or "Find the truth."
        secret_text = item.get("secret") or "Private details require manual review."
        character_records.append({
            "character_id": character_id,
            "display_name": item["name"],
            "public_profile": item.get("public_profile") or "Public profile requires manual review.",
            "goals": [{"goal_id": f"goal_{character_id}", "description": goal_text, "visibility": "private"}],
            "relationships": [],
            "secrets": [{"secret_id": f"secret_{character_id}", "description": secret_text, "reveal_policy": "reveal_only_when_challenged"}],
        })
        cast_public.append({
            "character_id": character_id,
            "display_name": item["name"],
            "public_profile": item.get("public_profile") or "Public profile requires manual review.",
        })
        role_slots.append({"slot_id": f"slot_{character_id}", "character_id": character_id, "required": True})
        role_packets.append({
            "packet_id": f"packet_{character_id}_intro",
            "character_id": character_id,
            "phase_id": "intro",
            "content": secret_text,
            "content_ref": None,
            "visibility": "private",
            "recipients": [],
            "after_reveal_visibility": "private",
            "reveal_instruction": "reveal_only_when_challenged",
        })

    clue_records = []
    assets = []
    reveal_rules = []
    phases = [
        {
            "phase_id": "intro",
            "title": "Intro",
            "phase_type": "intro",
            "order": 1,
            "materials_to_release": [],
            "clues_to_reveal": [],
            "dm_instructions": {
                "opening_text": "Welcome players and explain the public setup.",
                "pace_notes": "Manual review required before live hosting.",
                "transition_condition": "players_confirm_rules",
            },
        },
        {
            "phase_id": "discussion",
            "title": "Discussion",
            "phase_type": "free_discussion",
            "order": 2,
            "materials_to_release": [],
            "clues_to_reveal": [],
            "dm_instructions": {
                "opening_text": "Begin open discussion.",
                "pace_notes": "Only use public information.",
                "transition_condition": "dm_manual",
            },
        },
    ]
    order = 3
    for index, clue in enumerate(candidates["clues"], start=1):
        clue_id = f"clue_{index}"
        phase_id = f"clue_{index}_release"
        asset_id = f"asset_{clue_id}"
        clue_records.append({
            "clue_id": clue_id,
            "title": clue["title"],
            "clue_type": "text",
            "content": clue["content"],
            "asset_refs": [asset_id],
            "initial_visibility": "hidden",
            "reveal_phase": phase_id,
            "related_characters": [],
        })
        assets.append({
            "asset_id": asset_id,
            "asset_type": "document",
            "path": f"assets/imported/{clue_id}.txt",
            "description": f"Imported text clue candidate: {clue['title']}",
            "linked_clue_id": clue_id,
            "visibility": "hidden",
            "source_page": None,
            "requires_manual_review": True,
        })
        reveal_rules.append({
            "rule_id": f"reveal_{clue_id}",
            "target_type": "clue",
            "target_id": clue_id,
            "trigger_type": "phase_start",
            "phase_id": phase_id,
            "recipients": ["ALL"],
            "after_reveal_visibility": "public",
            "announcement_template": f"New clue revealed: {clue['title']}",
        })
        phases.append({
            "phase_id": phase_id,
            "title": f"Clue {index} Release",
            "phase_type": "discovery",
            "order": order,
            "materials_to_release": [],
            "clues_to_reveal": [clue_id],
            "dm_instructions": {
                "opening_text": f"Reveal clue candidate: {clue['title']}",
                "pace_notes": "Confirm clue timing before live use.",
                "transition_condition": "dm_manual",
            },
        })
        order += 1

    phases.extend([
        {
            "phase_id": "accusation",
            "title": "Accusation",
            "phase_type": "accusation",
            "order": order,
            "materials_to_release": [],
            "clues_to_reveal": [],
            "dm_instructions": {
                "opening_text": "Collect player accusations.",
                "pace_notes": "Do not reveal truth until final_reveal_sequence is triggered.",
                "transition_condition": "accusation_submitted",
            },
        },
        {
            "phase_id": "recap",
            "title": "Recap",
            "phase_type": "recap",
            "order": order + 1,
            "materials_to_release": [],
            "clues_to_reveal": [],
            "dm_instructions": {
                "opening_text": "Close with recap after final reveal.",
                "pace_notes": "Answer questions using public final reveal information.",
                "transition_condition": "players_done",
            },
        },
    ])

    truth_nodes = []
    final_reveal_sequence = []
    for index, item in enumerate(candidates["truth_items"], start=1):
        node_id = f"truth_{index}"
        truth_nodes.append({
            "node_id": node_id,
            "node_type": "fact",
            "content": item["content"],
            "conditions": [],
            "related_characters": [character_records[0]["character_id"]] if character_records else [],
            "related_clues": [clue_records[0]["clue_id"]] if clue_records else [],
        })
        final_reveal_sequence.append({
            "step": index,
            "trigger": "code_word" if item.get("code_word") else "dm_reveal",
            "speaker_character_id": None,
            "required_code_word": item.get("code_word") or None,
            "content_ref": node_id,
            "next_step_condition": None,
        })

    evidence_links = []
    if clue_records:
        for index, truth in enumerate(truth_nodes, start=1):
            evidence_links.append({
                "link_id": f"link_truth_{index}_clue_1",
                "truth_node_id": truth["node_id"],
                "clue_id": clue_records[0]["clue_id"],
                "strength": "suggests",
                "explanation": "Imported draft link; manual review required.",
            })

    first_truth = truth_nodes[0]["node_id"]
    return {
        "schema_version": "0.2.1",
        "script_info": {
            "id": script_id,
            "title": candidates["title"],
            "author": candidates.get("author"),
            "game_mode": "fixed_truth",
            "player_count": {"min": len(character_records), "max": len(character_records), "recommended": len(character_records)},
            "language": candidates["language"],
        },
        "license_info": {
            "source": str(source_path),
            "license_type": "unknown_imported_text",
            "commercial_allowed": False,
            "redistribution_allowed": False,
            "attribution_required": True,
            "notes": "Imported draft. Human must verify rights before demo or redistribution.",
        },
        "public_materials": {
            "setting": candidates["setting"],
            "public_intro": candidates["intro"],
            "rules_text": candidates["rules"],
            "cast_public_list": cast_public,
            "opening_script": f"Welcome to {candidates['title']}. This is an imported draft and requires manual review.",
            "player_guidance": "Stay in character. Do not reveal private packets unless instructed.",
            "content_notes": "Imported text requires manual safety/content review.",
        },
        "player_config": {"mode": "all_role_players", "role_player_slots": role_slots, "observer_slots": []},
        "cast": character_records,
        "phases": phases,
        "role_packets": role_packets,
        "clues": clue_records,
        "assets": assets,
        "reveal_rules": reveal_rules,
        "truth_model": {
            "truth_type": "fixed",
            "case_questions": [{"question_id": "main_truth", "prompt": "What is the truth?", "expected_answer_node_ids": [first_truth]}],
            "truth_nodes": truth_nodes,
            "evidence_links": evidence_links,
        },
        "forbidden_spoilers": [
            {
                "spoiler_id": f"spoiler_{truth['node_id']}",
                "spoiler_type": "truth_node",
                "content": truth["content"],
                "aliases": [],
                "forbidden_until_phase": "accusation",
                "allowed_after_phase": "accusation",
                "allowed_after_reveal_rule": None,
                "allowed_after_condition": None,
            }
            for truth in truth_nodes
        ],
        "action_rules": {"enabled": False, "action_types": [], "resolution_order": [], "blocking_rules": [], "outcomes": []},
        "forms": [
            {
                "form_id": "accusation_sheet",
                "title": "Accusation Sheet",
                "form_type": "accusation_sheet",
                "per_player_or_global": "global",
                "read_aloud_after_submit": True,
                "used_for_resolution": True,
                "fields": [
                    {"field_id": "whodunit", "label": "Who did it?", "field_type": "character_ref", "required": True},
                    {"field_id": "how", "label": "How?", "field_type": "free_text", "required": True},
                    {"field_id": "why", "label": "Why?", "field_type": "free_text", "required": True},
                ],
                "submit_phase": "accusation",
            }
        ],
        "ending_rules": {
            "ending_type": "fixed_reveal",
            "conditions": [
                {
                    "ending_id": "ending_imported_fixed",
                    "priority": 1,
                    "when": "manual accusation complete",
                    "ending_title": "Imported Truth Reveal",
                    "ending_text_ref": "ending_text_imported",
                }
            ],
            "final_reveal_sequence": final_reveal_sequence,
        },
        "scoring_rules": {"enabled": False, "goal_checks": []},
        "hint_rules": [
            {
                "hint_id": "hint_imported_method",
                "level": "L1",
                "phase_id": "discussion",
                "allowed_when": "players are stalled",
                "allowed_clue_ids": [],
                "allowed_truth_nodes": [],
                "forbidden_truth_nodes": [node["node_id"] for node in truth_nodes],
                "template": "Rebuild the public timeline before making an accusation.",
                "cooldown_turns": 3,
                "spoiler_check_mode": "strict",
            }
        ],
    }


def make_evidence_id(title: str, used: set[str], index: int) -> str:
    base = slugify(title, f"evidence_{index}")
    if not base.startswith("evidence_"):
        base = f"evidence_{base}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def imported_input_format(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "md"
    if suffix == ".txt":
        return "txt"
    return "manual"


def build_game_schema_v0_3(candidates: dict[str, Any], script_id: str, source_path: Path) -> dict[str, Any]:
    """Build a single-player GameSchema v0.3 draft from imported text candidates.

    This is intentionally conservative: it creates a runnable skeleton and uses
    review.author_questions for thin NPC characterization instead of asking the
    author to write technical schema fields.
    """
    used_character_ids: set[str] = set()
    character_ids = [
        make_character_id(item["name"], used_character_ids, index)
        for index, item in enumerate(candidates["cast"], start=1)
    ]
    culprit_id = character_ids[0]

    used_evidence_ids: set[str] = set()
    evidence_items = candidates.get("clues") or [
        {"title": "Imported Evidence", "content": "Evidence details require manual review."}
    ]
    evidence_ids = [
        make_evidence_id(item.get("title", f"Evidence {index}"), used_evidence_ids, index)
        for index, item in enumerate(evidence_items, start=1)
    ]
    primary_evidence_id = evidence_ids[0]
    scene_id = "scene_imported_main"
    culprit_truth_id = "truth_culprit_imported"
    motive_truth_id = "truth_motive_imported"
    method_truth_id = "truth_method_imported"
    lie_id = f"lie_{culprit_id}_draft_secret"

    truth_candidates = candidates.get("truth_items") or []
    motive_text = truth_candidates[0]["content"] if truth_candidates else "The motive requires author confirmation."
    method_text = truth_candidates[1]["content"] if len(truth_candidates) > 1 else "The method requires author confirmation."
    culprit_text = f"The imported draft provisionally points to {candidates['cast'][0]['name']} as the culprit; confirm before running."

    truth_nodes = [
        {
            "truth_id": culprit_truth_id,
            "truth_type": "identity",
            "content": culprit_text,
            "revealed_by_default": False,
            "related_character_ids": [culprit_id],
            "related_evidence_ids": [primary_evidence_id],
            "required_clue_ids": [primary_evidence_id],
            "supporting_character_ids": [culprit_id],
            "timeline_refs": ["timeline_imported_truth"],
            "unlock_condition": {"discovered_evidence_ids_all": [primary_evidence_id]},
        },
        {
            "truth_id": motive_truth_id,
            "truth_type": "motive",
            "content": motive_text,
            "revealed_by_default": False,
            "related_character_ids": [culprit_id],
            "related_evidence_ids": [primary_evidence_id],
            "required_clue_ids": [primary_evidence_id],
            "supporting_character_ids": [culprit_id],
            "timeline_refs": ["timeline_imported_truth"],
            "unlock_condition": {"discovered_evidence_ids_all": [primary_evidence_id]},
        },
        {
            "truth_id": method_truth_id,
            "truth_type": "method",
            "content": method_text,
            "revealed_by_default": False,
            "related_character_ids": [culprit_id],
            "related_evidence_ids": [primary_evidence_id],
            "required_clue_ids": [primary_evidence_id],
            "supporting_character_ids": [culprit_id],
            "timeline_refs": ["timeline_imported_truth"],
            "unlock_condition": {"discovered_evidence_ids_all": [primary_evidence_id]},
        },
    ]

    npc_characters = []
    for index, (item, character_id) in enumerate(zip(candidates["cast"], character_ids), start=1):
        public_profile = item.get("public_profile") or "Public profile requires manual review."
        private_profile = item.get("secret") or "Private details require manual review."
        attitude = item.get("attitude") or item.get("voice") or ""
        goal_text = item.get("goal") or "Find the truth."
        known_truth_ids = [motive_truth_id, method_truth_id] if character_id == culprit_id else [method_truth_id]
        npc_characters.append(
            {
                "character_id": character_id,
                "display_name": item["name"],
                "public_profile": public_profile,
                "private_profile": private_profile,
                "known_truth_ids": known_truth_ids,
                "initial_attitude": attitude,
                "conversation_rules": {
                    "can_lie": character_id == culprit_id,
                    "lie_ids": [lie_id] if character_id == culprit_id else [],
                    "forbidden_truth_ids": [culprit_truth_id],
                    "fallback_style": item.get("voice") or attitude,
                },
                "action_profile": {
                    "initial_location_scene_id": scene_id,
                    "initial_stance": attitude,
                    "initial_stress": 0,
                    "goals": [
                        {
                            "goal_id": f"goal_{character_id}",
                            "priority": max(1, 10 - index),
                            "directive": goal_text,
                        }
                    ],
                    "rules": [],
                },
            }
        )

    evidence = []
    for evidence_id, clue in zip(evidence_ids, evidence_items):
        evidence.append(
            {
                "evidence_id": evidence_id,
                "title": clue.get("title", evidence_id),
                "evidence_type": "document",
                "content": clue.get("content", ""),
                "scene_id": scene_id,
                "initially_discovered": False,
                "unlock_condition": f"search {scene_id}",
                "related_truth_ids": [motive_truth_id, method_truth_id],
                "can_confront_lie_ids": [lie_id] if evidence_id == primary_evidence_id else [],
                "source_scene_id": scene_id,
                "lifecycle": {
                    "initial_state": "discoverable",
                    "discoverable_when": {},
                    "reveal_when": {"discovered_evidence_ids_all": [evidence_id]},
                    "lock_reason": "",
                },
            }
        )

    scoring_items = [
        {
            "score_id": "score_culprit",
            "field_id": "culprit",
            "prompt": "Who is the culprit?",
            "expected_character_id": culprit_id,
            "expected_truth_ids": [],
            "expected_evidence_ids": [],
            "expected_lie_ids": [],
            "points": 2,
        },
        {
            "score_id": "score_motive",
            "field_id": "motive",
            "prompt": "What was the motive?",
            "expected_character_id": None,
            "expected_truth_ids": [motive_truth_id],
            "expected_evidence_ids": [primary_evidence_id],
            "expected_lie_ids": [],
            "points": 2,
        },
        {
            "score_id": "score_method",
            "field_id": "method",
            "prompt": "What was the method?",
            "expected_character_id": None,
            "expected_truth_ids": [method_truth_id],
            "expected_evidence_ids": [primary_evidence_id],
            "expected_lie_ids": [],
            "points": 2,
        },
        {
            "score_id": "score_evidence_chain",
            "field_id": "evidence_chain",
            "prompt": "Which evidence supports the solution?",
            "expected_character_id": None,
            "expected_truth_ids": [culprit_truth_id, motive_truth_id, method_truth_id],
            "expected_evidence_ids": [primary_evidence_id],
            "expected_lie_ids": [lie_id],
            "points": 4,
        },
    ]

    schema = {
        "schema_version": "game_schema_v0.3",
        "game_info": {
            "id": f"{script_id}_game_v0_3",
            "title": candidates["title"],
            "language": candidates["language"],
            "mode": "single_player_detective",
            "player_role": "detective",
        },
        "source_info": {
            "source_type": "murder_mystery_text",
            "input_format": imported_input_format(source_path),
            "license_status": "unknown_imported_text",
            "notes": "Auto-generated GameSchema draft from imported md/txt. Structural fields are provisional.",
        },
        "review": {
            "status": "needs_review",
            "missing_fields": [],
            "logic_warnings": [
                "This GameSchema draft is auto-generated and needs semantic review before play.",
            ],
            "spoiler_risks": [
                "Imported truth and private character text must not be shown before evidence unlocks it.",
            ],
            "manual_checklist": [
                "Confirm culprit, motive, method, evidence chain, and NPC knowledge boundaries.",
            ],
            "source_traces": [
                {
                    "field": "game_info.title",
                    "source": str(source_path),
                    "confidence": 0.75,
                }
            ],
            "author_questions": [],
        },
        "public_case": {
            "setting": candidates["setting"],
            "opening_text": candidates["intro"],
            "detective_briefing": "Search the imported scene, question suspects, confront lies with evidence, and submit a structured accusation.",
            "case_objectives": [
                "Search available scenes.",
                "Review discovered evidence.",
                "Question NPC suspects.",
                "Use evidence to confront lies.",
                "Submit culprit, motive, method, and evidence chain.",
            ],
            "initial_available_scene_ids": [scene_id],
            "content_warnings": ["imported fictional mystery content"],
        },
        "npc_characters": npc_characters,
        "scenes": [
            {
                "scene_id": scene_id,
                "title": "Imported Investigation Scene",
                "description": candidates["setting"],
                "initially_unlocked": True,
                "unlock_condition": "available at start",
                "evidence_ids": evidence_ids,
                "npc_ids": character_ids,
                "entry_condition": {},
                "exit_condition": {"searched_scene_ids_all": [scene_id]},
                "search_result_events": [
                    {
                        "event_id": "scene_imported_main_search_reveals_evidence",
                        "event_type": "reveal_clues",
                        "target_ids": evidence_ids,
                    }
                ],
                "scene_tags": ["imported", "needs_review"],
            }
        ],
        "evidence": evidence,
        "lies": [
            {
                "lie_id": lie_id,
                "character_id": culprit_id,
                "claim": "I have nothing important to hide.",
                "truth_id": culprit_truth_id,
                "required_evidence_ids": [primary_evidence_id],
                "break_result": {
                    "unlocked_truth_ids": [culprit_truth_id, motive_truth_id, method_truth_id],
                    "phase_unlock_ids": ["phase_confrontation"],
                    "attitude_shift": "cornered",
                    "response_guidance": "When confronted with the imported key evidence, stop denying that something is being hidden.",
                },
            }
        ],
        "truth_model": {
            "culprit_character_id": culprit_id,
            "motive_truth_id": motive_truth_id,
            "method_truth_id": method_truth_id,
            "truth_nodes": truth_nodes,
            "timeline": [
                {
                    "timeline_id": "timeline_imported_truth",
                    "time_label": "Imported timeline",
                    "event": "The source text contains the provisional truth chain for this case.",
                    "truth_ids": [culprit_truth_id, motive_truth_id, method_truth_id],
                }
            ],
            "evidence_links": [
                {
                    "link_id": f"link_{primary_evidence_id}_{truth_id}",
                    "truth_id": truth_id,
                    "evidence_id": primary_evidence_id,
                    "strength": "supports",
                    "explanation": "Auto-generated support link from imported text; review required.",
                }
                for truth_id in (culprit_truth_id, motive_truth_id, method_truth_id)
            ],
        },
        "phases": [
            {
                "phase_id": "phase_intro",
                "title": "Intro",
                "phase_type": "intro",
                "order": 1,
                "unlock_condition": "available at start",
                "unlocked_scene_ids": [scene_id],
                "unlocked_evidence_ids": [],
                "allowed_actions": ["status", "search", "ask"],
                "entry_condition": {},
                "exit_condition": {"searched_scene_ids_all": [scene_id]},
                "mandatory_events": [],
                "optional_events": [],
            },
            {
                "phase_id": "phase_investigation",
                "title": "Investigation",
                "phase_type": "investigation",
                "order": 2,
                "unlock_condition": "after first search",
                "unlocked_scene_ids": [scene_id],
                "unlocked_evidence_ids": evidence_ids,
                "allowed_actions": ["status", "search", "show_evidence", "ask"],
                "entry_condition": {"searched_scene_ids_all": [scene_id]},
                "exit_condition": {"discovered_evidence_ids_all": [primary_evidence_id]},
                "mandatory_events": [],
                "optional_events": [],
            },
            {
                "phase_id": "phase_confrontation",
                "title": "Confrontation",
                "phase_type": "confrontation",
                "order": 3,
                "unlock_condition": f"after {lie_id} is broken",
                "unlocked_scene_ids": [scene_id],
                "unlocked_evidence_ids": evidence_ids,
                "allowed_actions": ["status", "show_evidence", "ask", "accuse"],
                "entry_condition": {"broken_lie_ids_any": [lie_id]},
                "exit_condition": {"broken_lie_ids_all": [lie_id]},
                "mandatory_events": [],
                "optional_events": [],
            },
            {
                "phase_id": "phase_accusation",
                "title": "Accusation",
                "phase_type": "accusation",
                "order": 4,
                "unlock_condition": "after key truth is unlocked",
                "unlocked_scene_ids": [scene_id],
                "unlocked_evidence_ids": evidence_ids,
                "allowed_actions": ["status", "show_evidence", "accuse"],
                "entry_condition": {"unlocked_truth_ids_any": [culprit_truth_id]},
                "exit_condition": {"accusation_submitted": True},
                "mandatory_events": [],
                "optional_events": [],
            },
            {
                "phase_id": "phase_recap",
                "title": "Recap",
                "phase_type": "recap",
                "order": 5,
                "unlock_condition": "after accusation",
                "unlocked_scene_ids": [scene_id],
                "unlocked_evidence_ids": evidence_ids,
                "allowed_actions": ["status", "review"],
                "entry_condition": {"game_over": True},
                "exit_condition": {},
                "mandatory_events": [],
                "optional_events": [],
            },
        ],
        "mechanics": {
            "starting_phase_id": "phase_intro",
            "max_hint_level": 1,
            "commands": {
                "ask": "/ask <character_id> <question>",
                "search": "/search <area_id>",
                "inspect": "/show <evidence_id>",
                "show_evidence": "/show <evidence_id>",
                "accuse": "/accuse <suspect_id> motive=<truth_id> method=<truth_id> evidence=<evidence_id,...>",
                "status": "/status",
                "hint": "/hint",
            },
        },
        "accusation_rules": {
            "required_fields": ["culprit", "motive", "method", "evidence_chain"],
            "score_thresholds": {"perfect": 10, "pass": 6},
            "scoring_items": scoring_items,
        },
        "ending_rules": {
            "required_fields": ["culprit", "motive", "method", "evidence_chain"],
            "score_thresholds": {"perfect": 10, "pass": 6},
            "scoring_items": scoring_items,
        },
        "recap": {
            "truth_summary": "Imported truth summary requires author confirmation.",
            "timeline_summary": "Imported timeline requires author confirmation.",
            "missed_content_templates": [
                "Review any unresolved NPC author questions before presenting this case.",
            ],
        },
        "game_state_spec": {
            "snapshot_fields": [
                "current_phase_id",
                "unlocked_scene_ids",
                "searched_scene_ids",
                "clue_state_by_id",
                "unlocked_truth_ids",
                "broken_lie_ids",
                "npc_runtime_state",
                "action_history",
            ]
        },
        "x_import_trace": {
            "generated_by": IMPORTER_NAME,
            "source_path": str(source_path),
            "source_trace": candidates.get("source_trace", {}),
            "manual_review_required": True,
        },
    }
    schema["review"]["author_questions"] = build_npc_author_questions(schema)
    return schema


def score_confidence(candidates: dict[str, Any]) -> dict[str, float]:
    """Coarse confidence scores for human triage, not runtime decisions."""
    cast_score = min(1.0, len(candidates.get("cast", [])) / 3)
    clue_score = min(1.0, len(candidates.get("clues", [])) / 2) if candidates.get("clues") else 0.2
    truth_score = min(1.0, len(candidates.get("truth_items", [])) / 2)
    scores = {
        "title": 0.9 if candidates.get("source_trace", {}).get("title") else 0.5,
        "author": 0.85 if candidates.get("author") else 0.0,
        "public_materials": 0.75 if candidates.get("intro") and candidates.get("rules") else 0.35,
        "cast": round(cast_score, 2),
        "clues": round(clue_score, 2),
        "truth_model": round(truth_score, 2),
        "actions": 0.25 if candidates.get("sections", {}).get("actions") else 0.0,
    }
    scored_values = [value for key, value in scores.items() if key != "actions"]
    scores["overall"] = round(sum(scored_values) / len(scored_values), 2)
    return scores


def normalize_for_compare(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def meaningful_private_text(value: str) -> bool:
    lowered = value.casefold()
    return len(value.strip()) >= 12 and "requires manual review" not in lowered


def check_private_public_isolation(schema: dict[str, Any]) -> list[str]:
    """Warn when private/truth text appears in public-facing draft fields."""
    warnings: list[str] = []
    public_materials = schema.get("public_materials", {})
    public_blobs: list[tuple[str, str]] = []
    for key in ("setting", "public_intro", "rules_text", "opening_script", "player_guidance", "content_notes"):
        value = public_materials.get(key)
        if isinstance(value, str):
            public_blobs.append((f"public_materials.{key}", value))
    for index, item in enumerate(public_materials.get("cast_public_list", [])):
        if isinstance(item, dict):
            public_blobs.append((f"public_materials.cast_public_list[{index}].public_profile", item.get("public_profile", "")))
    for index, clue in enumerate(schema.get("clues", [])):
        if isinstance(clue, dict):
            public_blobs.append((f"clues[{index}].content", clue.get("content", "")))

    public_texts = [(path, normalize_for_compare(text)) for path, text in public_blobs if text]
    for path, text in public_texts:
        if re.search(r"\bsecret\s*:", text):
            warnings.append(f"{path} appears to contain an explicit Secret: label.")

    private_sources: list[tuple[str, str]] = []
    for index, packet in enumerate(schema.get("role_packets", [])):
        if isinstance(packet, dict) and packet.get("visibility") != "public":
            content = packet.get("content") or ""
            if meaningful_private_text(content):
                private_sources.append((f"role_packets[{index}].content", content))
    for cast_index, character in enumerate(schema.get("cast", [])):
        if isinstance(character, dict):
            for secret_index, secret in enumerate(character.get("secrets", [])):
                if isinstance(secret, dict):
                    content = secret.get("description") or ""
                    if meaningful_private_text(content):
                        private_sources.append((f"cast[{cast_index}].secrets[{secret_index}]", content))

    for private_path, private_text in private_sources:
        private_norm = normalize_for_compare(private_text)
        for public_path, public_norm in public_texts:
            if private_norm and private_norm in public_norm:
                warnings.append(f"{private_path} is duplicated in public field {public_path}.")

    for truth_index, truth in enumerate(schema.get("truth_model", {}).get("truth_nodes", [])):
        if not isinstance(truth, dict):
            continue
        truth_content = truth.get("content") or ""
        if not meaningful_private_text(truth_content):
            continue
        truth_norm = normalize_for_compare(truth_content)
        for public_path, public_norm in public_texts:
            if truth_norm and truth_norm in public_norm:
                warnings.append(f"truth_model.truth_nodes[{truth_index}].content is duplicated in public field {public_path}.")

    return warnings


def detect_missing_fields(candidates: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    missing = []
    sections = candidates.get("sections", {})
    if not candidates.get("author"):
        missing.append("Author not detected.")
    if not candidates.get("clues"):
        missing.append("No explicit clue bullets detected.")
    if not any(item.get("relationships") for item in schema.get("cast", [])):
        missing.append("Character relationships are not inferred.")
    if not any(packet.get("content_ref") for packet in schema.get("role_packets", [])):
        missing.append("No content_ref role packet files were inferred.")
    if sections.get("secrets"):
        missing.append("Private/secret sections detected; only intro private packets are drafted and round gating needs manual mapping.")
    if sections.get("actions"):
        missing.append("Action/mechanism sections detected but action_rules are not inferred in v0.1.")
    if schema.get("action_rules", {}).get("enabled") is False:
        missing.append("action_rules remain disabled in imported drafts.")
    if schema.get("license_info", {}).get("license_type", "").startswith("unknown"):
        missing.append("License and redistribution rights are unknown.")
    return missing


def build_import_trace(
    source_path: Path,
    candidates: dict[str, Any],
    confidence: dict[str, float],
    missing_fields: list[str],
    privacy_warnings: list[str],
    validation_errors: list[str],
) -> dict[str, Any]:
    return {
        "generated_by": IMPORTER_NAME,
        "source_path": str(source_path),
        "source_trace": candidates.get("source_trace", {}),
        "confidence": confidence,
        "missing_fields": missing_fields,
        "privacy_warnings": privacy_warnings,
        "validator": {
            "valid": not validation_errors,
            "error_count": len(validation_errors),
        },
        "manual_review_required": True,
    }


def build_validator_error_report(validation_errors: list[str]) -> dict[str, Any]:
    return {
        "valid": not validation_errors,
        "error_count": len(validation_errors),
        "errors": validation_errors,
    }


def detect_gaps(
    candidates: dict[str, Any],
    schema: dict[str, Any],
    validation_errors: list[str],
    missing_fields: list[str],
    privacy_warnings: list[str],
    game_schema: dict[str, Any] | None = None,
    game_validation_errors: list[str] | None = None,
) -> list[str]:
    gaps = []
    game_schema = game_schema or {}
    game_validation_errors = game_validation_errors or []
    gaps.extend(missing_fields)
    if any("requires manual review" in clue.get("content", "").casefold() for clue in schema["clues"]):
        gaps.append("At least one clue is placeholder text.")
    if any("requires manual review" in packet.get("content", "").casefold() for packet in schema["role_packets"]):
        gaps.append("At least one role packet uses placeholder private text.")
    if len(schema["cast"]) < 2:
        gaps.append("Fewer than two characters detected.")
    if not schema["truth_model"]["truth_nodes"]:
        gaps.append("No truth nodes detected.")
    if validation_errors:
        gaps.append("Validator reported errors; draft is not runtime-ready.")
    if game_validation_errors:
        gaps.append("GameSchema v0.3 validator reported errors; detective runtime draft is not ready.")
    if privacy_warnings:
        gaps.append("Private/public isolation warnings require manual review.")
    author_questions = game_schema.get("review", {}).get("author_questions", []) if isinstance(game_schema, dict) else []
    if author_questions:
        gaps.append(f"GameSchema v0.3 generated {len(author_questions)} plain-language NPC author question(s).")
    gaps.extend([
        "License and redistribution rights must be confirmed manually.",
        "Scoring rules and complex endings are not inferred in v0.1.",
        "Human must verify that public materials do not contain private spoilers.",
    ])
    return list(dict.fromkeys(gaps))


def report_chunks(chunks: list[Chunk]) -> str:
    rows = ["| # | heading | lines | chars |", "|---:|---|---|---:|"]
    for chunk in chunks:
        rows.append(f"| {chunk.index} | {chunk.title} | {chunk.line_start}-{chunk.line_end} | {len(chunk.text)} |")
    return "\n".join(rows)


def report_confidence(confidence: dict[str, float]) -> str:
    rows = ["| area | confidence |", "|---|---:|"]
    for key in sorted(confidence):
        rows.append(f"| {key} | {confidence[key]:.2f} |")
    return "\n".join(rows)


def flatten_trace_rows(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    trace = candidates.get("source_trace", {})
    rows: list[dict[str, Any]] = []
    for key in ("title", "author", "setting", "public_intro", "rules_text"):
        item = trace.get(key)
        if item:
            rows.append(item)
    for key in ("cast", "clues", "truth_items"):
        for item in trace.get(key, []):
            if item:
                rows.append(item)
    return rows


def report_source_trace(candidates: dict[str, Any]) -> str:
    rows = ["| field | heading | lines | evidence |", "|---|---|---|---|"]
    for item in flatten_trace_rows(candidates):
        line_start = item.get("line_start")
        line_end = item.get("line_end")
        lines = "n/a" if line_start is None else f"{line_start}-{line_end}"
        heading = item.get("heading") or ""
        evidence = (item.get("evidence") or "").replace("|", "\\|")
        rows.append(f"| {item.get('field', '')} | {heading} | {lines} | {evidence} |")
    return "\n".join(rows)


def build_import_report(
    source_path: Path,
    out_dir: Path,
    chunks: list[Chunk],
    candidates: dict[str, Any],
    validation_errors: list[str],
    confidence: dict[str, float],
    missing_fields: list[str],
    privacy_warnings: list[str],
    game_validation_errors: list[str] | None = None,
    author_questions: list[dict[str, Any]] | None = None,
) -> str:
    status = "PASS" if not validation_errors else "FAIL"
    game_validation_errors = game_validation_errors or []
    author_questions = author_questions or []
    game_status = "PASS" if not game_validation_errors else "FAIL"
    return "\n".join([
        "# Import Report",
        "",
        f"- Source: `{source_path}`",
        f"- Output directory: `{out_dir}`",
        f"- Draft title: {candidates['title']}",
        f"- Language: {candidates['language']}",
        f"- Characters detected: {len(candidates['cast'])}",
        f"- Clues detected: {len(candidates['clues'])}",
        f"- Truth items detected: {len(candidates['truth_items'])}",
        f"- Validator status: {status}",
        f"- GameSchema v0.3 validator status: {game_status}",
        f"- GameSchema v0.3 author questions: {len(author_questions)}",
        "",
        "## Confidence",
        "",
        report_confidence(confidence),
        "",
        "## Missing Fields / Manual Review",
        "",
        "\n".join(f"- {item}" for item in missing_fields) if missing_fields else "- None",
        "",
        "## Private/Public Isolation Warnings",
        "",
        "\n".join(f"- {item}" for item in privacy_warnings) if privacy_warnings else "- None",
        "",
        "## GameSchema v0.3 Author Questions",
        "",
        "\n".join(f"- {item.get('question', '')}" for item in author_questions) if author_questions else "- None",
        "",
        "## Source Trace",
        "",
        report_source_trace(candidates),
        "",
        "## Detected Sections",
        "",
        "```json",
        json.dumps(candidates["sections"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Chunks",
        "",
        report_chunks(chunks),
        "",
        "## Validator Errors",
        "",
        "\n".join(f"- {error}" for error in validation_errors) if validation_errors else "- None",
        "",
        "## GameSchema v0.3 Validator Errors",
        "",
        "\n".join(f"- {error}" for error in game_validation_errors) if game_validation_errors else "- None",
        "",
        "## Manual Confirmation",
        "",
        "This draft was written only because --confirm-manual-review was supplied. Review license, spoilers, cast packets, truth, and clue timing before live use.",
        "",
    ])


def build_gap_report(gaps: list[str], schema: dict[str, Any], privacy_warnings: list[str], validation_errors: list[str]) -> str:
    return "\n".join([
        "# Schema Gap Report",
        "",
        "## Required Human Review",
        "",
        "\n".join(f"- {gap}" for gap in gaps),
        "",
        "## Validator Errors",
        "",
        "\n".join(f"- {error}" for error in validation_errors) if validation_errors else "- None",
        "",
        "## Private/Public Isolation Warnings",
        "",
        "\n".join(f"- {warning}" for warning in privacy_warnings) if privacy_warnings else "- None",
        "",
        "## Draft Capability Summary",
        "",
        f"- game_mode: {schema['script_info']['game_mode']}",
        f"- phases: {', '.join(phase['phase_id'] for phase in schema['phases'])}",
        f"- role_packets: {len(schema['role_packets'])}",
        f"- clues: {len(schema['clues'])}",
        f"- truth_nodes: {len(schema['truth_model']['truth_nodes'])}",
        f"- final_reveal_sequence steps: {len(schema['ending_rules']['final_reveal_sequence'])}",
        "",
    ])


def build_game_schema_gap_report(game_schema: dict[str, Any], validation_errors: list[str]) -> str:
    questions = game_schema.get("review", {}).get("author_questions", []) or []
    return "\n".join(
        [
            "# GameSchema v0.3 Draft Summary",
            "",
            f"- game_id: {game_schema.get('game_info', {}).get('id', '')}",
            f"- review_status: {game_schema.get('review', {}).get('status', '')}",
            f"- npc_count: {len(game_schema.get('npc_characters', []))}",
            f"- evidence_count: {len(game_schema.get('evidence', []))}",
            f"- truth_count: {len(game_schema.get('truth_model', {}).get('truth_nodes', []))}",
            f"- author_questions: {len(questions)}",
            "",
            "## Author Questions",
            "",
            "\n".join(f"- {item.get('question', '')}" for item in questions) if questions else "- None",
            "",
            "## Validator Errors",
            "",
            "\n".join(f"- {error}" for error in validation_errors) if validation_errors else "- None",
            "",
        ]
    )


def compact_text(value: Any, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def markdown_table(rows: list[list[Any]], headers: list[str]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        clean = [compact_text(cell, 180).replace("|", "\\|") for cell in row]
        output.append("| " + " | ".join(clean) + " |")
    return "\n".join(output)


def schema_review_summary(schema: dict[str, Any]) -> str:
    script_info = schema.get("script_info", {})
    phase_rows = [
        [
            phase.get("order"),
            phase.get("phase_id"),
            phase.get("phase_type"),
            ", ".join(phase.get("materials_to_release", [])),
            ", ".join(phase.get("clues_to_reveal", [])),
        ]
        for phase in schema.get("phases", [])
        if isinstance(phase, dict)
    ]
    clue_rows = [
        [
            clue.get("clue_id"),
            clue.get("title"),
            clue.get("initial_visibility"),
            clue.get("reveal_phase"),
            ", ".join(clue.get("related_characters", [])),
            compact_text(clue.get("content")),
        ]
        for clue in schema.get("clues", [])
        if isinstance(clue, dict)
    ]
    packet_rows = [
        [
            packet.get("packet_id"),
            packet.get("character_id"),
            packet.get("phase_id"),
            packet.get("visibility"),
            packet.get("after_reveal_visibility"),
            packet.get("reveal_instruction"),
            compact_text(packet.get("content") or packet.get("content_ref")),
        ]
        for packet in schema.get("role_packets", [])
        if isinstance(packet, dict)
    ]
    truth_rows = [
        [
            node.get("node_id"),
            node.get("node_type"),
            ", ".join(node.get("related_clues", [])),
            ", ".join(node.get("related_characters", [])),
            compact_text(node.get("content")),
        ]
        for node in schema.get("truth_model", {}).get("truth_nodes", [])
        if isinstance(node, dict)
    ]
    final_rows = [
        [
            step.get("step"),
            step.get("trigger"),
            step.get("required_code_word"),
            step.get("content_ref"),
            step.get("next_step_condition"),
        ]
        for step in schema.get("ending_rules", {}).get("final_reveal_sequence", [])
        if isinstance(step, dict)
    ]
    spoiler_rows = [
        [
            item.get("spoiler_id"),
            item.get("spoiler_type"),
            item.get("allowed_after_phase"),
            item.get("allowed_after_reveal_rule"),
            compact_text(item.get("content")),
        ]
        for item in schema.get("forbidden_spoilers", [])
        if isinstance(item, dict)
    ]
    return "\n\n".join([
        "## Draft Summary",
        f"- script_id: {script_info.get('id')}",
        f"- title: {script_info.get('title')}",
        f"- game_mode: {script_info.get('game_mode')}",
        f"- player_count: {script_info.get('player_count')}",
        "",
        "## Phase / Release Map",
        markdown_table(phase_rows, ["order", "phase_id", "type", "materials", "clues"]),
        "",
        "## Clues",
        markdown_table(clue_rows, ["clue_id", "title", "visibility", "reveal_phase", "related_characters", "content"]),
        "",
        "## Role Packets",
        markdown_table(packet_rows, ["packet_id", "character", "phase", "visibility", "after_reveal", "instruction", "content_or_ref"]),
        "",
        "## Truth Nodes",
        markdown_table(truth_rows, ["node_id", "type", "related_clues", "related_characters", "content"]),
        "",
        "## Final Reveal Sequence",
        markdown_table(final_rows, ["step", "trigger", "code_word", "content_ref", "next_step_condition"]),
        "",
        "## Forbidden Spoilers",
        markdown_table(spoiler_rows, ["spoiler_id", "type", "allowed_after_phase", "allowed_after_rule", "content"]),
    ])


def source_trace_brief(schema: dict[str, Any]) -> str:
    trace = schema.get("x_import_trace", {}).get("source_trace", {})
    rows = []
    for key in ("title", "author", "setting", "public_intro", "rules_text"):
        item = trace.get(key)
        if item:
            rows.append([key, item.get("heading"), f"{item.get('line_start')}-{item.get('line_end')}", item.get("evidence")])
    for key in ("cast", "clues", "truth_items"):
        for item in trace.get(key, []):
            rows.append([item.get("field"), item.get("heading"), f"{item.get('line_start')}-{item.get('line_end')}", item.get("evidence")])
    return markdown_table(rows, ["field", "heading", "lines", "evidence"])


def risk_item(level: str, area: str, item: str, why: str, suggested_check: str) -> dict[str, str]:
    return {
        "level": level,
        "area": area,
        "item": item,
        "why": why,
        "suggested_check": suggested_check,
    }


def build_author_questions_report(game_schema: dict[str, Any], validation_errors: list[str]) -> str:
    questions = game_schema.get("review", {}).get("author_questions", []) or []
    if questions:
        question_rows = markdown_table(
            [
                [
                    item.get("target_id"),
                    item.get("topic"),
                    item.get("question"),
                    item.get("why"),
                ]
                for item in questions
                if isinstance(item, dict)
            ],
            ["npc", "topic", "question", "why"],
        )
    else:
        question_rows = "- None. The imported NPC setup is currently complete enough for a first draft."
    return "\n".join(
        [
            "# GameSchema v0.3 Author Questions",
            "",
            "These are plain-language follow-up questions for the script owner. They are generated only when NPC personality or character setup is too thin for believable roleplay.",
            "",
            "## Questions",
            "",
            question_rows,
            "",
            "## Validator Errors",
            "",
            "\n".join(f"- {error}" for error in validation_errors) if validation_errors else "- None",
            "",
        ]
    )


def detect_review_high_risk_items(schema: dict[str, Any], validation_errors: list[str]) -> list[dict[str, str]]:
    trace = schema.get("x_import_trace", {})
    risks: list[dict[str, str]] = []
    for error in validation_errors:
        risks.append(risk_item("HIGH", "validator", "validator error", error, "Fix schema validity before semantic review."))
    for warning in trace.get("privacy_warnings", []):
        risks.append(risk_item("HIGH", "public_private", "privacy warning", warning, "Confirm private/truth text is not present in public fields."))
    for missing in trace.get("missing_fields", []):
        level = "HIGH" if "Private/secret" in missing or "Action/mechanism" in missing else "MEDIUM"
        risks.append(risk_item(level, "import_gap", "missing/manual field", missing, "Compare against source text and decide whether the draft needs manual edits."))

    phase_ids = {phase.get("phase_id") for phase in schema.get("phases", []) if isinstance(phase, dict)}
    reveal_by_target = {
        rule.get("target_id"): rule
        for rule in schema.get("reveal_rules", [])
        if isinstance(rule, dict)
    }
    for clue in schema.get("clues", []):
        if not isinstance(clue, dict):
            continue
        clue_id = clue.get("clue_id")
        if clue.get("initial_visibility") == "public" and clue.get("reveal_phase"):
            risks.append(risk_item("HIGH", "clue_phase", str(clue_id), "Clue starts public but also has a reveal phase.", "Confirm whether the clue should be public from the start."))
        if clue.get("reveal_phase") not in phase_ids:
            risks.append(risk_item("HIGH", "clue_phase", str(clue_id), "Clue reveal_phase is missing from phases.", "Map the clue to a valid phase."))
        rule = reveal_by_target.get(clue_id)
        if not rule:
            risks.append(risk_item("MEDIUM", "clue_phase", str(clue_id), "No reveal_rule targets this clue.", "Confirm phase advancement can reveal this clue."))
        elif rule.get("phase_id") != clue.get("reveal_phase"):
            risks.append(risk_item("HIGH", "clue_phase", str(clue_id), "reveal_rule phase does not match clue reveal_phase.", "Align reveal_rule.phase_id and clue.reveal_phase."))

    public_packet_instructions = {"must_read_aloud", "reveal_at_phase_start"}
    for packet in schema.get("role_packets", []):
        if not isinstance(packet, dict):
            continue
        packet_id = str(packet.get("packet_id"))
        content = compact_text(packet.get("content") or packet.get("content_ref"))
        if "requires manual review" in content.casefold():
            risks.append(risk_item("MEDIUM", "role_packets", packet_id, "Role packet contains placeholder private text.", "Replace with source-grounded private packet content."))
        if packet.get("reveal_instruction") in public_packet_instructions and packet.get("after_reveal_visibility") != "public":
            risks.append(risk_item("MEDIUM", "role_packets", packet_id, "Packet is instructed to be read/revealed but does not become public.", "Confirm whether this is a private delivery or public reading."))
        if packet.get("visibility") == "group_limited" and not packet.get("recipients"):
            risks.append(risk_item("HIGH", "role_packets", packet_id, "group_limited packet has no recipients.", "Add recipients or change visibility."))

    truth_nodes = schema.get("truth_model", {}).get("truth_nodes", [])
    evidence_links = schema.get("truth_model", {}).get("evidence_links", [])
    linked_truth_ids = {link.get("truth_node_id") for link in evidence_links if isinstance(link, dict)}
    clue_targets = [link.get("clue_id") for link in evidence_links if isinstance(link, dict)]
    for node in truth_nodes:
        if isinstance(node, dict) and node.get("node_id") not in linked_truth_ids:
            risks.append(risk_item("HIGH", "truth_logic", str(node.get("node_id")), "Truth node has no evidence link.", "Check whether public clues can support this truth."))
    if len(set(clue_targets)) == 1 and len(truth_nodes) > 1:
        risks.append(risk_item("MEDIUM", "truth_logic", "evidence_links", "Multiple truth nodes are linked to one clue only.", "Check whether evidence links were over-collapsed by the importer."))

    final_sequence = schema.get("ending_rules", {}).get("final_reveal_sequence", [])
    final_refs = {step.get("content_ref") for step in final_sequence if isinstance(step, dict)}
    truth_ids = {node.get("node_id") for node in truth_nodes if isinstance(node, dict)}
    missing_final_truths = sorted(str(node_id) for node_id in truth_ids - final_refs)
    if missing_final_truths:
        risks.append(risk_item("HIGH", "ending_consistency", "final_reveal_sequence", f"Truth nodes missing from final reveal: {', '.join(missing_final_truths)}", "Confirm every required truth appears in final_reveal_sequence or is intentionally omitted."))
    steps = [step.get("step") for step in final_sequence if isinstance(step, dict)]
    if steps != sorted(steps):
        risks.append(risk_item("MEDIUM", "ending_consistency", "final_reveal_sequence", "Final reveal steps are not sorted.", "Confirm reveal order and code-word chain."))

    spoiler_contents = {
        normalize_for_compare(item.get("content"))
        for item in schema.get("forbidden_spoilers", [])
        if isinstance(item, dict)
    }
    for node in truth_nodes:
        content = normalize_for_compare(node.get("content") if isinstance(node, dict) else "")
        if content and content not in spoiler_contents:
            risks.append(risk_item("HIGH", "spoiler_risk", str(node.get("node_id")), "Truth node content is not mirrored in forbidden_spoilers.", "Add or confirm spoiler coverage before live use."))
    return risks


def format_risk_items(risks: list[dict[str, str]]) -> str:
    if not risks:
        return "- No high-risk items detected by local heuristics. Human semantic review is still required."
    rows = [
        [risk["level"], risk["area"], risk["item"], risk["why"], risk["suggested_check"]]
        for risk in risks
    ]
    return markdown_table(rows, ["level", "area", "item", "why", "suggested_check"])


def build_review_prompt(schema: dict[str, Any], import_report: str, validator_error_report: dict[str, Any], high_risks: list[dict[str, str]]) -> str:
    return "\n".join([
        "# AI-Assisted Semantic Review Prompt",
        "",
        "You are reviewing a semi-automatically imported murder-mystery ScriptSchema draft. Do not expand the schema and do not rewrite the story. Your job is to identify semantic risks and produce a concise human-review report.",
        "",
        "Use these local artifacts as the source of truth:",
        "- script.json: generated schema draft with x_import_trace.",
        "- import_report.md: extraction confidence, source trace, missing fields.",
        "- schema_gap_report.md: human review gaps.",
        "- validator_errors.json: structural validation status.",
        "",
        "Review priorities:",
        "1. public/private isolation: public_materials, public cast profiles, clues, prompt-facing content must not contain role secrets or final truth.",
        "2. role packet ownership: each private packet must belong to the correct character, phase, and reveal instruction.",
        "3. clue timing: every clue should reveal at the intended phase and should not appear too early.",
        "4. truth logic: truth_nodes should be supported by evidence_links and not contradict public materials.",
        "5. ending consistency: final_reveal_sequence should reveal truth in a coherent order, including any code-word chain.",
        "6. spoiler risk: forbidden_spoilers should cover final truth and any aliases that would spoil before allowed phases.",
        "",
        "Return format:",
        "- Blocking issues",
        "- High-risk ambiguities",
        "- Suggested manual edits",
        "- Questions for the human script owner",
        "- Safe-to-demo verdict: yes/no and why",
        "",
        "## Validator Status",
        "",
        "```json",
        json.dumps(validator_error_report, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Local High-Risk Heuristics",
        "",
        format_risk_items(high_risks),
        "",
        schema_review_summary(schema),
        "",
        "## Source Trace",
        "",
        source_trace_brief(schema),
        "",
        "## Import Report Excerpt",
        "",
        import_report[:6000],
        "",
    ])


def build_review_checklist(schema: dict[str, Any], high_risks: list[dict[str, str]]) -> str:
    counts = {
        "characters": len(schema.get("cast", [])),
        "role_packets": len(schema.get("role_packets", [])),
        "clues": len(schema.get("clues", [])),
        "truth_nodes": len(schema.get("truth_model", {}).get("truth_nodes", [])),
        "final_steps": len(schema.get("ending_rules", {}).get("final_reveal_sequence", [])),
        "local_risks": len(high_risks),
    }
    return "\n".join([
        "# AI Review Checklist",
        "",
        "Use this checklist when asking GPT/Claude or a human reviewer to inspect the imported draft.",
        "",
        "## Scope Snapshot",
        "",
        "```json",
        json.dumps(counts, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Public / Private Isolation",
        "",
        "- [ ] Public intro, setting, rules, opening script contain no role secrets.",
        "- [ ] Public cast profiles do not include private goals, alibis, hidden identity, culprit, method, or final truth.",
        "- [ ] Clue content is safe at its reveal phase and not safe earlier.",
        "- [ ] Role packet content is absent from public materials unless reveal_instruction explicitly makes it public.",
        "",
        "## Role Packets",
        "",
        "- [ ] Every packet belongs to the correct character.",
        "- [ ] phase_id matches when the packet should unlock.",
        "- [ ] visibility, after_reveal_visibility, recipients, and reveal_instruction match the source text.",
        "- [ ] keep_secret / reveal_only_when_challenged packets are not placed in public knowledge.",
        "",
        "## Clue Timing",
        "",
        "- [ ] Each clue has the correct reveal_phase.",
        "- [ ] Each clue has a matching reveal_rule.",
        "- [ ] reveal_rule announcement does not reveal extra truth.",
        "- [ ] clue order supports the intended player reasoning path.",
        "",
        "## Truth Logic",
        "",
        "- [ ] Every truth_node is accurate and source-grounded.",
        "- [ ] evidence_links actually support the linked truth node.",
        "- [ ] case_questions ask the right final questions.",
        "- [ ] imported placeholder links are replaced or explicitly approved.",
        "",
        "## Ending Consistency",
        "",
        "- [ ] final_reveal_sequence step order is correct.",
        "- [ ] code_word steps are present only when the source script requires them.",
        "- [ ] content_ref points to the intended truth/clue/asset.",
        "- [ ] final reveal does not skip any required truth.",
        "",
        "## Spoiler Safety",
        "",
        "- [ ] forbidden_spoilers cover culprit, method, hidden identity, motive, code words, and aliases.",
        "- [ ] allowed_after_phase / allowed_after_reveal_rule are not too early.",
        "- [ ] hint_rules do not allow truth nodes before they should be known.",
        "- [ ] review any locally detected high-risk item below.",
        "",
        "## Local High-Risk Items",
        "",
        format_risk_items(high_risks),
        "",
    ])


def build_high_risk_items_report(schema: dict[str, Any], validator_error_report: dict[str, Any], high_risks: list[dict[str, str]]) -> str:
    trace = schema.get("x_import_trace", {})
    confidence = trace.get("confidence", {})
    return "\n".join([
        "# High Risk Items",
        "",
        "This file is generated by local heuristics before any real AI review. Treat it as a triage queue, not a final judgment.",
        "",
        "## Confidence",
        "",
        "```json",
        json.dumps(confidence, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Validator",
        "",
        "```json",
        json.dumps(validator_error_report, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Risks",
        "",
        format_risk_items(high_risks),
        "",
    ])


def build_review_pack(schema: dict[str, Any], import_report: str, validator_error_report: dict[str, Any]) -> dict[str, str]:
    validation_errors = validator_error_report.get("errors", [])
    high_risks = detect_review_high_risk_items(schema, validation_errors)
    return {
        "review_prompt.md": build_review_prompt(schema, import_report, validator_error_report, high_risks),
        "review_checklist.md": build_review_checklist(schema, high_risks),
        "high_risk_items.md": build_high_risk_items_report(schema, validator_error_report, high_risks),
    }


def write_outputs(
    out_dir: Path,
    schema: dict[str, Any],
    import_report: str,
    gap_report: str,
    validator_error_report: dict[str, Any],
    review_pack: dict[str, str],
    force: bool,
    game_schema_v0_3: dict[str, Any] | None = None,
    game_validator_error_report: dict[str, Any] | None = None,
    game_author_questions_report: str | None = None,
    game_gap_report: str | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        "script.json": json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        "import_report.md": import_report,
        "schema_gap_report.md": gap_report,
        "validator_errors.json": json.dumps(validator_error_report, ensure_ascii=False, indent=2) + "\n",
    }
    targets.update(review_pack)
    if game_schema_v0_3 is not None:
        targets["game_schema_v0_3.json"] = json.dumps(game_schema_v0_3, ensure_ascii=False, indent=2) + "\n"
    if game_validator_error_report is not None:
        targets["game_schema_v0_3_validator_errors.json"] = json.dumps(game_validator_error_report, ensure_ascii=False, indent=2) + "\n"
    if game_author_questions_report is not None:
        targets["game_schema_v0_3_author_questions.md"] = game_author_questions_report
    if game_gap_report is not None:
        targets["game_schema_v0_3_report.md"] = game_gap_report
    for name, content in targets.items():
        path = out_dir / name
        if path.exists() and not force:
            raise FileExistsError(f"{path} exists; pass --force to overwrite")
        path.write_text(content, encoding="utf-8")


def import_text_script(source_path: Path, out_dir: Path, script_id: str, confirm: bool, force: bool) -> int:
    if source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Only .txt/.md/.markdown imports are supported in v0.1; PDF/DOCX parsing is intentionally not implemented.")
    text = source_path.read_text(encoding="utf-8-sig")
    chunks = split_chunks(text)
    candidates = build_candidates(chunks, text, source_path)
    schema = build_schema(candidates, script_id, source_path)
    game_schema = build_game_schema_v0_3(candidates, script_id, source_path)
    validation_errors = validate_script_schema(schema)
    game_validation_errors = validate_game_schema_v0_3(game_schema)
    confidence = score_confidence(candidates)
    missing_fields = detect_missing_fields(candidates, schema)
    privacy_warnings = check_private_public_isolation(schema)
    schema["x_import_trace"] = build_import_trace(
        source_path,
        candidates,
        confidence,
        missing_fields,
        privacy_warnings,
        validation_errors,
    )
    validation_errors = validate_script_schema(schema)
    schema["x_import_trace"]["validator"] = {"valid": not validation_errors, "error_count": len(validation_errors)}
    game_schema["x_import_trace"]["confidence"] = confidence
    game_schema["x_import_trace"]["validator"] = {
        "valid": not game_validation_errors,
        "error_count": len(game_validation_errors),
    }
    validator_error_report = build_validator_error_report(validation_errors)
    game_validator_error_report = build_validator_error_report(game_validation_errors)
    author_questions = game_schema.get("review", {}).get("author_questions", []) or []
    gaps = detect_gaps(
        candidates,
        schema,
        validation_errors,
        missing_fields,
        privacy_warnings,
        game_schema,
        game_validation_errors,
    )
    import_report = build_import_report(
        source_path,
        out_dir,
        chunks,
        candidates,
        validation_errors,
        confidence,
        missing_fields,
        privacy_warnings,
        game_validation_errors,
        author_questions,
    )
    gap_report = build_gap_report(gaps, schema, privacy_warnings, validation_errors)
    review_pack = build_review_pack(schema, import_report, validator_error_report)
    game_author_questions_report = build_author_questions_report(game_schema, game_validation_errors)
    game_gap_report = build_game_schema_gap_report(game_schema, game_validation_errors)

    if not confirm:
        print("Manual confirmation required. Re-run with --confirm-manual-review to write draft files.")
        print(f"Detected title: {candidates['title']}")
        print(f"Characters: {len(candidates['cast'])}; clues: {len(candidates['clues'])}; truth items: {len(candidates['truth_items'])}")
        print(f"Validator errors: {len(validation_errors)}")
        print(f"GameSchema v0.3 validator errors: {len(game_validation_errors)}")
        print(f"GameSchema v0.3 author questions: {len(author_questions)}")
        return 2

    write_outputs(
        out_dir,
        schema,
        import_report,
        gap_report,
        validator_error_report,
        review_pack,
        force=force,
        game_schema_v0_3=game_schema,
        game_validator_error_report=game_validator_error_report,
        game_author_questions_report=game_author_questions_report,
        game_gap_report=game_gap_report,
    )
    print(f"[PASS] wrote draft schema: {out_dir / 'script.json'}")
    print(f"[PASS] wrote import report: {out_dir / 'import_report.md'}")
    print(f"[PASS] wrote gap report: {out_dir / 'schema_gap_report.md'}")
    print(f"[PASS] wrote validator errors: {out_dir / 'validator_errors.json'}")
    print(f"[PASS] wrote review prompt: {out_dir / 'review_prompt.md'}")
    print(f"[PASS] wrote review checklist: {out_dir / 'review_checklist.md'}")
    print(f"[PASS] wrote high risk items: {out_dir / 'high_risk_items.md'}")
    print(f"[PASS] wrote GameSchema v0.3 draft: {out_dir / 'game_schema_v0_3.json'}")
    print(f"[PASS] wrote GameSchema v0.3 author questions: {out_dir / 'game_schema_v0_3_author_questions.md'}")
    if validation_errors or game_validation_errors:
        print("[WARN] validator errors remain; inspect schema_gap_report.md")
        return 1
    print("[PASS] draft validates as ScriptSchema v0.2.1 and GameSchema v0.3")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Semi-automatic .txt/.md to ScriptSchema v0.2.1 draft importer.")
    parser.add_argument("source", help="Local .txt/.md/.markdown script text")
    parser.add_argument("--out-dir", required=True, help="Output directory for script.json and reports")
    parser.add_argument("--script-id", default=None, help="Draft script id; defaults to source filename slug")
    parser.add_argument("--confirm-manual-review", action="store_true", help="Required to write draft output files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    out_dir = Path(args.out_dir).resolve()
    script_id = args.script_id or slugify(source_path.stem, "imported_script")
    return import_text_script(source_path, out_dir, script_id, args.confirm_manual_review, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
