"""
背景音乐播放模块
提供场景背景音乐播放功能
支持场景切换、音量控制、淡入淡出效果
"""

import os
import pygame
from typing import Optional, Dict


# 场景音乐配置
# 注意：需要用户自行准备音乐文件，或使用默认占位符
BGM_CONFIGS: Dict[str, Dict[str, str]] = {
    "opening": {
        "name": "开场/规则说明",
        "file": None,  # 需要用户配置
        "volume": 0.5,
        "loop": True,
    },
    "discussion": {
        "name": "讨论阶段",
        "file": None,
        "volume": 0.4,
        "loop": True,
    },
    "search": {
        "name": "搜证阶段",
        "file": None,
        "volume": 0.45,
        "loop": True,
    },
    "suspense": {
        "name": "悬疑/紧张",
        "file": None,
        "volume": 0.5,
        "loop": True,
    },
    "confrontation": {
        "name": "对峙阶段",
        "file": None,
        "volume": 0.55,
        "loop": True,
    },
    "ending": {
        "name": "结局演绎",
        "file": None,
        "volume": 0.6,
        "loop": False,
    },
    "happy_ending": {
        "name": "Happy Ending",
        "file": None,
        "volume": 0.6,
        "loop": False,
    },
    "bad_ending": {
        "name": "Bad Ending",
        "file": None,
        "volume": 0.5,
        "loop": False,
    },
    "silence": {
        "name": "静音",
        "file": None,
        "volume": 0.0,
        "loop": False,
    },
}


class BGMEngine:
    """背景音乐播放引擎"""

    def __init__(self, music_dir: Optional[str] = None):
        """
        初始化 BGM 引擎
        :param music_dir: 音乐文件目录，默认为项目根目录下的 music 文件夹
        """
        # 初始化 pygame 混音器
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
            self.mixer_initialized = True
        except Exception as e:
            print(f"警告：音频初始化失败：{e}")
            self.mixer_initialized = False

        # 设置音乐目录
        if music_dir is None:
            music_dir = os.path.join(os.path.dirname(__file__), "music")
        self.music_dir = music_dir

        # 当前状态
        self.current_scene = "silence"
        self.is_playing = False
        self.master_volume = 0.5  # 主音量 0-1

        # 加载配置
        self.bgm_configs = BGM_CONFIGS.copy()

        # 创建音乐目录（如果不存在）
        if not os.path.exists(self.music_dir):
            os.makedirs(self.music_dir, exist_ok=True)
            self._create_music_readme()

    def _create_music_readme(self):
        """创建音乐目录说明文件"""
        readme_path = os.path.join(self.music_dir, "README.txt")
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(
                "背景音乐文件目录\n"
                "================\n\n"
                "请将音乐文件放入此目录，并在 main.py 中配置 BGM_CONFIGS。\n\n"
                "推荐的音乐文件格式：\n"
                "- opening.mp3: 开场音乐（轻松、友好）\n"
                "- discussion.mp3: 讨论背景音乐（轻柔、不干扰）\n"
                "- suspense.mp3: 悬疑音乐（紧张氛围）\n"
                "- confrontation.mp3: 对峙音乐（激烈、紧张）\n"
                "- ending.mp3: 结局音乐（感人类）\n"
                "- happy_ending.mp3: Happy Ending 专用（温暖、希望）\n"
                "- bad_ending.mp3: Bad Ending 专用（悲伤、遗憾）\n\n"
                "如果找不到合适的音乐，可以使用免费音效网站：\n"
                "- 耳聆网：https://www.soundverse.net/\n"
                "- FreeSound：https://freesound.org/\n"
                "- YouTube Audio Library\n"
            )

    def set_music_dir(self, music_dir: str):
        """设置音乐文件目录"""
        self.music_dir = music_dir
        if not os.path.exists(music_dir):
            os.makedirs(music_dir, exist_ok=True)

    def _get_music_path(self, scene: str) -> Optional[str]:
        """获取音乐文件路径"""
        config = self.bgm_configs.get(scene, {})
        music_file = config.get("file")

        # 如果配置了具体文件名
        if music_file:
            path = os.path.join(self.music_dir, music_file)
            if os.path.exists(path):
                return path

        # 尝试使用场景名作为文件名
        default_file = f"{scene}.mp3"
        path = os.path.join(self.music_dir, default_file)
        if os.path.exists(path):
            # 更新配置
            self.bgm_configs[scene]["file"] = default_file
            return path

        # 尝试其他常见格式
        for ext in ['.ogg', '.wav', '.mid']:
            path = os.path.join(self.music_dir, f"{scene}{ext}")
            if os.path.exists(path):
                self.bgm_configs[scene]["file"] = f"{scene}{ext}"
                return path

        return None

    def play(self, scene: str = "discussion", fade_ms: int = 1000) -> bool:
        """
        播放指定场景的背景音乐
        :param scene: 场景名称
        :param fade_ms: 淡入时间（毫秒）
        :return: 是否成功
        """
        if not self.mixer_initialized:
            return False

        # 检查文件是否存在
        music_path = self._get_music_path(scene)
        if not music_path:
            # 静默失败（不打印错误，避免干扰游戏）
            self.current_scene = scene
            return False

        try:
            # 设置音量
            volume = self.bgm_configs.get(scene, {}).get("volume", 0.5)
            pygame.mixer.music.set_volume(volume * self.master_volume)

            # 加载并播放
            pygame.mixer.music.load(music_path)
            loop = -1 if self.bgm_configs.get(scene, {}).get("loop", True) else 0
            pygame.mixer.music.play(loops=loop, fade_ms=fade_ms)

            self.current_scene = scene
            self.is_playing = True
            return True

        except Exception as e:
            print(f"BGM 播放失败：{e}")
            return False

    def stop(self, fade_ms: int = 1000) -> bool:
        """
        停止背景音乐
        :param fade_ms: 淡出时间（毫秒）
        :return: 是否成功
        """
        if not self.mixer_initialized:
            return False

        try:
            pygame.mixer.music.fadeout(fade_ms)
            self.is_playing = False
            self.current_scene = "silence"
            return True
        except Exception:
            pygame.mixer.music.stop()
            self.is_playing = False
            self.current_scene = "silence"
            return True

    def set_volume(self, volume: float) -> bool:
        """
        设置主音量
        :param volume: 音量 0.0-1.0
        :return: 是否成功
        """
        if not self.mixer_initialized:
            return False

        self.master_volume = max(0.0, min(1.0, volume))

        # 如果正在播放，立即应用新音量
        if self.is_playing:
            current_volume = self.bgm_configs.get(self.current_scene, {}).get("volume", 0.5)
            pygame.mixer.music.set_volume(current_volume * self.master_volume)

        return True

    def get_volume(self) -> float:
        """获取当前主音量"""
        return self.master_volume

    def toggle(self) -> bool:
        """切换播放/暂停状态"""
        if self.is_playing:
            pygame.mixer.music.pause()
            return False
        else:
            pygame.mixer.music.unpause()
            return True

    def pause(self) -> bool:
        """暂停背景音乐"""
        if not self.mixer_initialized:
            return False
        pygame.mixer.music.pause()
        return True

    def unpause(self) -> bool:
        """恢复播放"""
        if not self.mixer_initialized:
            return False
        pygame.mixer.music.unpause()
        return True

    def is_music_playing(self) -> bool:
        """检查是否正在播放"""
        return self.is_playing and self.mixer_initialized

    def get_current_scene(self) -> str:
        """获取当前场景"""
        return self.current_scene

    def unload(self):
        """卸载引擎（退出时调用）"""
        if self.mixer_initialized:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            self.mixer_initialized = False
