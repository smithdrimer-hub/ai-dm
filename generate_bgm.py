"""
背景音乐生成脚本（简化版 - 无需 numpy）
使用标准库生成简单的氛围音乐文件
用于测试目的，建议后续替换为真实音乐
"""

import math
import wave
import struct
import os

# 输出目录
MUSIC_DIR = os.path.join(os.path.dirname(__file__), "music")
os.makedirs(MUSIC_DIR, exist_ok=True)

# 音频参数
SAMPLE_RATE = 44100
DURATION_SECONDS = 60  # 每个音频 60 秒循环


def generate_sine_wave(frequency: float, duration: float, volume: float = 0.3) -> list:
    """生成正弦波"""
    samples = []
    num_samples = int(SAMPLE_RATE * duration)
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        sample = volume * math.sin(2 * math.pi * frequency * t)
        samples.append(sample)
    return samples


def generate_ambient_chord(root_freq: float, chord_type: str = "major", duration: float = 10.0) -> list:
    """
    生成环境和弦
    chord_type: "major", "minor", "suspense", "dark"
    """
    # 和弦频率比
    chord_ratios = {
        "major": [1, 1.25, 1.5, 2],      # 大三和弦
        "minor": [1, 1.2, 1.5, 2],       # 小三和弦
        "suspense": [1, 1.12, 1.5, 1.9], # 悬疑和弦
        "dark": [1, 1.07, 1.4, 1.85],    # 黑暗和弦
    }

    ratios = chord_ratios.get(chord_type, "major")

    # 生成每个音
    length = int(SAMPLE_RATE * duration)
    samples = [0.0] * length

    for i, ratio in enumerate(ratios):
        freq = root_freq * ratio
        volume = 0.2 / (i + 1)  # 高音递减

        for j in range(length):
            t = j / SAMPLE_RATE
            samples[j] += volume * math.sin(2 * math.pi * freq * t)

    # 添加淡入淡出
    fade_length = int(SAMPLE_RATE * 0.5)  # 0.5 秒淡入淡出
    for j in range(fade_length):
        fade_in = j / fade_length
        samples[j] *= fade_in

    for j in range(length - fade_length, length):
        fade_out = (length - j) / fade_length
        samples[j] *= fade_out

    return samples


def generate_drone(frequency: float, duration: float = 30.0, volume: float = 0.15) -> list:
    """生成低频持续音（drone）"""
    samples = []
    num_samples = int(SAMPLE_RATE * duration)

    for i in range(num_samples):
        t = i / SAMPLE_RATE
        # 基频 + 泛音
        sample = volume * math.sin(2 * math.pi * frequency * t)
        sample += 0.1 * volume * math.sin(2 * math.pi * frequency * 2 * t)
        sample += 0.05 * volume * math.sin(2 * math.pi * frequency * 3 * t)

        # 添加轻微的频率调制（营造不安感）
        modulation = 0.02 * math.sin(2 * math.pi * 0.5 * t)
        sample *= (1 + modulation)

        samples.append(sample)

    return samples


def save_wav(data: list, filename: str):
    """将列表保存为 WAV 文件"""
    # 转换为 16 位整数
    max_val = max(abs(max(data)), abs(min(data)))
    if max_val > 0:
        data = [x / max_val * 0.8 for x in data]  # 归一化到 80%

    wav_file = wave.open(filename, 'w')
    wav_file.setnchannels(1)  # 单声道
    wav_file.setsampwidth(2)  # 16 位
    wav_file.setframerate(SAMPLE_RATE)

    for sample in data:
        sample_int = int(sample * 32767)
        # 限制在 16 位范围内
        sample_int = max(-32768, min(32767, sample_int))
        wav_file.writeframes(struct.pack('h', sample_int))

    wav_file.close()


def generate_ambient_track(filename: str, base_freq: float, chord_type: str,
                           duration: float = 60.0, has_drone: bool = True):
    """生成完整的氛围音轨"""
    print(f"正在生成 {filename}...")

    # 生成环境和弦（每 10 秒一个）
    chord_duration = 10.0
    num_chords = int(duration / chord_duration)

    total_samples = int(SAMPLE_RATE * duration)
    audio = [0.0] * total_samples

    for i in range(num_chords):
        start_sample = int(i * chord_duration * SAMPLE_RATE)
        chord = generate_ambient_chord(base_freq, chord_type, chord_duration)

        # 混合
        for j, sample in enumerate(chord):
            if start_sample + j < total_samples:
                audio[start_sample + j] += sample

    # 添加低频持续音
    if has_drone:
        drone = generate_drone(base_freq / 2, duration, volume=0.1)
        for i in range(min(len(drone), len(audio))):
            audio[i] += drone[i]

    # 归一化并保存
    save_wav(audio, os.path.join(MUSIC_DIR, filename))
    print(f"  已生成：{filename}")


def main():
    """生成所有背景音乐文件"""
    print("=" * 50)
    print("背景音乐生成器（简化版）")
    print("=" * 50)
    print()
    print("正在生成氛围音乐文件（每个约 60 秒）...")
    print("这些是合成音乐，用于测试目的。")
    print("建议后续替换为真实音乐文件。")
    print()

    # 音乐配置：文件名，基频，和弦类型，是否有持续音
    tracks = [
        ("opening.wav", 261.63, "major", True),      # C4 - 开场（明亮）
        ("discussion.wav", 220.00, "major", True),   # A3 - 讨论（平静）
        ("search.wav", 246.94, "suspense", False),   # B3 - 搜证（好奇）
        ("suspense.wav", 110.00, "suspense", True),  # A2 - 悬疑（紧张）
        ("confrontation.wav", 98.00, "dark", True),  # G2 - 对峙（激烈）
        ("ending.wav", 196.00, "minor", True),       # G3 - 结局（感性）
        ("happy_ending.wav", 329.63, "major", True), # E4 - Happy Ending（温暖）
        ("bad_ending.wav", 130.81, "dark", True),    # C3 - Bad Ending（悲伤）
    ]

    for filename, freq, chord, drone in tracks:
        generate_ambient_track(filename, freq, chord, duration=30.0, has_drone=drone)

    print()
    print("=" * 50)
    print("生成完成！")
    print("=" * 50)
    print()
    print(f"音乐文件已保存到：{MUSIC_DIR}")
    print()
    print("注意：")
    print("- 这些是合成的氛围音乐，比较简约")
    print("- 建议后续从免费音效网站下载更好的音乐替换")
    print("- 推荐网站：https://freesound.org/, https://www.soundverse.net/")
    print()
    print("现在可以在游戏中输入 '/bgm on' 测试背景音乐！")


if __name__ == "__main__":
    main()
