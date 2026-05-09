
"""Download and curate AI-DM SFX library (CC0-only, keyword-level pipeline).

2026-04-23 v2 note:
- Migrated to category->keyword bucket loop with keyword-level target.
- Added pre-download keyword audit, alias fallback, and noisy keyword filters.
- Resume mode now caps legacy records to target-per-keyword for stable acceptance.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import os
import random
import re
import shutil
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pygame
import requests

from sfx_config import (
    ALLOWED_AUDIO_EXTENSIONS,
    AUDIT_LOW_SUPPLY_THRESHOLD,
    AUDIT_NOISY_THRESHOLD,
    DEFAULT_CANDIDATE_BUFFER_MULTIPLIER,
    DEFAULT_MAX_ATTEMPTS_PER_KEYWORD,
    DEFAULT_MAX_AUTHOR_PER_KEYWORD,
    DEFAULT_MAX_CANDIDATES_PER_KEYWORD,
    DEFAULT_MAX_DURATION_SEC,
    DEFAULT_MAX_PAGE_LIMIT,
    DEFAULT_MAX_PER_QUERY,
    DEFAULT_MIN_DURATION_SEC,
    DEFAULT_PAGE_SIZE,
    DEFAULT_RANDOM_SEED,
    DEFAULT_RATE_LIMIT,
    DEFAULT_TARGET_PER_KEYWORD,
    KEYWORD_AUDIT_CSV_FILENAME,
    KEYWORD_AUDIT_JSON_FILENAME,
    LICENSE_MANIFEST_FILENAME,
    MAX_CLIPPING_RATIO,
    METADATA_FILENAME,
    MIN_VALID_RMS_DBFS,
    MUSIC_LIKE_TOKENS,
    RECOMMENDED_GAIN_MAX_DB,
    RECOMMENDED_GAIN_MIN_DB,
    REJECTED_FILENAME,
    RMS_TARGET_DBFS,
    SFX_BUNDLE_DIR,
    SFX_CATEGORY_KEYWORDS,
    SFX_KEYWORD_ALIASES,
    SFX_KEYWORD_NEGATIVE_TOKENS,
    SFX_LIBRARY_DIR,
    SFX_STYLE_BLOCK_TOKENS,
    SUMMARY_FILENAME,
)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


API_SEARCH_URL = "https://freesound.org/apiv2/search/"
MAX_RETRIES = 3
BACKOFF_SECONDS = 1.5
LICENSE_CC0 = "cc0"

GENERIC_KEYWORD_TOKENS = {
    "background",
    "cinematic",
    "low",
    "short",
    "soft",
    "ui",
    "warm",
}


@dataclass(frozen=True)
class Candidate:
    sound_id: int
    category: str
    keyword_bucket: str
    query_used: str
    name: str
    duration_sec: float
    license_raw: str
    author: str
    source_url: str
    preview_url: str
    tags: List[str]
    downloads: int
    rating: float
    keyword_match_score: float

    @property
    def score(self) -> float:
        return self.keyword_match_score * 100.0 + self.downloads + self.rating * 50.0


@dataclass(frozen=True)
class AudioMetrics:
    duration_sec: float
    peak_db: float
    rms_db: float
    clipping_ratio: float


class RequestThrottle:
    def __init__(self, requests_per_minute: int):
        self._min_interval = 60.0 / max(1, requests_per_minute)
        self._last = 0.0

    def wait(self):
        now = time.monotonic()
        delta = now - self._last
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last = time.monotonic()


def ensure_mixer_initialized() -> bool:
    """Initialize pygame mixer, fallback to dummy audio driver when needed."""
    if pygame.mixer.get_init() is not None:
        return True
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        return True
    except Exception:
        pass

    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        return True
    except Exception:
        return False


class SFXLibraryDownloader:
    def __init__(
        self,
        api_key: str,
        output_dir: Path,
        target_per_keyword: int = DEFAULT_TARGET_PER_KEYWORD,
        min_duration: float = DEFAULT_MIN_DURATION_SEC,
        max_duration: float = DEFAULT_MAX_DURATION_SEC,
        max_page_limit: int = DEFAULT_MAX_PAGE_LIMIT,
        max_per_query: int = DEFAULT_MAX_PER_QUERY,
        max_candidates_per_keyword: int = DEFAULT_MAX_CANDIDATES_PER_KEYWORD,
        candidate_buffer_multiplier: int = DEFAULT_CANDIDATE_BUFFER_MULTIPLIER,
        max_attempts_per_keyword: int = DEFAULT_MAX_ATTEMPTS_PER_KEYWORD,
        max_author_per_keyword: int = DEFAULT_MAX_AUTHOR_PER_KEYWORD,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        dry_run: bool = False,
        audit_only: bool = False,
        resume: bool = False,
        keyword_scope: Optional[Set[str]] = None,
        seed: int = DEFAULT_RANDOM_SEED,
    ):
        self.api_key = api_key
        self.output_dir = output_dir
        self.target_per_keyword = target_per_keyword
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.max_page_limit = max_page_limit
        self.max_per_query = max_per_query
        self.max_candidates_per_keyword = max_candidates_per_keyword
        self.candidate_buffer_multiplier = candidate_buffer_multiplier
        self.max_attempts_per_keyword = max_attempts_per_keyword
        self.max_author_per_keyword = max_author_per_keyword
        self.rate_limit = rate_limit
        self.dry_run = dry_run
        self.audit_only = audit_only
        self.resume = resume
        self.keyword_scope = keyword_scope or set()

        self.random = random.Random(seed)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Authorization": f"Token {self.api_key}"})
        self.throttle = RequestThrottle(rate_limit)

        self.audio_backend_ready = ensure_mixer_initialized()
        if not self.audio_backend_ready:
            print("[SFX] mixer unavailable; decode-based quality checks will be downgraded.")

        self.metadata_path = self.output_dir / METADATA_FILENAME
        self.rejected_path = self.output_dir / REJECTED_FILENAME
        self.summary_path = self.output_dir / SUMMARY_FILENAME
        self.license_manifest_path = self.output_dir / LICENSE_MANIFEST_FILENAME
        self.audit_csv_path = self.output_dir / KEYWORD_AUDIT_CSV_FILENAME
        self.audit_json_path = self.output_dir / KEYWORD_AUDIT_JSON_FILENAME
        self.bundle_dir = Path(SFX_BUNDLE_DIR).resolve()

        self.existing_records: List[Dict[str, object]] = []
        self.records_by_keyword: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
        self.sound_ids_in_use: Set[int] = set()
        self.hashes_in_use: Set[str] = set()
        self.name_keys_in_use: Set[str] = set()
        self.author_count_by_keyword: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)

        self.rejected_rows: List[Dict[str, object]] = []
        self.rejected_counter_global: Counter[str] = Counter()
        self.rejected_counter_by_category: Dict[str, Counter[str]] = defaultdict(Counter)
        self.rejected_counter_by_keyword: Dict[Tuple[str, str], Counter[str]] = defaultdict(Counter)

        self.downloaded_count_by_category: Counter[str] = Counter()
        self.downloaded_count_by_keyword: Dict[Tuple[str, str], int] = defaultdict(int)
        self.downloaded_examples_by_category: Dict[str, List[str]] = defaultdict(list)
        self.downloaded_examples_by_keyword: Dict[Tuple[str, str], List[str]] = defaultdict(list)

        self.final_count_by_category: Counter[str] = Counter()
        self.final_count_by_keyword: Dict[Tuple[str, str], int] = defaultdict(int)
        self.keyword_gap_reason: Dict[Tuple[str, str], str] = {}
        self.trimmed_existing_records = 0

        self.keyword_pairs: List[Tuple[str, str]] = []
        self.keyword_audit: Dict[Tuple[str, str], Dict[str, object]] = {}
    def run(self) -> int:
        self._prepare_dirs()
        self.keyword_pairs = self._resolve_keyword_pairs()
        if not self.keyword_pairs:
            print("[SFX] No keywords matched scope; nothing to process.")
            return 1

        if self.resume:
            self._load_existing_metadata()

        self._run_keyword_audit()
        if self.audit_only:
            self._print_audit_summary()
            return 0

        accepted_records = list(self.existing_records) if self.resume else []

        for category, keyword_bucket in self.keyword_pairs:
            key = (category, keyword_bucket)
            existing_valid = list(self.records_by_keyword.get(key, []))
            current_count = len(existing_valid)

            needed = max(0, self.target_per_keyword - current_count)
            if needed <= 0:
                continue

            audit_row = self.keyword_audit.get(key, {})
            status = str(audit_row.get("status", "ok"))
            query_chain = self._resolve_query_chain(keyword_bucket=keyword_bucket, status=status)
            audit_row["query_chain"] = query_chain

            candidates = self._fetch_candidates(
                category=category,
                keyword_bucket=keyword_bucket,
                query_chain=query_chain,
                needed=needed,
                status=status,
            )

            attempts = 0
            for candidate in candidates:
                if needed <= 0:
                    break
                if attempts >= self.max_attempts_per_keyword:
                    break
                attempts += 1

                if candidate.sound_id in self.sound_ids_in_use:
                    self._reject(candidate, reason="duplicate_sound_id")
                    continue

                author_key = candidate.author.strip().lower() or "unknown"
                if self.author_count_by_keyword[key][author_key] >= self.max_author_per_keyword:
                    self._reject(candidate, reason="author_overrepresented")
                    continue

                _, filename, target_path = self._allocate_target_file(
                    category=category,
                    keyword_bucket=keyword_bucket,
                    candidate=candidate,
                    initial_rank=current_count + self.downloaded_count_by_keyword[key] + 1,
                )

                name_key = f"{category}|{keyword_bucket}|{normalize_name_key(filename)}"
                if name_key in self.name_keys_in_use:
                    self._reject(candidate, reason="duplicate_normalized_name")
                    continue

                if self.dry_run:
                    self._accept_dry_run(
                        category=category,
                        keyword_bucket=keyword_bucket,
                        filename=filename,
                        candidate=candidate,
                        name_key=name_key,
                    )
                    needed -= 1
                    continue

                try:
                    self._download_file(candidate.preview_url, target_path)
                except Exception as exc:  # noqa: BLE001
                    self._reject(candidate, reason=f"download_failed:{exc}")
                    continue

                quality_reasons, metrics = self._validate_download(candidate=candidate, path=target_path)
                if quality_reasons:
                    for reason in quality_reasons:
                        self._reject(candidate, reason=reason)
                    safe_unlink(target_path)
                    continue

                file_sha = sha256_of_file(target_path)
                if file_sha in self.hashes_in_use:
                    self._reject(candidate, reason="duplicate_hash")
                    safe_unlink(target_path)
                    continue

                gain_db = clamp_db(
                    RMS_TARGET_DBFS - metrics.rms_db,
                    RECOMMENDED_GAIN_MIN_DB,
                    RECOMMENDED_GAIN_MAX_DB,
                )
                downloaded_at = utc_now_iso()
                record = {
                    "filename": filename,
                    "category": category,
                    "keyword": keyword_bucket,
                    "keyword_bucket": keyword_bucket,
                    "query_used": candidate.query_used,
                    "suitability_status": status,
                    "source_url": candidate.source_url,
                    "license": candidate.license_raw,
                    "license_url": candidate.license_raw,
                    "author": candidate.author,
                    "sound_id": candidate.sound_id,
                    "duration_sec": f"{metrics.duration_sec:.3f}",
                    "downloaded_at": downloaded_at,
                    "file_sha256": file_sha,
                    "preview_url": candidate.preview_url,
                    "peak_db": f"{metrics.peak_db:.2f}",
                    "rms_db": f"{metrics.rms_db:.2f}",
                    "recommended_gain_db": f"{gain_db:.2f}",
                }
                accepted_records.append(record)
                self.records_by_keyword[key].append(record)

                self.sound_ids_in_use.add(candidate.sound_id)
                self.hashes_in_use.add(file_sha)
                self.name_keys_in_use.add(name_key)
                self.author_count_by_keyword[key][author_key] += 1

                self.downloaded_count_by_keyword[key] += 1
                self.downloaded_count_by_category[category] += 1
                self.final_count_by_keyword[key] += 1
                self.final_count_by_category[category] += 1
                self.downloaded_examples_by_keyword[key].append(filename)
                self.downloaded_examples_by_category[category].append(filename)

                needed -= 1

            if needed > 0:
                self.keyword_gap_reason[key] = (
                    "low_supply" if status == "low_supply" else "continuous_download_failures"
                )

        accepted_records = self._dedupe_records(accepted_records)

        if self.dry_run:
            summary = self._build_summary(records=accepted_records)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        self._write_metadata(accepted_records)
        self._write_rejected()
        self._write_license_manifest(accepted_records, self.license_manifest_path)
        summary = self._build_summary(records=accepted_records)
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self._export_demo_bundle(accepted_records, summary)
        self._print_summary(summary)
        return 0

    def _prepare_dirs(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.dry_run or self.audit_only:
            return
        for category in SFX_CATEGORY_KEYWORDS.keys():
            (self.output_dir / category).mkdir(parents=True, exist_ok=True)

    def _resolve_keyword_pairs(self) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        for category, keywords in SFX_CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if self._is_keyword_selected(category=category, keyword=keyword):
                    pairs.append((category, keyword))
        return pairs

    def _is_keyword_selected(self, category: str, keyword: str) -> bool:
        if not self.keyword_scope:
            return True
        ck = f"{category.strip().lower()}:{keyword.strip().lower()}"
        k = keyword.strip().lower()
        return ck in self.keyword_scope or k in self.keyword_scope

    def _load_existing_metadata(self):
        if not self.metadata_path.exists():
            return

        with self.metadata_path.open("r", encoding="utf-8", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                category = str(row.get("category", "")).strip()
                if category not in SFX_CATEGORY_KEYWORDS:
                    continue

                keyword_bucket = str(row.get("keyword_bucket", "")).strip() or str(row.get("keyword", "")).strip()
                if keyword_bucket not in SFX_CATEGORY_KEYWORDS.get(category, []):
                    continue

                filename = str(row.get("filename", "")).strip()
                if not filename:
                    continue
                file_path = self.output_dir / category / filename
                if not file_path.exists():
                    continue

                if classify_license(str(row.get("license", ""))) != LICENSE_CC0:
                    continue

                normalized = dict(row)
                normalized["keyword"] = keyword_bucket
                normalized["keyword_bucket"] = keyword_bucket
                if not str(normalized.get("query_used", "")).strip():
                    normalized["query_used"] = keyword_bucket
                if not str(normalized.get("suitability_status", "")).strip():
                    normalized["suitability_status"] = "legacy"

                key = (category, keyword_bucket)
                if len(self.records_by_keyword[key]) >= self.target_per_keyword:
                    self.trimmed_existing_records += 1
                    continue
                self.existing_records.append(normalized)
                self.records_by_keyword[key].append(normalized)

                try:
                    self.sound_ids_in_use.add(int(float(row.get("sound_id", 0) or 0)))
                except (TypeError, ValueError):
                    pass

                file_sha = str(row.get("file_sha256", "")).strip()
                if file_sha:
                    self.hashes_in_use.add(file_sha)

                name_key = f"{category}|{keyword_bucket}|{normalize_name_key(filename)}"
                self.name_keys_in_use.add(name_key)

                author = str(row.get("author", "")).strip().lower() or "unknown"
                self.author_count_by_keyword[key][author] += 1

        self._sync_final_counts_from_records(self.existing_records)

    def _sync_final_counts_from_records(self, records: Sequence[Dict[str, object]]):
        self.final_count_by_category = Counter()
        self.final_count_by_keyword = defaultdict(int)
        for row in records:
            category = str(row.get("category", "")).strip()
            keyword_bucket = str(row.get("keyword_bucket", "")).strip() or str(row.get("keyword", "")).strip()
            key = (category, keyword_bucket)
            self.final_count_by_category[category] += 1
            self.final_count_by_keyword[key] += 1

    def _run_keyword_audit(self):
        rows: List[Dict[str, object]] = []
        for category, keyword_bucket in self.keyword_pairs:
            row = self._audit_keyword(category=category, keyword_bucket=keyword_bucket)
            key = (category, keyword_bucket)
            self.keyword_audit[key] = row
            rows.append(row)

        fieldnames = [
            "category",
            "keyword_bucket",
            "cc0_candidates_top50",
            "music_like_ratio",
            "status",
            "query_chain",
        ]
        with self.audit_csv_path.open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "category": row["category"],
                        "keyword_bucket": row["keyword_bucket"],
                        "cc0_candidates_top50": row["cc0_candidates_top50"],
                        "music_like_ratio": f"{float(row['music_like_ratio']):.4f}",
                        "status": row["status"],
                        "query_chain": " | ".join(row.get("query_chain", [row["keyword_bucket"]])),
                    }
                )

        self.audit_json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def _audit_keyword(self, category: str, keyword_bucket: str) -> Dict[str, object]:
        payload = self._search(keyword=keyword_bucket, page=1, page_size=DEFAULT_PAGE_SIZE)
        results = payload.get("results") or []

        cc0_candidates = 0
        music_like_count = 0
        for raw in results:
            candidate = self._to_candidate(
                raw=raw,
                category=category,
                keyword_bucket=keyword_bucket,
                query_used=keyword_bucket,
            )
            if candidate is None:
                continue
            cc0_candidates += 1
            merged = set(tokenize(candidate.name))
            for tag in candidate.tags:
                merged.update(tokenize(tag))
            if merged.intersection(MUSIC_LIKE_TOKENS):
                music_like_count += 1

        ratio = (music_like_count / cc0_candidates) if cc0_candidates else 0.0
        status = "ok"
        if cc0_candidates < AUDIT_LOW_SUPPLY_THRESHOLD:
            status = "low_supply"
        elif ratio >= AUDIT_NOISY_THRESHOLD:
            status = "noisy"

        return {
            "category": category,
            "keyword_bucket": keyword_bucket,
            "cc0_candidates_top50": cc0_candidates,
            "music_like_ratio": round(ratio, 6),
            "status": status,
            "query_chain": self._resolve_query_chain(keyword_bucket=keyword_bucket, status=status),
        }
    def _resolve_query_chain(self, keyword_bucket: str, status: str) -> List[str]:
        chain: List[str] = [keyword_bucket]
        if status in {"low_supply", "noisy"}:
            for alias in SFX_KEYWORD_ALIASES.get(keyword_bucket, []):
                if alias not in chain:
                    chain.append(alias)
        return chain

    def _fetch_candidates(
        self,
        category: str,
        keyword_bucket: str,
        query_chain: Sequence[str],
        needed: int,
        status: str,
    ) -> List[Candidate]:
        collected: Dict[int, Candidate] = {}
        target_pool_size = min(
            self.max_candidates_per_keyword,
            max(needed + 5, needed * self.candidate_buffer_multiplier),
        )

        for query_used in query_chain:
            if len(collected) >= target_pool_size:
                break

            per_query_count = 0
            for page in range(1, self.max_page_limit + 1):
                if len(collected) >= target_pool_size:
                    break

                payload = self._search(keyword=query_used, page=page, page_size=DEFAULT_PAGE_SIZE)
                results = payload.get("results") or []
                if not isinstance(results, list) or not results:
                    break

                for raw in results:
                    candidate = self._to_candidate(
                        raw=raw,
                        category=category,
                        keyword_bucket=keyword_bucket,
                        query_used=query_used,
                    )
                    if candidate is None:
                        continue

                    if candidate.sound_id in collected:
                        continue

                    if status == "noisy" and self._contains_keyword_negative_tokens(
                        keyword_bucket=keyword_bucket,
                        name=candidate.name,
                        tags=candidate.tags,
                    ):
                        continue

                    collected[candidate.sound_id] = candidate
                    per_query_count += 1

                    if len(collected) >= target_pool_size:
                        break
                    if per_query_count >= self.max_per_query:
                        break

                if per_query_count >= self.max_per_query:
                    break
                if len(results) < DEFAULT_PAGE_SIZE:
                    break

        items = list(collected.values())
        items.sort(key=lambda item: item.score, reverse=True)
        return items

    def _contains_keyword_negative_tokens(self, keyword_bucket: str, name: str, tags: Sequence[str]) -> bool:
        negatives = SFX_KEYWORD_NEGATIVE_TOKENS.get(keyword_bucket)
        if not negatives:
            return False

        merged = set(tokenize(name))
        for tag in tags:
            merged.update(tokenize(tag))
        return bool(merged.intersection(negatives))

    def _search(self, keyword: str, page: int, page_size: int) -> Dict[str, object]:
        duration_filter = f"duration:[{self.min_duration} TO *] AND duration:[* TO {self.max_duration}]"
        params = {
            "query": keyword,
            "page": page,
            "page_size": page_size,
            "filter": duration_filter,
            "fields": "id,name,license,username,duration,url,previews,tags,num_downloads,avg_rating",
        }
        return self._request_json(API_SEARCH_URL, params)

    def _request_json(self, url: str, params: Dict[str, object]) -> Dict[str, object]:
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                self.throttle.wait()
                response = self.session.get(url, params=params, timeout=25)

                if response.status_code == 404 and int(params.get("page", 1)) > 1:
                    return {"results": []}
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:120]}")

                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("Invalid API response format")
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= MAX_RETRIES - 1:
                    break
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))

        raise RuntimeError(f"Request to Freesound failed: {last_error}")

    def _to_candidate(
        self,
        raw: Dict[str, object],
        category: str,
        keyword_bucket: str,
        query_used: str,
    ) -> Optional[Candidate]:
        try:
            sound_id = int(raw.get("id"))
        except (TypeError, ValueError):
            return None

        name = str(raw.get("name") or "").strip() or f"sound_{sound_id}"
        duration = float(raw.get("duration") or 0.0)
        if duration < self.min_duration or duration > self.max_duration:
            return None

        license_raw = str(raw.get("license") or "").strip()
        if classify_license(license_raw) != LICENSE_CC0:
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
        author = str(raw.get("username") or "").strip() or "unknown"
        downloads = int(raw.get("num_downloads") or 0)
        rating = float(raw.get("avg_rating") or 0.0)

        tags_raw = raw.get("tags")
        tags: List[str] = []
        if isinstance(tags_raw, list):
            tags = [str(tag).strip() for tag in tags_raw if str(tag).strip()]

        keyword_match = keyword_match_score(keyword=query_used, name=name, tags=tags)
        if keyword_match <= 0:
            return None

        return Candidate(
            sound_id=sound_id,
            category=category,
            keyword_bucket=keyword_bucket,
            query_used=query_used,
            name=name,
            duration_sec=duration,
            license_raw=license_raw,
            author=author,
            source_url=source_url,
            preview_url=preview_url,
            tags=tags,
            downloads=downloads,
            rating=rating,
            keyword_match_score=keyword_match,
        )

    def _allocate_target_file(
        self,
        category: str,
        keyword_bucket: str,
        candidate: Candidate,
        initial_rank: int,
    ) -> Tuple[int, str, Path]:
        rank = max(1, initial_rank)
        while True:
            filename = self._build_filename(rank=rank, candidate=candidate, keyword_bucket=keyword_bucket)
            target_path = self.output_dir / category / filename
            if not target_path.exists():
                return rank, filename, target_path
            rank += 1

    def _build_filename(self, rank: int, candidate: Candidate, keyword_bucket: str) -> str:
        bucket_slug = slugify(keyword_bucket)
        name_slug = slugify(candidate.name)[:28]
        return f"{rank:02d}_{candidate.sound_id}_{bucket_slug}_{name_slug}.mp3"

    def _download_file(self, preview_url: str, target_path: Path):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                self.throttle.wait()
                with self.session.get(preview_url, stream=True, timeout=35) as response:
                    if response.status_code in {429, 500, 502, 503, 504}:
                        raise RuntimeError(f"HTTP {response.status_code} while downloading")
                    response.raise_for_status()
                    with target_path.open("wb") as fh:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                fh.write(chunk)

                if target_path.stat().st_size <= 0:
                    raise RuntimeError("downloaded empty file")
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                safe_unlink(target_path)
                if attempt >= MAX_RETRIES - 1:
                    break
                time.sleep(BACKOFF_SECONDS * (2 ** attempt))

        raise RuntimeError(str(last_error))

    def _validate_download(self, candidate: Candidate, path: Path) -> Tuple[List[str], AudioMetrics]:
        reasons: List[str] = []

        if path.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
            reasons.append("unsupported_extension")

        if self.audio_backend_ready:
            try:
                metrics = analyze_audio(path)
            except Exception as exc:  # noqa: BLE001
                fallback = AudioMetrics(duration_sec=0.0, peak_db=-120.0, rms_db=-120.0, clipping_ratio=0.0)
                return [str(exc)], fallback
        else:
            metrics = AudioMetrics(
                duration_sec=float(candidate.duration_sec),
                peak_db=-6.0,
                rms_db=-24.0,
                clipping_ratio=0.0,
            )
            if path.stat().st_size < 1024:
                reasons.append("file_too_small")

        if metrics.duration_sec < self.min_duration:
            reasons.append("duration_too_short")
        if metrics.duration_sec > self.max_duration:
            reasons.append("duration_too_long")
        if metrics.rms_db < MIN_VALID_RMS_DBFS:
            reasons.append("rms_too_low")
        if metrics.clipping_ratio > MAX_CLIPPING_RATIO:
            reasons.append("clipping_too_high")

        merged_tokens = set(tokenize(candidate.name))
        for tag in candidate.tags:
            merged_tokens.update(tokenize(tag))

        if "watermark" in merged_tokens:
            reasons.append("possible_watermark")

        if candidate.duration_sec >= 3.5 and merged_tokens.intersection(SFX_STYLE_BLOCK_TOKENS):
            reasons.append("likely_not_sfx")

        negatives = SFX_KEYWORD_NEGATIVE_TOKENS.get(candidate.keyword_bucket, set())
        if negatives and merged_tokens.intersection(negatives):
            reasons.append("keyword_negative_token")

        return reasons, metrics

    def _accept_dry_run(
        self,
        category: str,
        keyword_bucket: str,
        filename: str,
        candidate: Candidate,
        name_key: str,
    ):
        key = (category, keyword_bucket)
        self.sound_ids_in_use.add(candidate.sound_id)
        self.name_keys_in_use.add(name_key)
        self.author_count_by_keyword[key][candidate.author.strip().lower() or "unknown"] += 1

        self.downloaded_count_by_keyword[key] += 1
        self.downloaded_count_by_category[category] += 1
        self.final_count_by_keyword[key] += 1
        self.final_count_by_category[category] += 1
        self.downloaded_examples_by_keyword[key].append(filename)
        self.downloaded_examples_by_category[category].append(filename)

    def _reject(self, candidate: Candidate, reason: str):
        key = (candidate.category, candidate.keyword_bucket)
        row = {
            "timestamp": utc_now_iso(),
            "category": candidate.category,
            "keyword": candidate.keyword_bucket,
            "keyword_bucket": candidate.keyword_bucket,
            "query_used": candidate.query_used,
            "sound_id": candidate.sound_id,
            "name": candidate.name,
            "reason": reason,
            "license": candidate.license_raw,
            "duration_sec": f"{candidate.duration_sec:.3f}",
            "source_url": candidate.source_url,
        }
        self.rejected_rows.append(row)
        self.rejected_counter_global[reason] += 1
        self.rejected_counter_by_category[candidate.category][reason] += 1
        self.rejected_counter_by_keyword[key][reason] += 1
    def _dedupe_records(self, records: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
        dedup_by_sound: Dict[int, Dict[str, object]] = {}
        for row in records:
            try:
                sound_id = int(float(row.get("sound_id", 0) or 0))
            except (TypeError, ValueError):
                continue
            if sound_id not in dedup_by_sound:
                dedup_by_sound[sound_id] = row

        dedup_by_hash: Dict[str, Dict[str, object]] = {}
        fallback_rows: List[Dict[str, object]] = []
        for row in dedup_by_sound.values():
            file_sha = str(row.get("file_sha256", "")).strip()
            if file_sha:
                if file_sha not in dedup_by_hash:
                    dedup_by_hash[file_sha] = row
            else:
                fallback_rows.append(row)

        merged = list(dedup_by_hash.values()) + fallback_rows
        merged.sort(
            key=lambda item: (
                str(item.get("category", "")),
                str(item.get("keyword_bucket", item.get("keyword", ""))),
                str(item.get("filename", "")),
            )
        )
        return merged

    def _write_metadata(self, records: Sequence[Dict[str, object]]):
        fieldnames = [
            "filename",
            "category",
            "keyword",
            "keyword_bucket",
            "query_used",
            "suitability_status",
            "source_url",
            "license",
            "license_url",
            "author",
            "sound_id",
            "duration_sec",
            "downloaded_at",
            "file_sha256",
            "preview_url",
            "peak_db",
            "rms_db",
            "recommended_gain_db",
        ]
        with self.metadata_path.open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in records:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _write_rejected(self):
        fieldnames = [
            "timestamp",
            "category",
            "keyword",
            "keyword_bucket",
            "query_used",
            "sound_id",
            "name",
            "reason",
            "license",
            "duration_sec",
            "source_url",
        ]
        with self.rejected_path.open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in self.rejected_rows:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _write_license_manifest(self, records: Sequence[Dict[str, object]], target_path: Path):
        fieldnames = [
            "filename",
            "category",
            "keyword_bucket",
            "sound_id",
            "author",
            "license",
            "license_url",
            "source_url",
        ]
        with target_path.open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in records:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _build_summary(self, records: Sequence[Dict[str, object]]) -> Dict[str, object]:
        per_category_total = Counter(str(row.get("category", "")).strip() for row in records)
        per_keyword_total: Counter[Tuple[str, str]] = Counter()
        for row in records:
            category = str(row.get("category", "")).strip()
            keyword_bucket = str(row.get("keyword_bucket", "")).strip() or str(row.get("keyword", "")).strip()
            per_keyword_total[(category, keyword_bucket)] += 1

        categories: Dict[str, object] = {}
        per_keyword: Dict[str, object] = {}

        for category, keywords in SFX_CATEGORY_KEYWORDS.items():
            category_target = self.target_per_keyword * len(keywords)
            category_missing = 0
            keyword_rows: Dict[str, object] = {}

            for keyword_bucket in keywords:
                key = (category, keyword_bucket)
                total = int(per_keyword_total.get(key, 0))
                downloaded = int(self.downloaded_count_by_keyword.get(key, 0))
                missing = max(0, self.target_per_keyword - total)
                category_missing += missing

                audit_row = self.keyword_audit.get(key, {})
                status = str(audit_row.get("status", "not_scoped"))
                if key not in self.keyword_gap_reason and missing > 0:
                    if status == "low_supply":
                        self.keyword_gap_reason[key] = "low_supply"
                    elif key in self.keyword_audit:
                        self.keyword_gap_reason[key] = "continuous_download_failures"

                keyword_rows[keyword_bucket] = {
                    "total_count": total,
                    "downloaded_count": downloaded,
                    "target_count": self.target_per_keyword,
                    "missing_count": missing,
                    "status": status,
                    "gap_reason": self.keyword_gap_reason.get(key, ""),
                    "rejected_reason_counts": dict(self.rejected_counter_by_keyword.get(key, Counter())),
                    "examples": self.downloaded_examples_by_keyword.get(key, [])[:3],
                    "query_chain": audit_row.get("query_chain", [keyword_bucket]),
                    "cc0_candidates_top50": audit_row.get("cc0_candidates_top50", 0),
                    "music_like_ratio": audit_row.get("music_like_ratio", 0.0),
                }

            categories[category] = {
                "total_count": int(per_category_total.get(category, 0)),
                "downloaded_count": int(self.downloaded_count_by_category.get(category, 0)),
                "target_count": category_target,
                "missing_count": category_missing,
                "examples": self.downloaded_examples_by_category.get(category, [])[:3],
                "rejected_reason_counts": dict(self.rejected_counter_by_category.get(category, Counter())),
            }
            per_keyword[category] = keyword_rows

        return {
            "generated_at": utc_now_iso(),
            "output_dir": str(self.output_dir),
            "target_per_keyword": self.target_per_keyword,
            "totals": {
                "accepted_records": len(records),
                "rejected_records": len(self.rejected_rows),
                "processed_keywords": len(self.keyword_pairs),
                "trimmed_existing_records": self.trimmed_existing_records,
            },
            "categories": categories,
            "per_keyword": per_keyword,
            "global_rejected_reason_counts": dict(self.rejected_counter_global),
        }

    def _export_demo_bundle(self, records: Sequence[Dict[str, object]], summary: Dict[str, object]):
        self.bundle_dir.mkdir(parents=True, exist_ok=True)

        grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        for row in records:
            category = str(row.get("category", "")).strip()
            grouped[category].append(row)

        bundle_records: List[Dict[str, object]] = []
        for category in SFX_CATEGORY_KEYWORDS.keys():
            rows = sorted(grouped.get(category, []), key=lambda item: str(item.get("filename", "")))
            selected = rows[:2]
            if not selected:
                continue

            target_dir = self.bundle_dir / category
            target_dir.mkdir(parents=True, exist_ok=True)

            for row in selected:
                filename = str(row.get("filename", "")).strip()
                source = self.output_dir / category / filename
                if not source.exists():
                    continue
                dest = target_dir / filename
                try:
                    shutil.copy2(source, dest)
                except Exception:
                    continue
                bundle_records.append(dict(row))

        metadata_target = self.bundle_dir / METADATA_FILENAME
        license_target = self.bundle_dir / LICENSE_MANIFEST_FILENAME
        summary_target = self.bundle_dir / SUMMARY_FILENAME

        self._write_csv_records(metadata_target, bundle_records)
        self._write_license_manifest(bundle_records, license_target)
        summary_target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_csv_records(self, target_path: Path, records: Sequence[Dict[str, object]]):
        fieldnames = [
            "filename",
            "category",
            "keyword",
            "keyword_bucket",
            "query_used",
            "suitability_status",
            "source_url",
            "license",
            "license_url",
            "author",
            "sound_id",
            "duration_sec",
            "downloaded_at",
            "file_sha256",
            "preview_url",
            "peak_db",
            "rms_db",
            "recommended_gain_db",
        ]
        with target_path.open("w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in records:
                writer.writerow({name: row.get(name, "") for name in fieldnames})

    def _print_audit_summary(self):
        print("\n========== SFX KEYWORD AUDIT ==========")
        low_supply = 0
        noisy = 0
        for category, keyword in self.keyword_pairs:
            row = self.keyword_audit[(category, keyword)]
            status = row["status"]
            if status == "low_supply":
                low_supply += 1
            elif status == "noisy":
                noisy += 1
            print(
                f"[{category}::{keyword}] cc0_top50={row['cc0_candidates_top50']} "
                f"music_like_ratio={float(row['music_like_ratio']):.2f} status={status}"
            )
        print(f"audit_csv: {self.audit_csv_path}")
        print(f"audit_json: {self.audit_json_path}")
        print(f"totals: low_supply={low_supply}, noisy={noisy}, keywords={len(self.keyword_pairs)}")
        print("======================================\n")

    def _print_summary(self, summary: Dict[str, object]):
        print("\n========== SFX DOWNLOAD SUMMARY ==========")
        categories = summary.get("categories", {})
        if isinstance(categories, dict):
            for category in SFX_CATEGORY_KEYWORDS.keys():
                row = categories.get(category, {})
                if not isinstance(row, dict):
                    continue
                examples = row.get("examples", [])
                example_text = "、".join(examples[:3]) if isinstance(examples, list) and examples else "无"
                print(
                    f"[{category}] total={row.get('total_count', 0)} "
                    f"downloaded={row.get('downloaded_count', 0)} "
                    f"missing={row.get('missing_count', 0)} examples={example_text}"
                )

        per_keyword = summary.get("per_keyword", {})
        missing_keywords = []
        if isinstance(per_keyword, dict):
            for category, rows in per_keyword.items():
                if not isinstance(rows, dict):
                    continue
                for keyword_bucket, info in rows.items():
                    if int(info.get("missing_count", 0)) > 0:
                        missing_keywords.append((category, keyword_bucket, info.get("gap_reason", "")))

        if missing_keywords:
            print("\nKeywords with gaps:")
            for category, keyword_bucket, reason in missing_keywords:
                print(f"- {category}::{keyword_bucket} -> {reason or 'unknown'}")

        print(f"metadata: {self.metadata_path}")
        print(f"rejected: {self.rejected_path}")
        print(f"summary: {self.summary_path}")
        print(f"audit_csv: {self.audit_csv_path}")
        print(f"audit_json: {self.audit_json_path}")
        print(f"demo_bundle: {self.bundle_dir}")
        print("==========================================\n")

def safe_unlink(path: Path):
    for _ in range(4):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05)
        except Exception:
            return


def tokenize(text: str) -> Set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", text.lower()) if token}


def keyword_match_score(keyword: str, name: str, tags: Sequence[str]) -> float:
    keyword_tokens = {token for token in tokenize(keyword) if token not in GENERIC_KEYWORD_TOKENS}
    if not keyword_tokens:
        keyword_tokens = tokenize(keyword)

    merged = tokenize(name)
    for tag in tags:
        merged.update(tokenize(tag))
    if not merged:
        return 0.0

    hits = len(keyword_tokens.intersection(merged))
    return float(hits)


def classify_license(license_raw: str) -> str:
    text = license_raw.strip().lower()
    if "publicdomain/zero" in text or "cc0" in text:
        return LICENSE_CC0
    return "other"


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return lowered or "sfx"


def normalize_name_key(filename: str) -> str:
    lowered = filename.lower()
    lowered = re.sub(r"^\d+_", "", lowered)
    lowered = re.sub(r"_\d+_", "_", lowered)
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def clamp_db(value: float, min_db: float, max_db: float) -> float:
    return max(min_db, min(max_db, value))


def to_dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(value / 32768.0)


def analyze_audio(path: Path) -> AudioMetrics:
    try:
        sound = pygame.mixer.Sound(str(path))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"decode_error:{exc}") from exc

    duration = float(sound.get_length())
    if np is None:
        del sound
        return AudioMetrics(duration_sec=duration, peak_db=-6.0, rms_db=-24.0, clipping_ratio=0.0)

    try:
        arr = pygame.sndarray.array(sound).astype(np.float64)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"decode_error:{exc}") from exc
    finally:
        del sound

    if arr.size == 0:
        raise RuntimeError("empty_audio")

    if arr.ndim == 2:
        mono = arr.mean(axis=1)
    else:
        mono = arr

    if mono.size == 0:
        raise RuntimeError("empty_audio")

    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono))))
    clipping_ratio = float(np.mean(np.abs(mono) >= 32760))

    return AudioMetrics(
        duration_sec=duration,
        peak_db=to_dbfs(peak),
        rms_db=to_dbfs(rms),
        clipping_ratio=clipping_ratio,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_keyword_scope(raw_values: Optional[List[str]]) -> Set[str]:
    if not raw_values:
        return set()

    normalized: Set[str] = set()
    for raw in raw_values:
        if not raw:
            continue
        for part in raw.split(","):
            token = part.strip().lower()
            if token:
                normalized.add(token)
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and curate AI-DM SFX library (keyword-level).")
    parser.add_argument("--dry-run", action="store_true", help="Simulate acceptance and report only.")
    parser.add_argument("--resume", action="store_true", help="Resume from existing metadata.csv.")
    parser.add_argument("--audit-only", action="store_true", help="Only run keyword audit and write audit files.")
    parser.add_argument(
        "--keyword-scope",
        action="append",
        help="Limit run to selected keywords (comma-separated or repeated; supports 'category:keyword').",
    )

    parser.add_argument("--output-dir", default=SFX_LIBRARY_DIR, help="Output directory.")
    parser.add_argument("--target-per-keyword", type=int, default=DEFAULT_TARGET_PER_KEYWORD, help="Target assets per keyword bucket.")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION_SEC, help="Minimum duration in seconds.")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION_SEC, help="Maximum duration in seconds.")
    parser.add_argument("--rate-limit", type=int, default=DEFAULT_RATE_LIMIT, help="API request rate limit (per minute).")

    parser.add_argument("--max-page-limit", type=int, default=DEFAULT_MAX_PAGE_LIMIT, help="Max pages per query term.")
    parser.add_argument("--max-per-query", type=int, default=DEFAULT_MAX_PER_QUERY, help="Max collected candidates per query term.")
    parser.add_argument(
        "--max-candidates-per-keyword",
        type=int,
        default=DEFAULT_MAX_CANDIDATES_PER_KEYWORD,
        help="Max candidate pool size per keyword bucket.",
    )
    parser.add_argument(
        "--candidate-buffer-multiplier",
        type=int,
        default=DEFAULT_CANDIDATE_BUFFER_MULTIPLIER,
        help="Candidate pool multiplier based on target count.",
    )
    parser.add_argument(
        "--max-attempts-per-keyword",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS_PER_KEYWORD,
        help="Max download attempts per keyword bucket.",
    )
    parser.add_argument(
        "--max-author-per-keyword",
        type=int,
        default=DEFAULT_MAX_AUTHOR_PER_KEYWORD,
        help="Max assets per author under the same keyword bucket.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_RANDOM_SEED, help="Random seed.")
    return parser.parse_args()


def main() -> int:
    if load_dotenv is not None:
        load_dotenv()

    api_key = os.getenv("FREESOUND_API_KEY", "").strip()
    if not api_key:
        print("FREESOUND_API_KEY is missing. Please configure it in .env")
        return 1

    args = parse_args()
    keyword_scope = parse_keyword_scope(args.keyword_scope)

    downloader = SFXLibraryDownloader(
        api_key=api_key,
        output_dir=Path(args.output_dir).resolve(),
        target_per_keyword=max(1, int(args.target_per_keyword)),
        min_duration=max(0.01, float(args.min_duration)),
        max_duration=max(float(args.min_duration), float(args.max_duration)),
        max_page_limit=max(1, int(args.max_page_limit)),
        max_per_query=max(1, int(args.max_per_query)),
        max_candidates_per_keyword=max(10, int(args.max_candidates_per_keyword)),
        candidate_buffer_multiplier=max(2, int(args.candidate_buffer_multiplier)),
        max_attempts_per_keyword=max(10, int(args.max_attempts_per_keyword)),
        max_author_per_keyword=max(1, int(args.max_author_per_keyword)),
        rate_limit=max(1, int(args.rate_limit)),
        dry_run=bool(args.dry_run),
        audit_only=bool(args.audit_only),
        resume=bool(args.resume),
        keyword_scope=keyword_scope,
        seed=int(args.seed),
    )

    try:
        return downloader.run()
    finally:
        try:
            if pygame.mixer.get_init() is not None:
                pygame.mixer.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
