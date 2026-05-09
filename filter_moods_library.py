"""情绪音频库质检与筛选脚本。

2026-04-22 变更说明:
- 新增可复用筛选流程：先筛选，再回补，再复筛。
- 筛选维度包含时长、可听度（RMS/活跃度）与可选文本匹配阈值。
- 支持 `--apply` 将不合格文件移动到 `_rejected` 并重写 index/attribution。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pygame

from mood_config import MOOD_PROFILES


DEFAULT_INDEX_PATH = "music/moods/index.json"
DEFAULT_ATTRIBUTION_PATH = "music/moods/attribution.csv"
DEFAULT_MOODS_ROOT = "music/moods"
DEFAULT_REJECTED_ROOT = "music/moods/_rejected"

DEFAULT_MIN_DURATION = 30.0
DEFAULT_MAX_DURATION = 180.0
DEFAULT_MIN_RMS = 120.0
DEFAULT_ACTIVE_AMP = 200.0
DEFAULT_MIN_ACTIVE_RATIO = 0.02
DEFAULT_HEAD_SECONDS = 5.0
DEFAULT_MIN_HEAD_RMS = 20.0
DEFAULT_MIN_TEXT_MATCH = 0.6

LICENSE_CC_BY = "cc_by"

GENERIC_QUERY_TOKENS: Set[str] = {
    "ambient",
    "ambience",
    "atmosphere",
    "atmospheric",
    "cinematic",
    "background",
    "underscore",
    "soundtrack",
    "texture",
    "drone",
    "pad",
    "music",
    "loop",
}


@dataclass
class AudioMetrics:
    duration_sec: float
    rms: float
    active_ratio: float
    head_rms: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="筛选 music/moods/index.json 中的音频质量")
    parser.add_argument("--index-path", default=DEFAULT_INDEX_PATH, help="索引文件路径")
    parser.add_argument("--attribution-path", default=DEFAULT_ATTRIBUTION_PATH, help="署名文件路径")
    parser.add_argument("--moods-root", default=DEFAULT_MOODS_ROOT, help="音频根目录")
    parser.add_argument("--rejected-root", default=DEFAULT_REJECTED_ROOT, help="剔除文件归档目录")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION, help="最小时长（秒）")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION, help="最大时长（秒）")
    parser.add_argument("--min-rms", type=float, default=DEFAULT_MIN_RMS, help="最小整体 RMS")
    parser.add_argument("--active-amp", type=float, default=DEFAULT_ACTIVE_AMP, help="活跃度振幅阈值")
    parser.add_argument(
        "--min-active-ratio",
        type=float,
        default=DEFAULT_MIN_ACTIVE_RATIO,
        help="最小活跃度占比（0-1）",
    )
    parser.add_argument("--head-seconds", type=float, default=DEFAULT_HEAD_SECONDS, help="开头检测秒数")
    parser.add_argument("--min-head-rms", type=float, default=DEFAULT_MIN_HEAD_RMS, help="开头最小 RMS")
    parser.add_argument(
        "--enforce-text-match",
        action="store_true",
        help="启用文本匹配阈值，不达标则剔除",
    )
    parser.add_argument(
        "--min-text-match",
        type=float,
        default=DEFAULT_MIN_TEXT_MATCH,
        help="文本匹配阈值（仅在 --enforce-text-match 时生效）",
    )
    parser.add_argument("--apply", action="store_true", help="应用筛选结果并重写索引")
    parser.add_argument("--report-limit", type=int, default=40, help="控制台展示剔除样例数")
    return parser.parse_args()


def classify_license(license_raw: str) -> str:
    text = license_raw.strip().lower()
    if "/licenses/by/" in text or text.endswith("by") or text == "attribution":
        return LICENSE_CC_BY
    return "other"


def tokenize(text: str) -> Set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def build_mood_terms(mood: str) -> Set[str]:
    profile = MOOD_PROFILES.get(mood, {})
    terms: Set[str] = set()

    match_terms = profile.get("match_terms")
    if isinstance(match_terms, list):
        for token in match_terms:
            for part in tokenize(str(token)):
                if len(part) >= 4:
                    terms.add(part)

    if not terms:
        search_terms = profile.get("search_terms")
        if isinstance(search_terms, list):
            for phrase in search_terms:
                for token in tokenize(str(phrase)):
                    if token in GENERIC_QUERY_TOKENS:
                        continue
                    if len(token) >= 4:
                        terms.add(token)

    terms.add(mood.lower())
    return terms


def compute_text_match_score(mood: str, query: str, filename: str) -> float:
    mood_terms = build_mood_terms(mood)
    if not mood_terms:
        return 0.0
    name_tokens = tokenize(filename)
    if not name_tokens:
        return 0.0

    mood_hits = len(mood_terms.intersection(name_tokens))
    query_tokens = {
        token for token in tokenize(query) if token not in GENERIC_QUERY_TOKENS and len(token) >= 4
    }
    query_hits = len(query_tokens.intersection(name_tokens))
    return mood_hits + query_hits * 0.5


def analyze_audio(path: Path, active_amp: float, head_seconds: float) -> AudioMetrics:
    sound = pygame.mixer.Sound(str(path))
    samples = pygame.sndarray.array(sound).astype(np.float64)
    if samples.ndim == 2:
        mono = samples.mean(axis=1)
    else:
        mono = samples
    duration = float(sound.get_length())
    if mono.size == 0:
        return AudioMetrics(duration_sec=duration, rms=0.0, active_ratio=0.0, head_rms=0.0)

    rms = float(np.sqrt(np.mean(np.square(mono))))
    active_ratio = float(np.mean(np.abs(mono) >= active_amp))

    mixer_init = pygame.mixer.get_init()
    sample_rate = mixer_init[0] if mixer_init else 44100
    head_count = min(len(mono), int(sample_rate * head_seconds))
    head = mono[:head_count]
    head_rms = float(np.sqrt(np.mean(np.square(head)))) if head.size else 0.0

    return AudioMetrics(
        duration_sec=duration,
        rms=rms,
        active_ratio=active_ratio,
        head_rms=head_rms,
    )


def write_attribution(records: List[Dict[str, object]], attribution_path: Path):
    rows = []
    for record in records:
        license_class = classify_license(str(record.get("license", "")))
        if license_class != LICENSE_CC_BY:
            continue
        username = str(record.get("username", "unknown"))
        source_url = str(record.get("source_url", ""))
        rows.append(
            {
                "sound_id": record.get("sound_id"),
                "mood": record.get("mood"),
                "filename": record.get("filename"),
                "username": username,
                "license": record.get("license"),
                "source_url": source_url,
                "credit_line": f"Sound by {username} via Freesound: {source_url}",
            }
        )

    attribution_path.parent.mkdir(parents=True, exist_ok=True)
    with attribution_path.open("w", encoding="utf-8", newline="") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=[
                "sound_id",
                "mood",
                "filename",
                "username",
                "license",
                "source_url",
                "credit_line",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    index_path = Path(args.index_path).resolve()
    attribution_path = Path(args.attribution_path).resolve()
    moods_root = Path(args.moods_root).resolve()
    rejected_root = Path(args.rejected_root).resolve()

    if not index_path.exists():
        print(f"未找到索引文件: {index_path}")
        return 1

    try:
        records = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"索引解析失败: {exc}")
        return 1
    if not isinstance(records, list):
        print("索引格式错误：期望 list")
        return 1

    pygame.mixer.quit()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

    kept: List[Dict[str, object]] = []
    rejected: List[tuple[Dict[str, object], List[str], Path]] = []
    reason_counter: Counter[str] = Counter()
    before_counter: Counter[str] = Counter()
    after_counter: Counter[str] = Counter()

    for record in records:
        mood = str(record.get("mood", "")).strip()
        filename = str(record.get("filename", "")).strip()
        query = str(record.get("query", "")).strip()
        before_counter[mood] += 1
        file_path = moods_root / mood / filename

        reasons: List[str] = []
        if not file_path.exists():
            reasons.append("missing_file")
        else:
            try:
                metrics = analyze_audio(
                    path=file_path,
                    active_amp=float(args.active_amp),
                    head_seconds=float(args.head_seconds),
                )
                if metrics.duration_sec < float(args.min_duration):
                    reasons.append(f"duration<{args.min_duration}")
                if metrics.duration_sec > float(args.max_duration):
                    reasons.append(f"duration>{args.max_duration}")
                if metrics.rms < float(args.min_rms):
                    reasons.append(f"rms<{args.min_rms}")
                if metrics.active_ratio < float(args.min_active_ratio):
                    reasons.append(f"active_ratio<{args.min_active_ratio}")
                if metrics.head_rms < float(args.min_head_rms):
                    reasons.append(f"head_rms<{args.min_head_rms}")
            except Exception as exc:  # noqa: BLE001
                reasons.append(f"decode_error:{exc}")

        if args.enforce_text_match:
            score = compute_text_match_score(mood=mood, query=query, filename=filename)
            if score < float(args.min_text_match):
                reasons.append(f"text_match<{args.min_text_match}")

        if reasons:
            rejected.append((record, reasons, file_path))
            for reason in reasons:
                reason_counter[reason] += 1
        else:
            kept.append(record)
            after_counter[mood] += 1

    print("\n========== FILTER REPORT ==========")
    print(f"总条目: {len(records)}")
    print(f"通过: {len(kept)}")
    print(f"剔除: {len(rejected)}")
    if reason_counter:
        print("剔除原因统计:")
        for reason, count in reason_counter.most_common():
            print(f"- {reason}: {count}")

    print("\n分类数量变化:")
    all_moods = sorted(set(list(before_counter.keys()) + list(MOOD_PROFILES.keys())))
    for mood in all_moods:
        before = before_counter.get(mood, 0)
        after = after_counter.get(mood, 0)
        if before == 0 and after == 0:
            continue
        diff = after - before
        print(f"- {mood}: {before} -> {after} ({diff:+d})")

    if rejected:
        print(f"\n剔除样例（最多 {args.report_limit} 条）:")
        for record, reasons, _ in rejected[: args.report_limit]:
            print(f"- [{record.get('mood')}] {record.get('filename')} | {', '.join(reasons)}")
    print("===================================\n")

    if not args.apply:
        return 2 if rejected else 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_root = rejected_root / timestamp

    # Windows 下 pygame 可能持有文件句柄，移动前先释放。
    pygame.mixer.quit()

    moved = 0
    move_failures: List[str] = []
    for record, _, file_path in rejected:
        mood = str(record.get("mood", "")).strip()
        filename = str(record.get("filename", "")).strip()
        if not filename:
            continue
        if not file_path.exists():
            continue
        target_dir = snapshot_root / mood
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        try:
            shutil.move(str(file_path), str(target_path))
            moved += 1
        except Exception as exc:  # noqa: BLE001
            move_failures.append(f"{file_path} -> {target_path}: {exc}")

    index_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    write_attribution(kept, attribution_path)
    print(f"已应用筛选: 更新索引 {index_path}")
    print(f"已更新署名: {attribution_path}")
    print(f"已移动文件: {moved} -> {snapshot_root}")
    if move_failures:
        print(f"未移动文件: {len(move_failures)}（权限受限，已仅从索引剔除）")
        for item in move_failures[:20]:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
