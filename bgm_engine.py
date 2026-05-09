"""背景音乐播放模块 - 支持场景模式与情绪模式

2026-04-22 变更说明:
- 一级情绪分类桶同步为 20 类（来自 mood_config.py）。
- 修复 play_for_phase() 空实现，恢复自动情绪切歌逻辑。
- 保持原有命令接口兼容（/bgm on/off/volume/mood/auto）。
- 当 index.json 存在时仅按索引加载，避免“已移除条目”被目录扫描重新纳入。

职责:
- 场景 BGM 播放 (opening/discussion/search/suspense/confrontation/ending)
- 情绪 BGM 播放 (20 种情绪分类，随机选择曲目)
- 自动情绪映射 (根据游戏阶段自动切换到对应情绪)
- 音量控制 (全局音量 + 各场景独立音量配置)

不负责的模块:
- TTS 语音合成 -> tts_engine.py
- 游戏状态判断 -> main.py 的 auto_switch_bgm()

两种播放模式:
1. 场景模式 (play()): 传统单文件模式，每个场景对应一个音乐文件
2. 情绪模式 (play_mood()): 多曲目随机播放，按情绪分类选择

自动情绪映射:
- auto_mood_enabled=True 时，调用 play_for_phase() 自动切换
- 优先使用情绪模式，失败时回退到场景模式
- 结局根据 happy/bad 关键词自动匹配不同情绪

初始化行为:
- 检测 music/moods/ 目录是否有情绪音效
- 如有则自动开启 auto_mood_enabled
- 如无则打印提示，保持关闭状态"""

from __future__ import annotations

import json
import os
import random
from typing import Dict, List, Optional

import pygame

from mood_config import DEFAULT_ENDING_MOOD, DEFAULT_PHASE_TO_MOOD, MOOD_PROFILES


# 场景音乐配置（兼容旧逻辑）
BGM_CONFIGS: Dict[str, Dict[str, object]] = {
    "opening": {"name": "开场/规则说明", "file": None, "volume": 0.28, "loop": True},
    "discussion": {"name": "讨论阶段", "file": None, "volume": 0.22, "loop": True},
    "search": {"name": "搜证阶段", "file": None, "volume": 0.28, "loop": True},
    "suspense": {"name": "悬疑/紧张", "file": None, "volume": 0.3, "loop": True},
    "confrontation": {"name": "对峙阶段", "file": None, "volume": 0.34, "loop": True},
    "ending": {"name": "结局演绎", "file": None, "volume": 0.36, "loop": False},
    "happy_ending": {"name": "Happy Ending", "file": None, "volume": 0.34, "loop": False},
    "bad_ending": {"name": "Bad Ending", "file": None, "volume": 0.32, "loop": False},
    "silence": {"name": "静音", "file": None, "volume": 0.0, "loop": False},
}


PHASE_TO_SCENE_FALLBACK: Dict[str, str] = {
    "opening": "opening",
    "opening_rules": "opening",
    "discussion": "discussion",
    "search": "search",
    "vote": "suspense",
    "owner_confrontation": "confrontation",
    "ending": "ending",
}


NON_LOOP_MOODS = {"revelatory", "regretful", "melancholic", "triumphant"}


MOOD_VOLUME_HINT: Dict[str, float] = {
    "warm": 0.26,
    "calm": 0.2,  # 讨论阶段低调，不打扰玩家交流
    "playful": 0.24,
    "romantic": 0.24,
    "dreamy": 0.24,
    "lonely": 0.24,
    "melancholic": 0.28,
    "regretful": 0.28,
    "hopeful": 0.26,
    "uplifting": 0.3,
    "triumphant": 0.32,
    "mysterious": 0.28,
    "uneasy": 0.3,
    "suspenseful": 0.32,
    "horrific": 0.34,
    "urgent": 0.35,
    "conflicted": 0.3,
    "dramatic": 0.34,
    "revelatory": 0.35,
    "chaotic": 0.35,
}


class BGMEngine:
    """
    BGM 背景音乐引擎

    核心方法:
    - play(scene): 播放场景音乐 (传统单文件模式)
    - play_mood(mood): 播放情绪音乐 (多曲目随机模式)
    - play_for_phase(phase): 根据游戏阶段自动选择播放模式
    - set_auto_mood(enabled): 开关自动情绪映射

    状态变量:
    - current_scene: 当前播放的场景名称
    - current_mood: 当前播放的情绪 slug
    - auto_mood_enabled: 自动情绪映射开关 (启动时根据音效库自动判断)
    - master_volume: 全局音量 (0.0-1.0)

    文件结构:
    - music/<scene>.mp3: 场景音乐 (opening/discussion/search 等)
    - music/moods/<mood_slug>/*.mp3: 情绪音乐 (warm/calm/.../chaotic)
    - music/moods/index.json: 情绪音乐索引 (download_moods_freesound.py 生成)
    """

    def __init__(self, music_dir: Optional[str] = None):
        """
        初始化 BGM 引擎。

        参数:
            music_dir: 音乐文件目录 (默认 ./music)

        副作用:
            - 初始化 pygame.mixer (44.1kHz 立体声)
            - 扫描情绪音效库并加载到 mood_tracks
            - 检测是否有情绪音效，自动决定是否开启 auto_mood_enabled
        """
        if pygame.mixer.get_init() is not None:
            self.mixer_initialized = True
        else:
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
                self.mixer_initialized = True
            except Exception as exc:  # noqa: BLE001
                print(f"警告：音频初始化失败：{exc}")
                self.mixer_initialized = False

        if music_dir is None:
            music_dir = os.path.join(os.path.dirname(__file__), "music")
        self.music_dir = music_dir
        self.mood_music_dir = os.path.join(self.music_dir, "moods")
        self.mood_index_path = os.path.join(self.mood_music_dir, "index.json")

        self.current_scene = "silence"
        self.current_mood: Optional[str] = None
        self.is_playing = False
        self.master_volume = 0.4
        self.auto_mood_enabled = False  # 默认关闭，用户手动开启或检测到音效库后自动开启
        self.phase_to_mood_map = DEFAULT_PHASE_TO_MOOD.copy()
        self.ending_mood_map = DEFAULT_ENDING_MOOD.copy()
        self._rng = random.Random()

        self.bgm_configs = {scene: config.copy() for scene, config in BGM_CONFIGS.items()}
        self.mood_tracks: Dict[str, List[str]] = {}

        # 检测情绪音效库是否已下载
        if self._has_mood_music():
            self.auto_mood_enabled = True
            print("[BGM] 检测到情绪音效库，自动情绪映射已开启")
        else:
            print("[BGM] 未检测到情绪音效库，自动情绪映射已关闭（运行 python download_moods_freesound.py 下载）")

        if not os.path.exists(self.music_dir):
            os.makedirs(self.music_dir, exist_ok=True)
            self._create_music_readme()
        os.makedirs(self.mood_music_dir, exist_ok=True)
        self.refresh_mood_catalog()

    def _create_music_readme(self):
        readme_path = os.path.join(self.music_dir, "README.txt")
        with open(readme_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(
                "背景音乐文件目录\n"
                "================\n\n"
                "请将音乐文件放入此目录，并在 main.py 中配置 BGM_CONFIGS。\n\n"
                "推荐场景文件名：\n"
                "- opening.mp3: 开场音乐\n"
                "- discussion.mp3: 讨论音乐\n"
                "- search.mp3: 搜证音乐\n"
                "- suspense.mp3: 悬疑音乐\n"
                "- confrontation.mp3: 对峙音乐\n"
                "- ending.mp3: 结局音乐\n"
                "- happy_ending.mp3: Happy Ending\n"
                "- bad_ending.mp3: Bad Ending\n\n"
                "情绪音效目录：music/moods/<mood_slug>/*.mp3\n"
                "可通过脚本自动下载：python download_moods_freesound.py\n"
            )

    def set_music_dir(self, music_dir: str):
        self.music_dir = music_dir
        self.mood_music_dir = os.path.join(self.music_dir, "moods")
        self.mood_index_path = os.path.join(self.mood_music_dir, "index.json")
        os.makedirs(self.music_dir, exist_ok=True)
        os.makedirs(self.mood_music_dir, exist_ok=True)
        self.refresh_mood_catalog()

    def set_auto_mood(self, enabled: bool):
        self.auto_mood_enabled = enabled

    def is_auto_mood_enabled(self) -> bool:
        return self.auto_mood_enabled

    def resolve_scene_for_phase(self, phase: str) -> str:
        return PHASE_TO_SCENE_FALLBACK.get(phase, "discussion")

    def resolve_mood_for_phase(self, phase: str, reply_text: str = "") -> Optional[str]:
        """根据游戏阶段解析目标情绪（含低库存 fallback 逻辑）。

        核心流程：
        1. 根据阶段和结局类型解析目标情绪
        2. 检查该情绪曲目数量，若 < 3 条则自动 fallback 到替代情绪
        3. 返回最终情绪 slug

        Fallback 映射表（低库存情绪→替代情绪）：
        - revelatory (揭示) → dramatic (戏剧化)
        - triumphant (凯旋) → uplifting (振奋)
        - regretful (遗憾) → melancholic (忧郁)
        - urgent (紧急) → suspenseful (悬疑)
        - chaotic (混乱) → dramatic (戏剧化)

        参数:
            phase: 游戏阶段 (opening/discussion/vote/ending 等)
            reply_text: DM 回复文本 (用于结局类型判断)

        返回:
            str: 最终情绪 slug（可能经过 fallback）
        """
        if phase in {"ending", "owner_confrontation"}:
            ending_variant = self._detect_ending_variant(reply_text)
            if ending_variant == "happy":
                mood = self.ending_mood_map.get("happy", "triumphant")
            elif ending_variant == "bad":
                mood = self.ending_mood_map.get("bad", "regretful")
            else:
                mood = self.phase_to_mood_map.get(phase, self.ending_mood_map.get("default", "revelatory"))
        else:
            mood = self.phase_to_mood_map.get(phase)

        # 低库存 fallback：目标情绪曲目 < 3 条时，使用替代情绪
        if mood and len(self.mood_tracks.get(mood, [])) < 3:
            fallback = self._get_fallback_mood(mood)
            print(f"[BGM] {mood} 曲目不足 ({len(self.mood_tracks.get(mood, []))}条)，fallback 到 {fallback}")
            mood = fallback

        return mood

    def _get_fallback_mood(self, mood: str) -> str:
        """获取低库存情绪的替代情绪。

        参数:
            mood: 原始情绪 slug

        返回:
            str: 替代情绪 slug
        """
        FALLBACK_MAP = {
            "revelatory": "dramatic",    # 揭示→戏剧化（1 条→15 条）
            "triumphant": "uplifting",   # 凯旋→振奋（1 条→15 条）
            "regretful": "melancholic",  # 遗憾→忧郁（1 条→15 条）
            "urgent": "suspenseful",     # 紧急→悬疑（1 条→15 条）
            "chaotic": "dramatic",       # 混乱→戏剧化（0 条→15 条）
        }
        return FALLBACK_MAP.get(mood, mood)

    def _detect_ending_variant(self, reply_text: str) -> str:
        lowered = reply_text.lower()
        if "happy ending" in lowered or "诚实与救赎" in reply_text:
            return "happy"
        if "bad ending" in lowered or "谎言的代价" in reply_text:
            return "bad"
        return "default"

    def refresh_mood_catalog(self):
        tracks: Dict[str, List[str]] = {}
        loaded_from_index = False

        if os.path.exists(self.mood_index_path):
            try:
                with open(self.mood_index_path, "r", encoding="utf-8") as file_handle:
                    data = json.loads(file_handle.read())
            except (json.JSONDecodeError, OSError):
                data = []
            if isinstance(data, list):
                loaded_from_index = True
                for item in data:
                    mood = str(item.get("mood", "")).strip()
                    filename = str(item.get("filename", "")).strip()
                    if not mood or not filename:
                        continue
                    path = os.path.join(self.mood_music_dir, mood, filename)
                    if os.path.exists(path):
                        tracks.setdefault(mood, []).append(path)
        # 仅当 index.json 不存在或不可用时，回退到目录扫描模式。
        if not loaded_from_index:
            for mood in MOOD_PROFILES.keys():
                mood_dir = os.path.join(self.mood_music_dir, mood)
                if not os.path.isdir(mood_dir):
                    continue
                for file_name in os.listdir(mood_dir):
                    lowered = file_name.lower()
                    if not lowered.endswith((".mp3", ".ogg", ".wav", ".mid")):
                        continue
                    full_path = os.path.join(mood_dir, file_name)
                    if not os.path.isfile(full_path):
                        continue
                    tracks.setdefault(mood, []).append(full_path)

        normalized: Dict[str, List[str]] = {}
        for mood, items in tracks.items():
            unique = sorted(set(items))
            if unique:
                normalized[mood] = unique
        self.mood_tracks = normalized

    def _has_mood_music(self) -> bool:
        """检测是否有可用的情绪音效。"""
        self.refresh_mood_catalog()
        return len(self.mood_tracks) > 0 and any(len(items) > 0 for items in self.mood_tracks.values())

    def list_available_moods(self) -> List[str]:
        self.refresh_mood_catalog()
        return sorted(self.mood_tracks.keys())

    def get_mood_catalog(self) -> Dict[str, int]:
        self.refresh_mood_catalog()
        catalog = {mood: 0 for mood in MOOD_PROFILES.keys()}
        for mood, items in self.mood_tracks.items():
            catalog[mood] = len(items)
        return catalog

    def _get_music_path(self, scene: str) -> Optional[str]:
        config = self.bgm_configs.get(scene, {})
        music_file = config.get("file")

        if isinstance(music_file, str) and music_file:
            path = os.path.join(self.music_dir, music_file)
            if os.path.exists(path):
                return path

        default_file = f"{scene}.mp3"
        path = os.path.join(self.music_dir, default_file)
        if os.path.exists(path):
            if scene in self.bgm_configs:
                self.bgm_configs[scene]["file"] = default_file
            return path

        for ext in [".ogg", ".wav", ".mid"]:
            path = os.path.join(self.music_dir, f"{scene}{ext}")
            if os.path.exists(path):
                if scene in self.bgm_configs:
                    self.bgm_configs[scene]["file"] = f"{scene}{ext}"
                return path

        return None

    def play(self, scene: str = "discussion", fade_ms: int = 1000) -> bool:
        """
        播放场景音乐 (传统单文件模式)。

        参数:
            scene: 场景名称 (opening/discussion/search/suspense/confrontation/ending 等)
            fade_ms: 淡入时间 (毫秒，默认 1000)

        返回:
            bool: 是否成功开始播放

        文件查找顺序:
            1. BGM_CONFIGS[scene]["file"] 指定文件
            2. <scene>.mp3
            3. <scene>.ogg / .wav / .mid
        """

        if not self.mixer_initialized:
            return False

        music_path = self._get_music_path(scene)
        if not music_path:
            self.current_scene = scene
            self.current_mood = None
            return False

        try:
            volume = float(self.bgm_configs.get(scene, {}).get("volume", 0.5))
            pygame.mixer.music.set_volume(volume * self.master_volume)
            pygame.mixer.music.load(music_path)
            loop = -1 if bool(self.bgm_configs.get(scene, {}).get("loop", True)) else 0
            pygame.mixer.music.play(loops=loop, fade_ms=fade_ms)
            self.current_scene = scene
            self.current_mood = None
            self.is_playing = True
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"BGM 播放失败：{exc}")
            return False

    def play_mood(self, mood: str, fade_ms: int = 1000) -> bool:
        """
        播放情绪音乐 (多曲目随机模式)。

        参数:
            mood: 情绪 slug (warm/calm/.../chaotic)
            fade_ms: 淡入时间 (毫秒，默认 1000)

        返回:
            bool: 是否成功开始播放

        行为:
            - 从该情绪的所有曲目中随机选择一首
            - revelatory/regretful/melancholic/triumphant 不循环播放
            - 其他情绪循环播放
        """

        if not self.mixer_initialized:
            return False

        self.refresh_mood_catalog()
        mood = mood.strip().lower()
        tracks = self.mood_tracks.get(mood, [])
        if not tracks:
            self.current_mood = mood
            return False

        track_path = self._rng.choice(tracks)
        try:
            volume = MOOD_VOLUME_HINT.get(mood, 0.5)
            pygame.mixer.music.set_volume(volume * self.master_volume)
            pygame.mixer.music.load(track_path)
            loop = 0 if mood in NON_LOOP_MOODS else -1
            pygame.mixer.music.play(loops=loop, fade_ms=fade_ms)
            self.current_scene = f"mood:{mood}"
            self.current_mood = mood
            self.is_playing = True
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"情绪音乐播放失败：{exc}")
            return False

    def play_for_phase(self, phase: str, reply_text: str = "", fade_ms: int = 1000) -> bool:
        """
        根据游戏阶段自动选择并播放音乐 (核心方法，main.py 调用)。

        参数:
            phase: 游戏阶段 (opening/discussion/vote/owner_confrontation/ending)
            reply_text: DM 回复文本 (用于结局类型判断)
            fade_ms: 淡入时间 (毫秒，默认 1000)

        返回:
            bool: 是否成功开始播放

        流程:
            1. 如果 auto_mood_enabled=True，解析情绪并调用 play_mood()
            2. 情绪播放失败或 auto_mood_enabled=False 时，回退到 play()
            3. 结局阶段根据 reply_text 判断 happy/bad 类型
        """
        if self.auto_mood_enabled:
            mood = self.resolve_mood_for_phase(phase, reply_text=reply_text)
            if mood and self.play_mood(mood, fade_ms=fade_ms):
                return True

        fallback_scene = self.resolve_scene_for_phase(phase)
        return self.play(fallback_scene, fade_ms=fade_ms)

    def stop(self, fade_ms: int = 1000) -> bool:
        if not self.mixer_initialized:
            return False

        try:
            pygame.mixer.music.fadeout(fade_ms)
        except Exception:
            pygame.mixer.music.stop()
        self.is_playing = False
        self.current_scene = "silence"
        self.current_mood = None
        return True

    def set_volume(self, volume: float) -> bool:
        if not self.mixer_initialized:
            return False

        self.master_volume = max(0.0, min(1.0, volume))

        if self.is_playing:
            if self.current_mood:
                mood_volume = MOOD_VOLUME_HINT.get(self.current_mood, 0.5)
                pygame.mixer.music.set_volume(mood_volume * self.master_volume)
            else:
                current_volume = float(self.bgm_configs.get(self.current_scene, {}).get("volume", 0.5))
                pygame.mixer.music.set_volume(current_volume * self.master_volume)

        return True

    def get_volume(self) -> float:
        return self.master_volume

    def toggle(self) -> bool:
        if self.is_playing:
            pygame.mixer.music.pause()
            return False
        pygame.mixer.music.unpause()
        return True

    def pause(self) -> bool:
        if not self.mixer_initialized:
            return False
        pygame.mixer.music.pause()
        return True

    def unpause(self) -> bool:
        if not self.mixer_initialized:
            return False
        pygame.mixer.music.unpause()
        return True

    def is_music_playing(self) -> bool:
        return self.is_playing and self.mixer_initialized

    def get_current_scene(self) -> str:
        return self.current_scene

    def get_current_mood(self) -> Optional[str]:
        return self.current_mood

    def unload(self):
        if self.mixer_initialized:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            self.mixer_initialized = False
