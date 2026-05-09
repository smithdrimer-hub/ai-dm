"""
语音合成模块 - 使用 ECNU 学校官方 TTS API

职责：
- 调用 ECNU TTS API 合成语音（支持多场景声音配置）
- 音频播放控制（加载、播放、停止）
- 长文本自动分割（避免 TTS 超时）

不负责的模块：
- BGM 播放 → bgm_engine.py
- 场景判断 → main.py 的 detect_tts_scene()

场景声音配置（VOICE_CONFIGS）：
- dm: 女声 xiayu，语速 1.0（默认 DM 旁白）
- owner: 男声 liwa，语速 1.15（业主愤怒）
- owner_forgiveness: 男声 liwa，语速 0.85（业主原谅）
- clue: 女声 xiayu，语速 0.9（线索公开）
- ending: 女声 xiayu，语速 0.85（结局演绎）
- ending_happy: 女声 xiayu，语速 0.9（Happy Ending）
- task: 女声 xiayu，语速 0.95（任务陈述）
"""

import os
import re
import hashlib
import tempfile
import threading
import pygame
import requests
from typing import Optional, Dict, List
from config import API_KEY, TTS_API_URL, TTS_MODEL, DEFAULT_VOICE, API_PROVIDER, TTS_TIMEOUT_SECONDS

# TTS API 配置（从 config.py 导入）
if API_PROVIDER != "ecnu" and TTS_API_URL is None:
    # 自定义 API 未配置 TTS 时，禁用 TTS
    TTS_AVAILABLE = False
    print("[TTS] 当前 API 未配置 TTS 功能，语音输出已禁用")
else:
    TTS_AVAILABLE = True
    ECNU_TTS_API_URL = TTS_API_URL
    ECNU_TTS_MODEL = TTS_MODEL or "ecnu-tts"

# 场景声音配置
# voice: xiayu (女声 - DM/旁白), liwa (男声 - 业主)
# speed: 0.25-4.0, 1.0 为正常语速
VOICE_CONFIGS: Dict[str, Dict[str, any]] = {
    "dm": {
        "name": "DM 旁白",
        "voice": "xiayu",   # 女声，温柔亲切
        "speed": 1.0,
    },
    "owner": {
        "name": "业主",
        "voice": "liwa",    # 男声，威严
        "speed": 1.15,      # 稍快，表现急促/愤怒
    },
    "owner_forgiveness": {
        "name": "业主原谅",
        "voice": "liwa",    # 男声
        "speed": 0.85,      # 缓慢，感性
    },
    "clue": {
        "name": "线索公开",
        "voice": "xiayu",   # 女声
        "speed": 0.9,       # 稍慢，营造神秘感
    },
    "ending": {
        "name": "结局演绎",
        "voice": "xiayu",   # 女声
        "speed": 0.85,      # 更慢，营造收尾氛围
    },
    "ending_happy": {
        "name": "Happy Ending 旁白",
        "voice": "xiayu",   # 女声
        "speed": 0.9,       # 温暖治愈
    },
    "task": {
        "name": "任务陈述",
        "voice": "xiayu",
        "speed": 0.95,      # 清晰稳重
    },
}


class TTSEngine:
    """
    TTS 语音合成引擎

    核心功能：
    - speak(): 合成并播放语音（支持长文本自动分割）
    - set_voice_for_scene(): 根据场景切换声音配置

    容错机制：
    - 连续失败 3 次后打印警告，调用方应降级到纯文字模式
    - 长文本自动按句号/问号/感叹号分割（最大 180 字/段）
    """

    def __init__(self, use_cache: bool = False):
        """
        初始化 TTS 引擎。

        参数:
            use_cache: 是否启用音频缓存（默认 False，开发阶段建议关闭）

        副作用:
            - 初始化 pygame.mixer（与 BGM/SFX 共用 44.1kHz 立体声）
            - 创建 requests.Session（复用 HTTP 连接）
        """
        self.use_cache = use_cache
        self.cache_dir = "audio_cache"
        if use_cache:
            os.makedirs(self.cache_dir, exist_ok=True)

        # 与 BGM/SFX 共用 mixer；TTS 使用保留 channel，避免占用 pygame.mixer.music。
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        pygame.mixer.set_num_channels(max(pygame.mixer.get_num_channels(), 16))
        pygame.mixer.set_reserved(1)
        self._tts_channel = pygame.mixer.Channel(0)
        self._active_sound = None

        # 当前声音配置
        self.current_voice_config = VOICE_CONFIGS["dm"].copy()

        # 创建 Session 复用连接
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {API_KEY}",
        })

        # 连续失败计数，用于自动降级
        self.consecutive_failures = 0
        self.max_failures_before_disable = 3

        # 播放锁，防止并发调用导致状态混乱
        self._play_lock = threading.Lock()

    def set_voice_for_scene(self, scene: str):
        """根据场景切换声音配置"""
        if scene in VOICE_CONFIGS:
            self.current_voice_config = VOICE_CONFIGS[scene].copy()
        else:
            self.current_voice_config = VOICE_CONFIGS["dm"].copy()

    def _split_long_text(self, text: str, max_length: int = 180) -> List[str]:
        """将长文本按标点符号分割成多个片段，避免 TTS 超时。

        Args:
            text: 要分割的文本
            max_length: 每段最大字符数

        Returns:
            分割后的文本片段列表
        """
        # 按句号、问号、感叹号、换行分割，保留分隔符
        segments = re.split(r'([。！？!?\n]+)', text)

        result = []
        current = ""

        for segment in segments:
            if len(current) + len(segment) > max_length:
                if current:
                    result.append(current)
                # 如果单段过长，强制分割
                if len(segment) > max_length:
                    result.append(segment[:max_length])
                    current = segment[max_length:]
                else:
                    current = segment
            else:
                current += segment

        if current:
            result.append(current)

        return result

    def _synthesize_and_play(self, text: str, blocking: bool = True) -> bool:
        """合成并播放单段语音（内部方法）。

        Args:
            text: 要播放的文本
            blocking: 是否阻塞等待播放完成

        Returns:
            是否成功
        """
        # 使用唯一临时文件名，避免并发冲突
        if self.use_cache:
            output_path = self._get_cache_path(text)
            is_temp_file = False
        else:
            fd, output_path = tempfile.mkstemp(suffix='.mp3')
            os.close(fd)  # 关闭文件描述符，只保留路径
            is_temp_file = True

        # 调用 API 合成
        if not self._synthesize(text, output_path):
            if is_temp_file:
                try:
                    os.unlink(output_path)
                except OSError:
                    pass
            return False

        # 播放音频（加锁保护，防止并发调用导致状态混乱）
        try:
            with self._play_lock:
                self._active_sound = pygame.mixer.Sound(output_path)
                self._tts_channel.play(self._active_sound)

                if blocking:
                    # 等待播放完成
                    while self._tts_channel.get_busy():
                        pygame.time.Clock().tick(10)

                # 清理临时文件（缓存模式下保留）
                if is_temp_file:
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass

            return True

        except Exception as e:
            print(f"音频播放失败：{e}")
            if is_temp_file:
                try:
                    os.unlink(output_path)
                except OSError:
                    pass
            return False

    def _get_cache_path(self, text: str) -> str:
        """根据文本生成缓存文件路径"""
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        voice_id = self.current_voice_config["voice"]
        speed_id = str(self.current_voice_config["speed"]).replace(".", "_")
        return os.path.join(self.cache_dir, f"{voice_id}_{speed_id}_{text_hash}.mp3")

    def _synthesize(self, text: str, output_path: str) -> bool:
        """
        调用学校 API 合成语音
        :param text: 要合成的文本
        :param output_path: 输出文件路径
        :return: 是否成功
        """
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": ECNU_TTS_MODEL,
            "input": text,
            "voice": self.current_voice_config["voice"],
            "speed": float(self.current_voice_config["speed"]),
            "response_format": "mp3",
        }

        try:
            response = self.session.post(
                ECNU_TTS_API_URL,
                headers=headers,
                json=payload,
                timeout=TTS_TIMEOUT_SECONDS,
            )

            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            else:
                print(f"TTS API 失败：{response.status_code} - {response.text[:200]}")
                return False

        except Exception as e:
            print(f"TTS 请求异常：{e}")
            return False

    def speak(self, text: str, scene: str = "dm", blocking: bool = True) -> bool:
        """
        合成并播放语音（支持长文本自动分割）。

        核心方法，外部调用此方法来播放语音。

        参数:
            text: 要播放的文本内容
            scene: 场景类型，决定声音配置
                - "dm": 默认 DM 旁白（女声，1.0 倍速）
                - "owner": 业主愤怒（男声，1.15 倍速）
                - "owner_forgiveness": 业主原谅（男声，0.85 倍速）
                - "clue": 线索公开（女声，0.9 倍速）
                - "ending": 结局演绎（女声，0.85 倍速）
                - "ending_happy": Happy Ending（女声，0.9 倍速）
                - "task": 任务陈述（女声，0.95 倍速）
            blocking: 是否阻塞等待播放完成（默认 True）

        返回:
            bool: 所有片段是否都成功播放

        流程:
            1. 根据 scene 切换声音配置
            2. 按标点符号分割长文本（最大 180 字/段）
            3. 逐段调用 _synthesize_and_play()
            4. 失败次数累加到 consecutive_failures

        注意:
            返回 False 不意味着完全失败，可能是部分片段失败。
            调用方应检查 consecutive_failures 决定是否降级到纯文字模式。
        """
        # 切换声音配置
        self.set_voice_for_scene(scene)

        # 分割长文本
        segments = self._split_long_text(text)
        all_success = True

        for i, segment in enumerate(segments):
            segment = segment.strip()
            if not segment:
                continue

            if not self._synthesize_and_play(segment, blocking):
                self.consecutive_failures += 1
                all_success = False

                # 连续失败超过阈值，提示用户
                if self.consecutive_failures >= self.max_failures_before_disable:
                    print(f"⚠️ TTS 连续失败{self.consecutive_failures}次，建议检查网络或 API Key")
                else:
                    print(f"⚠️ TTS 第{i+1}段 ({len(segment)}字) 合成失败，继续尝试")
            else:
                self.consecutive_failures = 0

        return all_success

    def stop(self):
        """停止当前播放"""
        self._tts_channel.stop()

    def unload(self):
        """卸载引擎（退出时调用）"""
        self._tts_channel.stop()
        self.session.close()
