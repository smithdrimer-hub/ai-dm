"""从 Freesound 按情绪分类检索并下载音效预览（HQ MP3）。

2026-04-22 变更说明:
- 修复缺口统计在“无候选/无可选池”分支下漏记的问题。
- 检索排序改为按相关度优先，并加入 tags 字段参与匹配。
- 新增最小文本匹配阈值，提升情绪匹配精度（可通过参数调节）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from mood_config import MOOD_PROFILES


API_SEARCH_URL = "https://freesound.org/apiv2/search/"
DEFAULT_PER_MOOD = 10
DEFAULT_MIN_DURATION = 20
DEFAULT_MAX_DURATION = 180
DEFAULT_RATE_LIMIT = 45
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_LIMIT = 6
MAX_RETRIES = 3
BACKOFF_SECONDS = 1.5
DEFAULT_MIN_TEXT_MATCH = 0.08

LICENSE_CC0 = "cc0"
LICENSE_CC_BY = "cc_by"
LICENSE_NON_COMMERCIAL = "non_commercial"
LICENSE_OTHER = "other"

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


@dataclass(frozen=True)
class Candidate:
    sound_id: int
    name: str
    mood: str
    query: str
    duration_sec: float
    license_raw: str
    license_class: str
    username: str
    source_url: str
    preview_url: str
    tags: List[str]
    downloads: int
    rating: float
    text_match_score: float

    @property
    def score(self) -> float:
        # 文本匹配分在排序中占较高权重，用于减轻“高下载但情绪不贴合”的误命中。
        return self.downloads + self.rating * 50.0 + self.text_match_score * 250.0


@dataclass
class MoodRunStats:
    mood: str
    target_count: int
    existing_count: int = 0
    api_hits: int = 0
    selected_cc0: int = 0
    selected_cc_by: int = 0
    selected_total: int = 0
    missing_count: int = 0
    failures: List[str] | None = None

    def __post_init__(self):
        if self.failures is None:
            self.failures = []

    @property
    def cc0_ratio(self) -> float:
        if self.selected_total == 0:
            return 0.0
        return self.selected_cc0 / self.selected_total

    @property
    def supplemented(self) -> int:
        return self.selected_cc_by


class RequestThrottle:
    """简单请求节流器，按每分钟请求数限速。"""

    def __init__(self, requests_per_minute: int):
        self._min_interval = 60.0 / max(requests_per_minute, 1)
        self._last_request_at = 0.0

    def wait(self):
        now = time.monotonic()
        delta = now - self._last_request_at
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last_request_at = time.monotonic()


class FreesoundMoodDownloader:
    def __init__(
        self,
        api_key: str,
        output_root: Path,
        per_mood: int = DEFAULT_PER_MOOD,
        min_duration: int = DEFAULT_MIN_DURATION,
        max_duration: int = DEFAULT_MAX_DURATION,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        dry_run: bool = False,
        resume: bool = False,
        allow_cc_by_fallback: bool = False,
        min_text_match: float = DEFAULT_MIN_TEXT_MATCH,
        seed: int = 42,
    ):
        self.api_key = api_key
        self.output_root = output_root
        self.per_mood = per_mood
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.dry_run = dry_run
        self.resume = resume
        self.allow_cc_by_fallback = allow_cc_by_fallback
        self.min_text_match = max(0.0, min_text_match)
        self.session = requests.Session()
        self.throttle = RequestThrottle(rate_limit)
        self.random = random.Random(seed)

        self.moods_root = self.output_root / "moods"
        self.index_path = self.moods_root / "index.json"
        self.attribution_path = self.moods_root / "attribution.csv"

        self.index_records: List[Dict[str, object]] = []
        self.records_by_mood: Dict[str, List[Dict[str, object]]] = {}
        self.stats: Dict[str, MoodRunStats] = {}
        self.shortage: Dict[str, int] = {}
        self._mood_terms_cache: Dict[str, Set[str]] = {}

    def run(self) -> int:
        self._prepare_dirs()
        self._load_existing_index()

        final_records = [] if not self.resume else list(self.index_records)

        for mood in MOOD_PROFILES:
            mood_stats = MoodRunStats(mood=mood, target_count=self.per_mood)
            self.stats[mood] = mood_stats

            existing_records = self.records_by_mood.get(mood, [])
            existing_valid = []
            for record in existing_records:
                if not self._resolve_record_path(record).exists():
                    continue
                license_class = classify_license(str(record.get("license", "")))
                if license_class == LICENSE_CC0:
                    existing_valid.append(record)
                elif self.allow_cc_by_fallback and license_class == LICENSE_CC_BY:
                    existing_valid.append(record)
            mood_stats.existing_count = len(existing_valid)

            if self.resume and mood_stats.existing_count >= self.per_mood:
                mood_stats.selected_total = mood_stats.existing_count
                for record in existing_valid[: self.per_mood]:
                    license_class = classify_license(str(record.get("license", "")))
                    if license_class == LICENSE_CC0:
                        mood_stats.selected_cc0 += 1
                    elif license_class == LICENSE_CC_BY:
                        mood_stats.selected_cc_by += 1
                print(f"[{mood}] 已满足 {self.per_mood} 条（resume 跳过）")
                continue

            exclude_ids = set()
            for record in existing_valid:
                try:
                    exclude_ids.add(int(record.get("sound_id")))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
            exclude_ids.update(self._collect_disk_sound_ids(mood))
            needed = self.per_mood - mood_stats.existing_count

            candidates = self._fetch_candidates_for_mood(mood=mood, exclude_ids=exclude_ids)
            mood_stats.api_hits = len(candidates)

            if not candidates:
                mood_stats.failures.append("未获取到任何候选")
                print(f"[{mood}] 未获取到候选音频")
                mood_stats.selected_total = mood_stats.existing_count
                mood_stats.missing_count = max(0, self.per_mood - mood_stats.selected_total)
                if mood_stats.missing_count > 0:
                    self.shortage[mood] = mood_stats.missing_count
                continue

            selection_pool = self._build_selection_pool(candidates)
            if not selection_pool:
                mood_stats.failures.append("候选均不符合许可/匹配阈值策略")
                policy = "CC0 / CC BY" if self.allow_cc_by_fallback else "仅 CC0"
                print(f"[{mood}] 候选均不符合许可策略（{policy}，min_text_match={self.min_text_match}）")
                mood_stats.selected_total = mood_stats.existing_count
                mood_stats.missing_count = max(0, self.per_mood - mood_stats.selected_total)
                if mood_stats.missing_count > 0:
                    self.shortage[mood] = mood_stats.missing_count
                continue

            mood_new_records = []
            consumed_ids = set(exclude_ids)
            existing_ranks = [normalize_rank(item.get("filename", "")) for item in existing_valid]
            next_rank = max(existing_ranks, default=0) + 1

            for candidate in selection_pool:
                if needed <= 0:
                    break
                if candidate.sound_id in consumed_ids:
                    continue

                filename = self._build_filename(rank=next_rank, candidate=candidate)
                mood_dir = self.moods_root / mood
                target_path = mood_dir / filename
                downloaded_at = utc_now_iso()

                success = True
                if not self.dry_run:
                    try:
                        self._download_preview(candidate.preview_url, target_path)
                    except Exception as exc:  # noqa: BLE001
                        success = False
                        mood_stats.failures.append(f"{candidate.sound_id}: {exc}")

                if not success:
                    continue

                record = {
                    "sound_id": candidate.sound_id,
                    "mood": mood,
                    "filename": filename,
                    "duration_sec": round(candidate.duration_sec, 3),
                    "license": candidate.license_raw,
                    "username": candidate.username,
                    "source_url": candidate.source_url,
                    "preview_url": candidate.preview_url,
                    "query": candidate.query,
                    "downloaded_at": downloaded_at,
                }
                mood_new_records.append(record)
                consumed_ids.add(candidate.sound_id)
                needed -= 1
                next_rank += 1

                if candidate.license_class == LICENSE_CC0:
                    mood_stats.selected_cc0 += 1
                elif candidate.license_class == LICENSE_CC_BY:
                    mood_stats.selected_cc_by += 1

            mood_stats.selected_total = mood_stats.existing_count + len(mood_new_records)
            mood_stats.missing_count = max(0, self.per_mood - mood_stats.selected_total)
            if mood_stats.missing_count > 0:
                self.shortage[mood] = mood_stats.missing_count

            if self.dry_run:
                print(
                    f"[{mood}] dry-run: 命中 {mood_stats.api_hits}，计划新增 {len(mood_new_records)}，"
                    f"目标 {self.per_mood}，缺口 {mood_stats.missing_count}"
                )
                continue

            final_records.extend(mood_new_records)

        if self.dry_run:
            self._print_report(dry_run=True)
            if self.shortage:
                self._print_shortage()
                return 2
            return 0

        final_records = self._normalize_and_sort_records(final_records)
        self._write_index(final_records)
        self._write_attribution(final_records)
        self._print_report(dry_run=False)
        if self.shortage:
            self._print_shortage()
            return 2
        return 0

    def _prepare_dirs(self):
        if self.dry_run:
            return
        self.moods_root.mkdir(parents=True, exist_ok=True)
        for mood in MOOD_PROFILES:
            (self.moods_root / mood).mkdir(parents=True, exist_ok=True)

    def _load_existing_index(self):
        if not self.index_path.exists():
            return
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self.index_records = data
        except json.JSONDecodeError:
            self.index_records = []
        grouped: Dict[str, List[Dict[str, object]]] = {}
        for item in self.index_records:
            mood = str(item.get("mood", "")).strip()
            if not mood:
                continue
            grouped.setdefault(mood, []).append(item)
        self.records_by_mood = grouped

    def _fetch_candidates_for_mood(self, mood: str, exclude_ids: set[int]) -> List[Candidate]:
        terms = MOOD_PROFILES[mood]["search_terms"]
        desired_pool = max(self.per_mood * 6, 60)
        collected: Dict[int, Candidate] = {}

        for term in terms:
            for page in range(1, MAX_PAGE_LIMIT + 1):
                try:
                    payload = self._search(term=term, page=page)
                except RuntimeError as exc:
                    # Freesound 在翻到不存在的页码时会返回 404，这里按“该词分页结束”处理。
                    if "404" in str(exc) and page > 1:
                        break
                    raise
                results = payload.get("results") or []
                if not isinstance(results, list) or not results:
                    break

                for raw in results:
                    candidate = self._to_candidate(raw=raw, mood=mood, query=term)
                    if candidate is None:
                        continue
                    if candidate.sound_id in exclude_ids:
                        continue
                    if candidate.sound_id in collected:
                        continue
                    collected[candidate.sound_id] = candidate

                if len(collected) >= desired_pool:
                    break
                if len(results) < DEFAULT_PAGE_SIZE:
                    break

            if len(collected) >= desired_pool:
                break

        candidates = list(collected.values())
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates

    def _search(self, term: str, page: int) -> Dict[str, object]:
        duration_filter = (
            f"duration:[{self.min_duration} TO *] "
            f"AND duration:[* TO {self.max_duration}]"
        )
        params = {
            "token": self.api_key,
            "query": term,
            "page": page,
            "page_size": DEFAULT_PAGE_SIZE,
            "filter": duration_filter,
            "fields": (
                "id,name,license,username,duration,url,previews,"
                "num_downloads,avg_rating,tags"
            ),
        }
        return self._request_json(API_SEARCH_URL, params=params)

    def _request_json(self, url: str, params: Dict[str, object]) -> Dict[str, object]:
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                self.throttle.wait()
                response = self.session.get(url, params=params, timeout=20)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:120]}")
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("API 返回格式异常")
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= MAX_RETRIES - 1:
                    break
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
        raise RuntimeError(f"请求 Freesound 失败: {last_error}")

    def _to_candidate(self, raw: Dict[str, object], mood: str, query: str) -> Optional[Candidate]:
        try:
            sound_id = int(raw.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

        name = str(raw.get("name") or "").strip() or f"sound_{sound_id}"
        license_raw = str(raw.get("license") or "").strip()
        license_class = classify_license(license_raw)
        if license_class in {LICENSE_NON_COMMERCIAL, LICENSE_OTHER}:
            return None

        duration = float(raw.get("duration") or 0.0)
        if duration < self.min_duration or duration > self.max_duration:
            return None

        previews = raw.get("previews")
        preview_url = ""
        if isinstance(previews, dict):
            preview_url = str(previews.get("preview-hq-mp3") or "").strip()
        if not preview_url:
            preview_url = str(raw.get("preview-hq-mp3") or "").strip()
        if not preview_url:
            return None

        source_url = str(raw.get("url") or "").strip()
        username = str(raw.get("username") or "").strip() or "unknown"
        downloads = int(raw.get("num_downloads") or 0)
        rating = float(raw.get("avg_rating") or 0.0)
        tags_raw = raw.get("tags")
        tags: List[str] = []
        if isinstance(tags_raw, list):
            for tag in tags_raw:
                text = str(tag).strip()
                if text:
                    tags.append(text)
        text_match_score = self._compute_text_match_score(
            mood=mood,
            query=query,
            name=name,
            tags=tags,
        )

        return Candidate(
            sound_id=sound_id,
            name=name,
            mood=mood,
            query=query,
            duration_sec=duration,
            license_raw=license_raw,
            license_class=license_class,
            username=username,
            source_url=source_url,
            preview_url=preview_url,
            tags=tags,
            downloads=downloads,
            rating=rating,
            text_match_score=text_match_score,
        )

    def _build_selection_pool(self, candidates: Iterable[Candidate]) -> List[Candidate]:
        cc0 = [
            item
            for item in candidates
            if item.license_class == LICENSE_CC0 and item.text_match_score >= self.min_text_match
        ]
        cc_by = [
            item
            for item in candidates
            if item.license_class == LICENSE_CC_BY and item.text_match_score >= self.min_text_match
        ]
        cc0.sort(key=lambda item: (item.text_match_score, item.score), reverse=True)
        cc_by.sort(key=lambda item: (item.text_match_score, item.score), reverse=True)
        if self.allow_cc_by_fallback:
            return cc0 + cc_by
        return cc0

    def _compute_text_match_score(self, mood: str, query: str, name: str, tags: List[str]) -> float:
        target_terms = self._get_mood_terms(mood)
        if not target_terms:
            return 0.0

        text_tokens = self._tokenize(f"{name} {' '.join(tags)}")
        if not text_tokens:
            return 0.0

        mood_hits = len(target_terms.intersection(text_tokens))
        query_tokens = {
            token
            for token in self._tokenize(query)
            if token not in GENERIC_QUERY_TOKENS and len(token) >= 4
        }
        query_hits = len(query_tokens.intersection(text_tokens))
        return mood_hits + query_hits * 0.5

    def _get_mood_terms(self, mood: str) -> Set[str]:
        cached = self._mood_terms_cache.get(mood)
        if cached is not None:
            return cached

        profile = MOOD_PROFILES.get(mood, {})
        terms: Set[str] = set()

        custom_terms = profile.get("match_terms")
        if isinstance(custom_terms, list):
            for token in custom_terms:
                for parsed in self._tokenize(str(token)):
                    if len(parsed) >= 4:
                        terms.add(parsed)

        if not terms:
            search_terms = profile.get("search_terms")
            if isinstance(search_terms, list):
                for phrase in search_terms:
                    for token in self._tokenize(str(phrase)):
                        if token in GENERIC_QUERY_TOKENS:
                            continue
                        if len(token) >= 4:
                            terms.add(token)

        terms.add(mood.lower())
        self._mood_terms_cache[mood] = terms
        return terms

    def _tokenize(self, text: str) -> Set[str]:
        return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}

    def _download_preview(self, preview_url: str, target_path: Path):
        target_path.parent.mkdir(parents=True, exist_ok=True)

        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                self.throttle.wait()
                with self.session.get(preview_url, stream=True, timeout=30) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise RuntimeError(f"下载失败 HTTP {response.status_code}")
                    response.raise_for_status()
                    with target_path.open("wb") as file_handle:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                file_handle.write(chunk)
                if target_path.stat().st_size <= 0:
                    raise RuntimeError("下载文件为空")
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if target_path.exists():
                    target_path.unlink(missing_ok=True)
                if attempt >= MAX_RETRIES - 1:
                    break
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))
        raise RuntimeError(f"下载失败: {last_error}")

    def _build_filename(self, rank: int, candidate: Candidate) -> str:
        slug = slugify(candidate.name)
        return f"{rank:02d}_{candidate.sound_id}_{slug}.mp3"

    def _resolve_record_path(self, record: Dict[str, object]) -> Path:
        mood = str(record.get("mood", "")).strip()
        filename = str(record.get("filename", "")).strip()
        return self.moods_root / mood / filename

    def _collect_disk_sound_ids(self, mood: str) -> set[int]:
        mood_dir = self.moods_root / mood
        if not mood_dir.exists():
            return set()
        sound_ids: set[int] = set()
        for path in mood_dir.glob("*.mp3"):
            match = re.match(r"^\d+_(\d+)_", path.name)
            if not match:
                continue
            try:
                sound_ids.add(int(match.group(1)))
            except ValueError:
                continue
        return sound_ids

    def _normalize_and_sort_records(self, records: List[Dict[str, object]]) -> List[Dict[str, object]]:
        dedup: Dict[tuple[str, int], Dict[str, object]] = {}
        for record in records:
            mood = str(record.get("mood", "")).strip()
            try:
                sound_id = int(record.get("sound_id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            dedup[(mood, sound_id)] = record

        grouped: Dict[str, List[Dict[str, object]]] = {}
        for record in dedup.values():
            mood = str(record["mood"])
            grouped.setdefault(mood, []).append(record)

        normalized: List[Dict[str, object]] = []
        for mood in sorted(grouped.keys()):
            group = grouped[mood]
            group.sort(key=lambda item: (
                normalize_rank(item.get("filename", "")),
                int(item.get("sound_id", 0)),
            ))
            for item in group:
                normalized.append(item)
        return normalized

    def _write_index(self, records: List[Dict[str, object]]):
        self.moods_root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_attribution(self, records: List[Dict[str, object]]):
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

        self.moods_root.mkdir(parents=True, exist_ok=True)
        with self.attribution_path.open("w", encoding="utf-8", newline="") as csvfile:
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

    def _print_report(self, dry_run: bool):
        mode = "DRY-RUN" if dry_run else "RUN"
        print(f"\n========== {mode} REPORT ==========")

        for mood, stats in self.stats.items():
            ratio = f"{stats.cc0_ratio * 100:.1f}%"
            supplement_text = f"CC BY 补位 {stats.supplemented}"
            fail_text = "；".join(stats.failures[:3]) if stats.failures else "无"
            print(
                f"[{mood}] 命中={stats.api_hits} 现有={stats.existing_count} "
                f"总量={stats.selected_total} 缺口={stats.missing_count} CC0占比={ratio} "
                f"{supplement_text} 失败={fail_text}"
            )

        if not dry_run:
            print(f"\n索引文件：{self.index_path}")
            print(f"署名清单：{self.attribution_path}")
        print("===================================\n")

    def _print_shortage(self):
        print("\n========== CC0 缺口清单 ==========")
        for mood in sorted(self.shortage.keys()):
            print(f"- {mood}: 缺 {self.shortage[mood]} 条")
        print("===================================\n")


def classify_license(license_raw: str) -> str:
    text = license_raw.strip().lower()
    if not text:
        return LICENSE_OTHER
    if "publicdomain/zero" in text or "cc0" in text:
        return LICENSE_CC0
    if "by-nc" in text or "noncommercial" in text:
        return LICENSE_NON_COMMERCIAL
    if "/licenses/by/" in text or "attribution" == text or text.endswith("by"):
        return LICENSE_CC_BY
    return LICENSE_OTHER


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if not lowered:
        lowered = "sound"
    return lowered[:48]


def normalize_rank(filename: object) -> int:
    text = str(filename)
    match = re.match(r"^(\d{2})_", text)
    if not match:
        return 9999
    return int(match.group(1))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 Freesound 下载剧本杀情绪音效（预览 HQ MP3）",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅检索和报告，不下载文件")
    parser.add_argument("--resume", action="store_true", help="从 index.json 断点续抓")
    parser.add_argument(
        "--allow-cc-by-fallback",
        action="store_true",
        help="允许 CC BY 补位（默认关闭，仅下载 CC0）",
    )
    parser.add_argument("--per-mood", type=int, default=DEFAULT_PER_MOOD, help="每类目标数量")
    parser.add_argument("--min-duration", type=int, default=DEFAULT_MIN_DURATION, help="最小时长（秒）")
    parser.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION, help="最大时长（秒）")
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=DEFAULT_RATE_LIMIT,
        help="请求限速（每分钟请求数，默认 45）",
    )
    parser.add_argument(
        "--output-dir",
        default="music",
        help="输出根目录（默认 music）",
    )
    parser.add_argument(
        "--min-text-match",
        type=float,
        default=DEFAULT_MIN_TEXT_MATCH,
        help="最小文本匹配分（默认 0.08，越高越严格）",
    )
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    return parser.parse_args()


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    args = parse_args()
    api_key = os.getenv("FREESOUND_API_KEY", "").strip()
    if not api_key:
        print("未检测到 FREESOUND_API_KEY，请先在 .env 中配置。")
        return 1

    output_root = Path(args.output_dir).resolve()

    downloader = FreesoundMoodDownloader(
        api_key=api_key,
        output_root=output_root,
        per_mood=args.per_mood,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        rate_limit=args.rate_limit,
        dry_run=args.dry_run,
        resume=args.resume,
        allow_cc_by_fallback=args.allow_cc_by_fallback,
        min_text_match=args.min_text_match,
        seed=args.seed,
    )
    return downloader.run()


if __name__ == "__main__":
    raise SystemExit(main())
