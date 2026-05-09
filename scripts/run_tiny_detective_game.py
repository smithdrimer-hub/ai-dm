"""Run the tiny GameSchema v0.1 detective demo in a simple CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from detective_game_engine import DetectiveGameEngine


DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "scripts" / "schema_examples" / "tiny_detective_case_v0_1.json"


def print_help() -> None:
    print("可用命令：")
    print("  /status")
    print("  /search <area_id>")
    print("  /show <clue_id>")
    print("  /ask <character_id> <question>")
    print("  /confront <character_id> <evidence_id>")
    print("  /accuse <suspect_id>")
    print("  /accuse <suspect_id> motive=<truth_id> method=<truth_id> evidence=<id,id> lies=<id,id>")
    print("  help")
    print("  quit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a GameSchema v0.1 detective CLI demo.")
    parser.add_argument("schema_path", nargs="?", default=str(DEFAULT_SCHEMA_PATH), help="Path to a GameSchema JSON file.")
    parser.add_argument("--llm", action="store_true", help="Use an OpenAI-compatible LLM actor for NPC replies.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schema_path = Path(args.schema_path)
    npc_actor = None
    if args.llm:
        from detective_llm_actor import OpenAINPCActor

        npc_actor = OpenAINPCActor.from_env()
    engine = DetectiveGameEngine(schema_path, npc_actor=npc_actor)
    case = engine.schema.get("public_case", {})
    info = engine.schema.get("game_info", {})

    print("=" * 50)
    print(f"单人 AI 推理游戏 Demo：{info.get('title', schema_path.stem)}")
    print(f"NPC 表演：{'LLM' if npc_actor else '规则模板'}")
    print("=" * 50)
    print(case.get("opening_text", ""))
    print(case.get("detective_briefing", ""))
    print()
    print_help()
    print()
    print(engine.get_status_text())

    while True:
        try:
            command = input("\n侦探> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出游戏。")
            break
        if not command:
            continue
        if command.lower() in {"quit", "exit", "/quit"}:
            print("退出游戏。")
            break
        if command.lower() in {"help", "/help", "?"}:
            print_help()
            continue
        print(engine.handle_command(command))


if __name__ == "__main__":
    main()
