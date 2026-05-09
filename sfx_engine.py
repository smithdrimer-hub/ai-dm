"""SFX 播放引擎（2026-04-23：新增事件驱动、冷却与去重复播策略）。"""

from __future__ import annotations

import csv
import json
import os
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional

import pygame

from sfx_config import (
    DEFAULT_PRELOAD_HOTSPOTS,
    METADATA_FILENAME,
    SFX_LIBRARY_DIR,
)


@dataclass(frozen=True)
class SFXAsset:
    filename: str
    category: str
    keyword: str
    sound_id: int
    source_url: str
    preview_url: str
    license: str
    author: str
    duration_sec: float
    file_sha256: str
    peak_db: float
    rms_db: float
    recommended_gain_db: float
    file_path: Path


class SFXEngine:
    def __init__(
        self,
        library_root: str = SFX_LIBRARY_DIR,
        event_map_path: str = "sfx_event_map.yaml",
        metadata_filename: str = METADATA_FILENAME,
        enabled: bool = True,
        seed: int = 42,
    ):
        self.library_root = Path(library_root).resolve()
        self.metadata_path = self.library_root / metadata_filename
        self.event_map_path = Path(event_map_path).resolve()
        self.enabled = enabled
        self.master_volume = 0.65
        self.random = random.Random(seed)

        self.mixer_initialized = self._ensure_mixer()
        self.assets_by_category: Dict[str, List[SFXAsset]] = {}
        self.events_map: Dict[str, Dict[str, object]] = {}
        self.defaults: Dict[str, object] = {}
        self.preloaded_sounds: Dict[str, pygame.mixer.Sound] = {}

        self.last_event_played_at: Dict[str, float] = {}
        self.last_sound_played_at: Dict[str, float] = {}
        self.recent_files: Deque[str] = deque(maxlen=10)

        self.refresh()

    def _ensure_mixer(self) -> bool:
        if pygame.mixer.get_init() is not None:
            return True
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[SFX] 音频初始化失败：{exc}")
            return False

    def refresh(self):
        self._load_event_map()
        self._load_assets()
        history_size = int(self.defaults.get("recent_history_size", 10))
        self.recent_files = deque(list(self.recent_files)[-history_size:], maxlen=history_size)
        self._preload_hotspots()

    def _load_event_map(self):
        defaults = {
            "event_cooldown_sec": 0.5,
            "file_reuse_cooldown_sec": 4.0,
            "recent_history_size": 10,
            "preload_hotspots": DEFAULT_PRELOAD_HOTSPOTS,
            "category_base_volume": {},
        }
        events: Dict[str, Dict[str, object]] = {}
        if self.event_map_path.exists():
            try:
                payload = json.loads(self.event_map_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    raw_defaults = payload.get("defaults")
                    raw_events = payload.get("events")
                    if isinstance(raw_defaults, dict):
                        defaults.update(raw_defaults)
                    if isinstance(raw_events, dict):
                        for name, cfg in raw_events.items():
                            if isinstance(name, str) and isinstance(cfg, dict):
                                events[name] = cfg
            except Exception as exc:  # noqa: BLE001
                print(f"[SFX] 事件映射加载失败，使用默认配置：{exc}")
        self.defaults = defaults
        self.events_map = events

    def _load_assets(self):
        grouped: Dict[str, List[SFXAsset]] = defaultdict(list)
        if not self.metadata_path.exists():
            self.assets_by_category = {}
            return

        with self.metadata_path.open("r", encoding="utf-8", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                try:
                    category = str(row.get("category", "")).strip()
                    filename = str(row.get("filename", "")).strip()
                    if not category or not filename:
                        continue
                    file_path = self.library_root / category / filename
                    if not file_path.exists():
                        continue
                    asset = SFXAsset(
                        filename=filename,
                        category=category,
                        keyword=str(row.get("keyword", "")).strip(),
                        sound_id=int(float(row.get("sound_id", 0) or 0)),
                        source_url=str(row.get("source_url", "")).strip(),
                        preview_url=str(row.get("preview_url", "")).strip(),
                        license=str(row.get("license", "")).strip(),
                        author=str(row.get("author", "")).strip(),
                        duration_sec=float(row.get("duration_sec", 0.0) or 0.0),
                        file_sha256=str(row.get("file_sha256", "")).strip(),
                        peak_db=float(row.get("peak_db", 0.0) or 0.0),
                        rms_db=float(row.get("rms_db", 0.0) or 0.0),
                        recommended_gain_db=float(row.get("recommended_gain_db", 0.0) or 0.0),
                        file_path=file_path,
                    )
                    grouped[category].append(asset)
                except Exception:
                    continue

        normalized: Dict[str, List[SFXAsset]] = {}
        for category, items in grouped.items():
            if not items:
                continue
            normalized[category] = sorted(items, key=lambda item: (item.filename, item.sound_id))
        self.assets_by_category = normalized

    def _preload_hotspots(self):
        self.preloaded_sounds = {}
        if not self.mixer_initialized:
            return
        hotspots = self.defaults.get("preload_hotspots", DEFAULT_PRELOAD_HOTSPOTS)
        if not isinstance(hotspots, list):
            hotspots = DEFAULT_PRELOAD_HOTSPOTS

        for category in hotspots:
            if not isinstance(category, str):
                continue
            for asset in self.assets_by_category.get(category, []):
                key = str(asset.file_path)
                if key in self.preloaded_sounds:
                    continue
                try:
                    self.preloaded_sounds[key] = pygame.mixer.Sound(key)
                except Exception:
                    continue

    def list_events(self) -> List[str]:
        return sorted(self.events_map.keys())

    def list_categories(self) -> List[str]:
        return sorted(self.assets_by_category.keys())

    def get_catalog(self) -> Dict[str, int]:
        return {category: len(items) for category, items in sorted(self.assets_by_category.items())}

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def set_volume(self, volume: float):
        self.master_volume = max(0.0, min(1.0, volume))

    def _is_event_cooldown_active(self, event_name: str, cooldown_sec: float, force: bool) -> bool:
        if force:
            return False
        now = time.monotonic()
        last = self.last_event_played_at.get(event_name)
        if last is None:
            return False
        return (now - last) < cooldown_sec

    def _select_asset(self, category: str, force: bool) -> Optional[SFXAsset]:
        candidates = self.assets_by_category.get(category, [])
        if not candidates:
            return None

        now = time.monotonic()
        reuse_cooldown = float(self.defaults.get("file_reuse_cooldown_sec", 4.0))
        if force:
            return self.random.choice(candidates)

        filtered = []
        for asset in candidates:
            key = str(asset.file_path)
            last_played = self.last_sound_played_at.get(key)
            if last_played is not None and (now - last_played) < reuse_cooldown:
                continue
            if key in self.recent_files:
                continue
            filtered.append(asset)

        if filtered:
            return self.random.choice(filtered)
        return self.random.choice(candidates)

    def _get_sound(self, asset: SFXAsset) -> Optional[pygame.mixer.Sound]:
        key = str(asset.file_path)
        if key in self.preloaded_sounds:
            return self.preloaded_sounds[key]
        try:
            return pygame.mixer.Sound(key)
        except Exception:
            return None

    def _resolve_category_volume(self, category: str) -> float:
        raw = self.defaults.get("category_base_volume", {})
        if isinstance(raw, dict):
            value = raw.get(category)
            if value is not None:
                try:
                    return max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    pass
        return 0.6

    def _apply_gain(self, base_volume: float, gain_db: float) -> float:
        gain_multiplier = 10 ** (gain_db / 20.0)
        volume = base_volume * gain_multiplier * self.master_volume
        return max(0.0, min(1.0, volume))

    def play_event(self, event_name: str, force: bool = False) -> bool:
        if not self.enabled or not self.mixer_initialized:
            return False
        event = self.events_map.get(event_name)
        if not isinstance(event, dict):
            return False
        category = str(event.get("category", "")).strip()
        if not category:
            return False
        cooldown = float(event.get("cooldown_sec", self.defaults.get("event_cooldown_sec", 0.5)))
        if self._is_event_cooldown_active(event_name, cooldown, force=force):
            return False
        played = self.play_category(category=category, force=force, event_name=event_name)
        if played:
            self.last_event_played_at[event_name] = time.monotonic()
        return played

    def play_category(self, category: str, force: bool = False, event_name: str = "") -> bool:
        if not self.enabled or not self.mixer_initialized:
            return False
        category = category.strip()
        asset = self._select_asset(category, force=force)
        if asset is None:
            return False
        sound = self._get_sound(asset)
        if sound is None:
            return False

        channel = pygame.mixer.find_channel(force=False)
        if channel is None:
            return False

        base_volume = self._resolve_category_volume(category)
        volume = self._apply_gain(base_volume=base_volume, gain_db=asset.recommended_gain_db)
        sound.set_volume(volume)
        channel.play(sound)

        key = str(asset.file_path)
        self.last_sound_played_at[key] = time.monotonic()
        self.recent_files.append(key)
        if event_name:
            self.last_event_played_at[event_name] = time.monotonic()
        return True

    def get_status(self) -> Dict[str, object]:
        return {
            "enabled": self.enabled,
            "mixer_initialized": self.mixer_initialized,
            "volume": self.master_volume,
            "categories": self.get_catalog(),
            "events": self.list_events(),
        }

    def unload(self):
        self.preloaded_sounds = {}
