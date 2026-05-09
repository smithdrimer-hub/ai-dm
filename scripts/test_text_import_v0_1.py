r"""Acceptance tests for the text/markdown ScriptSchema draft importer.

Run with:
    python -B .\scripts\test_text_import_v0_1.py

The tests use only stdlib asserts and never call a real model/API.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from import_text_script_v0_1 import (  # noqa: E402
    build_candidates,
    build_game_schema_v0_3,
    build_gap_report,
    build_import_report,
    build_import_trace,
    build_review_pack,
    build_schema,
    build_validator_error_report,
    check_private_public_isolation,
    detect_review_high_risk_items,
    detect_gaps,
    detect_missing_fields,
    import_text_script,
    score_confidence,
    split_chunks,
    write_outputs,
)
from generate_ai_review_pack import generate_review_pack  # noqa: E402
from game_schema_v0_3 import validate_game_schema_v0_3  # noqa: E402
from script_schema import validate_script_schema  # noqa: E402


TMP_ROOT = ROOT / ".acceptance_tmp" / f"text_import_v0_1_{os.getpid()}"
SAMPLES = ROOT / "scripts" / "import_samples"


def pass_msg(name: str) -> None:
    print(f"[PASS] {name}")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_import_sample(sample_name: str, script_id: str) -> tuple[Path, dict, str, str, dict]:
    out_dir = TMP_ROOT / script_id
    code = import_text_script(SAMPLES / sample_name, out_dir, script_id, confirm=True, force=True)
    assert code == 0, f"{sample_name} should validate, got exit code {code}"
    for filename in (
        "script.json",
        "game_schema_v0_3.json",
        "game_schema_v0_3_validator_errors.json",
        "game_schema_v0_3_author_questions.md",
        "game_schema_v0_3_report.md",
        "import_report.md",
        "schema_gap_report.md",
        "validator_errors.json",
        "review_prompt.md",
        "review_checklist.md",
        "high_risk_items.md",
    ):
        assert (out_dir / filename).exists(), f"{filename} missing for {sample_name}"
    schema = read_json(out_dir / "script.json")
    validator_report = read_json(out_dir / "validator_errors.json")
    game_schema = read_json(out_dir / "game_schema_v0_3.json")
    game_validator_report = read_json(out_dir / "game_schema_v0_3_validator_errors.json")
    import_report = (out_dir / "import_report.md").read_text(encoding="utf-8")
    gap_report = (out_dir / "schema_gap_report.md").read_text(encoding="utf-8")
    errors = validate_script_schema(schema)
    assert not errors, f"{sample_name} generated invalid schema: {errors}"
    assert validator_report["valid"] is True
    assert game_validator_report["valid"] is True
    assert game_schema["schema_version"] == "game_schema_v0.3"
    assert "x_import_trace" in schema, "source trace metadata missing"
    assert schema["x_import_trace"]["manual_review_required"] is True
    assert "## Confidence" in import_report
    assert "GameSchema v0.3 author questions" in import_report
    assert "## Source Trace" in import_report
    assert "## Missing Fields / Manual Review" in import_report
    review_prompt = (out_dir / "review_prompt.md").read_text(encoding="utf-8")
    review_checklist = (out_dir / "review_checklist.md").read_text(encoding="utf-8")
    high_risk = (out_dir / "high_risk_items.md").read_text(encoding="utf-8")
    assert "AI-Assisted Semantic Review Prompt" in review_prompt
    assert "public/private isolation" in review_prompt
    assert "Role Packets" in review_checklist
    assert "High Risk Items" in high_risk
    return out_dir, schema, import_report, gap_report, validator_report


def test_fixed_truth_import() -> None:
    out_dir, schema, import_report, gap_report, _ = run_import_sample("tiny_fixed_truth.md", "tiny_fixed_truth_test")
    assert schema["script_info"]["game_mode"] == "fixed_truth"
    assert len(schema["cast"]) == 3
    assert len(schema["clues"]) == 2
    assert len(schema["ending_rules"]["final_reveal_sequence"]) == 2
    assert "Author not detected" not in gap_report
    assert "overall" in import_report
    assert generate_review_pack(out_dir, force=True) == 0
    assert (out_dir / "review_prompt.md").exists()
    pass_msg("fixed truth text import")


def test_round_private_packets_import() -> None:
    _, schema, _, gap_report, _ = run_import_sample("round_private_packets.md", "round_private_packets_test")
    assert len(schema["role_packets"]) == len(schema["cast"])
    assert all(packet["visibility"] == "private" for packet in schema["role_packets"])
    assert "Private/secret sections detected; only intro private packets are drafted" in gap_report
    pass_msg("round private packets import")


def test_action_mechanism_import() -> None:
    _, schema, _, gap_report, _ = run_import_sample("action_mechanism.md", "action_mechanism_test")
    assert schema["action_rules"]["enabled"] is False
    assert "Action/mechanism sections detected but action_rules are not inferred" in gap_report
    risks = detect_review_high_risk_items(schema, [])
    assert any(risk["area"] == "import_gap" and risk["level"] == "HIGH" for risk in risks)
    pass_msg("action mechanism import gap reporting")


def test_private_public_isolation_warning() -> None:
    out_dir, schema, _, _, _ = run_import_sample("tiny_fixed_truth.md", "privacy_warning_test")
    leaked = json.loads(json.dumps(schema))
    leaked["public_materials"]["public_intro"] += " " + leaked["role_packets"][0]["content"]
    warnings = check_private_public_isolation(leaked)
    assert warnings, "private role packet duplicated in public text should warn"
    assert any("role_packets" in warning for warning in warnings)
    assert out_dir.exists()
    pass_msg("private public isolation warning")


def test_game_schema_v0_3_author_questions_for_thin_npcs() -> None:
    source_path = SAMPLES / "tiny_fixed_truth.md"
    text = source_path.read_text(encoding="utf-8-sig")
    candidates = build_candidates(split_chunks(text), text, source_path)
    game_schema = build_game_schema_v0_3(candidates, "thin_npc_game_test", source_path)
    errors = validate_game_schema_v0_3(game_schema)
    questions = game_schema["review"]["author_questions"]

    assert not errors, f"generated GameSchema v0.3 should validate with author questions: {errors}"
    assert questions, "thin imported NPCs should produce author questions"
    question_text = "\n".join(item["question"] for item in questions)
    for forbidden in ("schema", "json", "action_profile", "truth_id", "public_profile", "private_profile"):
        assert forbidden not in question_text.casefold(), f"author question leaked technical word {forbidden}"
    assert any("怎么说话" in item["question"] or "侦探追问" in item["question"] for item in questions)
    pass_msg("GameSchema v0.3 import author questions for thin NPCs")


def test_game_schema_v0_3_no_author_questions_for_complete_npcs() -> None:
    source_path = TMP_ROOT / "complete_game_source.md"
    source_path.write_text(
        "\n".join(
            [
                "# Complete NPC Case",
                "",
                "Author: Demo Author",
                "Setting: A locked observatory after a gala.",
                "",
                "## Public Intro",
                "The director collapses during the gala, and the detective must inspect the observatory.",
                "",
                "## Rules",
                "Search, ask, confront, and accuse.",
                "",
                "## Cast",
                "- Iris: Observatory treasurer and long-time rival of the director. | Secret: Iris hid a forged invoice that gives her a strong motive. | Goal: Keep suspicion on the visiting donor while protecting the invoice. | Attitude: Polite but tense, answering carefully when cornered. | Voice: Speaks in short, precise sentences and becomes colder under pressure.",
                "- Jonah: Visiting donor with a public argument against the director. | Secret: Jonah saw Iris near the archive door but fears admitting he was nearby. | Goal: Clear his name without revealing why he entered the archive. | Attitude: Defensive, impatient, and quick to interrupt. | Voice: Blunt and restless, but cooperative when shown evidence.",
                "",
                "## Clues",
                "- Forged Invoice: The invoice connects Iris to missing observatory funds.",
                "- Archive Dust: Fresh dust on Iris's cuff places her near the locked archive.",
                "",
                "## Truth",
                "- Iris killed the director to hide the missing funds.",
                "- The forged invoice is the motive and the archive dust confirms access.",
            ]
        ),
        encoding="utf-8",
    )
    text = source_path.read_text(encoding="utf-8-sig")
    candidates = build_candidates(split_chunks(text), text, source_path)
    game_schema = build_game_schema_v0_3(candidates, "complete_npc_game_test", source_path)
    errors = validate_game_schema_v0_3(game_schema)

    assert not errors, f"complete generated GameSchema v0.3 should validate: {errors}"
    assert game_schema["review"]["author_questions"] == [], "complete NPC setup should not ask author questions"
    pass_msg("GameSchema v0.3 import skips author questions for complete NPCs")


def test_validator_failure_still_writes_draft_and_errors() -> None:
    source_path = SAMPLES / "tiny_fixed_truth.md"
    out_dir = TMP_ROOT / "validator_failure_preserved"
    text = source_path.read_text(encoding="utf-8-sig")
    chunks = split_chunks(text)
    candidates = build_candidates(chunks, text, source_path)
    schema = build_schema(candidates, "broken_validator_test", source_path)
    schema["script_info"]["game_mode"] = "not_a_mode"
    validation_errors = validate_script_schema(schema)
    assert validation_errors, "test setup should create validator errors"
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
    gaps = detect_gaps(candidates, schema, validation_errors, missing_fields, privacy_warnings)
    import_report = build_import_report(source_path, out_dir, chunks, candidates, validation_errors, confidence, missing_fields, privacy_warnings)
    gap_report = build_gap_report(gaps, schema, privacy_warnings, validation_errors)
    validator_report = build_validator_error_report(validation_errors)
    review_pack = build_review_pack(schema, import_report, validator_report)
    write_outputs(out_dir, schema, import_report, gap_report, validator_report, review_pack, force=True)
    assert (out_dir / "script.json").exists(), "invalid draft should still be written"
    assert (out_dir / "review_prompt.md").exists(), "review prompt should still be written"
    report = read_json(out_dir / "validator_errors.json")
    assert report["valid"] is False
    assert report["error_count"] == len(validation_errors)
    assert "not_a_mode" in "\n".join(report["errors"])
    pass_msg("validator failure preserves draft and error report")


def main() -> None:
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        test_fixed_truth_import()
        test_round_private_packets_import()
        test_action_mechanism_import()
        test_private_public_isolation_warning()
        test_game_schema_v0_3_author_questions_for_thin_npcs()
        test_game_schema_v0_3_no_author_questions_for_complete_npcs()
        test_validator_failure_still_writes_draft_and_errors()
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    print("[PASS] text import v0.1 auditability test suite")


if __name__ == "__main__":
    main()
