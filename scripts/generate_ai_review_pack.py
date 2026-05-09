r"""Generate an AI-assisted semantic review pack for an imported draft.

Run with:
    python -B .\scripts\generate_ai_review_pack.py .\scripts\import_outputs\tiny_fixed_truth --force

This does not call an API. It prepares review_prompt.md, review_checklist.md,
and high_risk_items.md so a human can paste them into GPT/Claude.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from import_text_script_v0_1 import build_review_pack  # noqa: E402


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def generate_review_pack(import_dir: Path, force: bool) -> int:
    script_path = import_dir / "script.json"
    report_path = import_dir / "import_report.md"
    validator_path = import_dir / "validator_errors.json"
    required = [script_path, report_path, validator_path]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required import artifacts in {import_dir}: {', '.join(missing)}")

    schema = read_json(script_path)
    import_report = report_path.read_text(encoding="utf-8")
    validator_report = read_json(validator_path)
    review_pack = build_review_pack(schema, import_report, validator_report)
    for filename, content in review_pack.items():
        path = import_dir / filename
        if path.exists() and not force:
            raise FileExistsError(f"{path} exists; pass --force to overwrite")
        path.write_text(content, encoding="utf-8")
        print(f"[PASS] wrote {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate AI review prompt/checklist files for an imported ScriptSchema draft.")
    parser.add_argument("import_dir", help="Directory containing script.json, import_report.md, validator_errors.json")
    parser.add_argument("--force", action="store_true", help="Overwrite existing review files")
    args = parser.parse_args()
    return generate_review_pack(Path(args.import_dir).resolve(), force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())
