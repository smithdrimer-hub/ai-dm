"""
语音合成模块 - 使用 ECNU 学校官方 TTS API
提供 OpenAI 兼容的文本转语音接口
支持多场景声音配置（DM 女声、业主男声等）
"""

import os
import re
import hashlib
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
    """语音合成引擎 - 使用 ECNU 学校 API"""

    def __init__(self, use_cache: bool = False):
        """
        初始化 TTS 引擎
        :param use_cache: 是否启用缓存（第一版建议 False）
        """
        self.use_cache = use_cache
        self.cache_dir = "audio_cache"
        if use_cache:
            os.makedirs(self.cache_dir, exist_ok=True)

        # 初始化 pygame 混音器
        pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)

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
        output_path = "temp_tts_output.mp3"
        if self.use_cache:
            output_path = self._get_cache_path(text)

        # 调用 API 合成
        if not self._synthesize(text, output_path):
            return False

        # 播放音频
        try:
            pygame.mixer.music.load(output_path)
            pygame.mixer.music.play()

            if blocking:
                # 等待播放完成
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)

            # 清理临时文件（缓存模式下保留）
            if not self.use_cache:
                pygame.mixer.music.unload()
                try:
                    os.unlink(output_path)
                except OSError:
                    pass

            return True

        except Exception as e:
            print(f"音频播放失败：{e}")
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
        合成并播放语音（支持长文本自动分割）
        :param text: 要播放的文本
        :param scene: 场景类型 ("dm", "owner", "clue", "ending", "task")
        :param blocking: 是否阻塞等待播放完成
        :return: 是否成功
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
        pygame.mixer.music.stop()

    def unload(self):
        """卸载引擎（退出时调用）"""
        pygame.mixer.quit()
        self.session.close()
