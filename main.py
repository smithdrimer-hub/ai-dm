"""命令行入口 - 整合 DM/TTS/BGM 三大模块

2026-04-21 变更说明:
- 同步 20 类情绪桶后的自动切歌兼容。
- 修复 /search 分支中的非 ASCII 引号导致的语法错误。
2026-04-23 变更说明:
- 新增 /sfx 命令族（on/off/volume/status/event/category）。
- 新增 SFX 阶段触发逻辑（phase transition、vote、ending 等）。

职责:
- 初始化 DMEngine、TTSEngine、BGMEngine
- 命令行交互循环 (input/print)
- 命令解析 (/bgm、/sound、/search、/vote 等)
- TTS 场景自动判断 (detect_tts_scene)
- BGM 自动切换 (auto_switch_bgm)

不负责:
- 游戏逻辑 → dm_engine.py
- 语音合成 → tts_engine.py
- 音乐播放 → bgm_engine.py

启动流程:
1. 初始化 tts、bgm、dm
2. 自动播放开场 BGM
3. 调用 dm.start_game() 获取开场白
4. 打印开场白 + 播放 TTS
5. 进入交互循环

交互循环:
1. 检查定时事件 (线索自动公开)
2. 获取玩家输入
3. 命令解析 (quit/reset/status/各类/bgm 命令)
4. 调用 dm.chat() 处理普通对话
5. 打印 DM 回复 + 自动切换 BGM + 播放 TTS"""

import argparse
import os
import shlex
import sys
import time
from typing import Optional

try:
    import msvcrt
except ImportError:  # 非 Windows 环境保留普通 input() 回退
    msvcrt = None

from bgm_engine import BGMEngine
from dm_engine import DMEngine
from sfx_engine import SFXEngine
from tts_engine import TTSEngine

# 初始化 TTS 引擎（第一版不建议缓存）
tts = TTSEngine(use_cache=False)

# 初始化 BGM 引擎
bgm = BGMEngine()

# 初始化 SFX 引擎
sfx = SFXEngine()

# 全局开关
sound_enabled = True
bgm_enabled = True
sfx_enabled = True

# 阶段入场 SFX 只覆盖真正需要“提示玩家注意”的节点。
PHASE_ENTRY_SFX_EVENTS = {
    "vote": ("phase_transition", "suspense_raise"),
    "owner_confrontation": ("phase_transition", "conflict_hit"),
    "ending": ("ending_resolve",),
    "postgame_review": ("ending_resolve",),
}

BGM_DUCKING_MULTIPLIER = 0.55


def read_input_with_idle_events(prompt_text: str, idle_callback=None, poll_interval: float = 0.2) -> str:
    """
    Windows 下用非阻塞键盘轮询读取输入，让 DM 能在玩家长时间不输入时插话。

    非 Windows 或不支持 msvcrt 的环境会自动退回普通 input()；这样不会改变现有命令语义，
    只在可用的平台上增强“真实沉默计时”。
    """
    prompt = f"\n{prompt_text}: "
    if msvcrt is None:
        return input(prompt).strip()

    buffer: list[str] = []
    sys.stdout.write(prompt)
    sys.stdout.flush()

    while True:
        if msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                sys.stdout.write("\n")
                return "".join(buffer).strip()
            if char == "\003":
                raise KeyboardInterrupt
            if char in ("\x00", "\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getwch()
                continue
            if char == "\b":
                if buffer:
                    buffer.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char >= " ":
                buffer.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
        else:
            if idle_callback and not buffer and idle_callback():
                sys.stdout.write(prompt)
                sys.stdout.flush()
            time.sleep(poll_interval)


def print_help():
    """打印可用命令。"""
    print("可用命令：")
    print("  quit              退出程序")
    print("  reset             重置整局游戏")
    print("  status            查看当前游戏状态")
    print("  /clue1            公开线索 1")
    print("  /clue2            公开线索 2")
    print("  /phase next       推进到下一个 schema 阶段")
    print("  /packet [角色名]  主持人查看已解锁私密角色包")
    print("  /schema submit actor=<id> form=<id> action=<ACTION> target=<id> vote=<id> declaration=\"...\"")
    print("  /schema resolve   结算 schema action/form runtime")
    print("  /schema reveal [code_word=...]  推进 schema final_reveal_sequence")
    print("  /search [地点]     搜索指定地点（讨论 10 分钟后开放）")
    print("  /vote             进入最终公开答案阶段")
    print("  /review           结局后进入完整结构化复盘")
    print("  /save [文件名]     保存游戏进度")
    print("  /load [文件名]     读取游戏进度")
    print("  /sound on/off     开关语音输出")
    print("  /sound test       测试语音输出")
    print("  /bgm on/off       开关背景音乐")
    print("  /bgm volume [0-1] 设置背景音乐音量")
    print("  /bgm mood list    显示可用情绪及数量")
    print("  /bgm mood [slug]  手动切换到指定情绪")
    print("  /bgm auto on/off  开关自动情绪映射")
    print("  /sfx on/off       开关 SFX 播放")
    print("  /sfx volume [0-1] 设置 SFX 全局音量")
    print("  /sfx status       查看 SFX 类别与事件状态")
    print("  /sfx event [name] 手动触发事件音效")
    print("  /sfx category list|[slug]  列出或手动播放分类 SFX")
    print("  角色名            当 DM 正在确认插话人时，只输入角色名完成确认")


def detect_tts_scene(reply: str) -> str:
    """
    根据 DM 回复内容自动判断 TTS 场景。

    匹配规则 (按优先级):
    - 任务陈述 → task (女声清晰)
    - 业主说/业主:/业主喊道 → owner (男声愤怒)
    - 原谅/复活 → owner_forgiveness (男声缓慢)
    - Happy Ending/后续故事 → ending_happy (女声温暖)
    - Bad Ending/谎言的代价 → ending (女声收尾)
    - 游戏结束 (排除真相揭晓) → ending
    - 线索 + 公开/收到/发现 → clue (女声神秘)
    - 其他 → dm (默认女声)

    参数:
        reply: DM 回复文本

    返回:
        str: 场景名称 (用于 tts.speak(scene=...))
    """
    scene = "dm"

    # 任务陈述（新增）
    if "你们的任务" in reply or "找出以下" in reply or "三道问题" in reply:
        scene = "task"

    # Happy Ending
    elif "Happy Ending" in reply or "幸福地生活" in reply or "后续故事" in reply:
        scene = "ending_happy"

    # Bad Ending（更精确）
    elif "Bad Ending" in reply or "谎言的代价" in reply:
        scene = "ending"

    # 游戏结束（排除真相揭晓时的误判）
    elif "游戏结束" in reply and "真相" not in reply:
        scene = "ending"

    # 业主说（兼容全角/半角冒号）
    elif "业主说" in reply or "业主：" in reply or "业主:" in reply or "业主喊道" in reply:
        scene = "owner"

    # 业主原谅
    elif "原谅" in reply or "复活" in reply:
        scene = "owner_forgiveness"

    # 线索公开
    elif "线索" in reply and ("公开" in reply or "收到" in reply or "发现" in reply):
        scene = "clue"

    return scene


def get_effective_phase_for_bgm(dm: DMEngine) -> str:
    """
    根据游戏状态返回有效的 phase key（用于 BGM 情绪映射）。

    讨论阶段细分逻辑：
    - 无线索 → "discussion" → calm
    - 线索 1 公开 → "discussion_clue1" → uneasy
    - 线索 2 公开 → "discussion_clue2" → suspenseful

    参数:
        dm: DMEngine 实例（读取 game_phase 和 released_clues）

    返回:
        str: 细分后的 phase key
    """
    if dm.game_phase == "discussion":
        if "clue_2" in dm.released_clues:
            return "discussion_clue2"
        elif "clue_1" in dm.released_clues:
            return "discussion_clue1"
        return "discussion"
    if dm.game_phase == "postgame_review":
        return "ending"
    return dm.game_phase


def main():
    """
    主函数：启动命令行游戏。

    流程:
    1. 初始化 DMEngine
    2. 播放开场 BGM (根据 auto_mood 状态)
    3. 获取开场白并播放 TTS
    4. 进入交互循环:
       - 检查定时事件 (线索自动公开)
       - 解析命令 (quit/reset/status/各类/bgm 命令)
       - 处理普通对话 (dm.chat)
       - 自动切换 BGM + 播放 TTS
    """
    global sound_enabled, bgm_enabled, sfx_enabled

    parser = argparse.ArgumentParser(description="AI murder mystery DM", add_help=True)
    parser.add_argument("--script-id", default=None, help="ScriptSchema script_id, e.g. second_sample")
    parser.add_argument("--schema-path", default=None, help="Path to a ScriptSchema v0.2.1 JSON file")
    parser.add_argument("--no-schema", action="store_true", help="Disable schema shadow mode and use legacy demo data")
    args, _unknown = parser.parse_known_args()
    if args.no_schema:
        os.environ["AI_DM_SCHEMA_ENABLED"] = "0"

    dm = DMEngine(script_id=args.script_id, schema_path=args.schema_path)
    last_bgm_signature: Optional[str] = None
    last_phase_for_sfx: Optional[str] = dm.game_phase

    def auto_switch_bgm(reply_text: str = "", force: bool = False, phase_override: Optional[str] = None):
        """
        按当前阶段自动切换 BGM（含情绪映射 + 场景回退）。

        使用 get_effective_phase_for_bgm() 获取细分的 phase key，
        使讨论阶段根据线索公开情况使用不同情绪。
        """
        nonlocal last_bgm_signature
        if not bgm_enabled or not bgm.is_auto_mood_enabled():
            return
        effective_phase = phase_override or get_effective_phase_for_bgm(dm)
        mood = bgm.resolve_mood_for_phase(effective_phase, reply_text=reply_text)
        fallback_scene = bgm.resolve_scene_for_phase(effective_phase)
        signature = f"{effective_phase}|{mood or fallback_scene}"
        if not force and signature == last_bgm_signature:
            return
        if bgm.play_for_phase(effective_phase, reply_text=reply_text):
            last_bgm_signature = signature

    def trigger_sfx_event(event_name: str, force: bool = False) -> bool:
        """集中触发 SFX，便于保持“少而关键”的策略。"""
        if not sfx_enabled:
            return False
        return sfx.play_event(event_name, force=force)

    def auto_trigger_sfx_for_phase_change(force: bool = False):
        """当游戏阶段发生变化时，触发过渡与阶段专属事件。"""
        nonlocal last_phase_for_sfx
        current_phase = dm.game_phase
        if current_phase == last_phase_for_sfx:
            return False
        events = PHASE_ENTRY_SFX_EVENTS.get(current_phase, ())
        for event_name in events:
            trigger_sfx_event(event_name, force=force)
        last_phase_for_sfx = current_phase
        return bool(events)

    def speak_with_ducking(text: str, scene: str = "dm") -> bool:
        """播放 TTS 时临时压低 BGM，保证主持词清晰。"""
        original_volume = None
        should_duck = bgm_enabled and bgm.is_music_playing()
        if should_duck:
            original_volume = bgm.get_volume()
            bgm.set_volume(original_volume * BGM_DUCKING_MULTIPLIER)
        try:
            return tts.speak(text, scene=scene)
        finally:
            if should_duck and original_volume is not None:
                bgm.set_volume(original_volume)

    def handle_idle_intervention() -> bool:
        """处理玩家真实沉默后的 DM 插话；返回 True 时输入行会被重新打印。"""
        global sound_enabled
        reply = dm.poll_idle_intervention()
        if not reply:
            return False
        print(f"\nDM: {reply}")
        if bgm_enabled and bgm.is_auto_mood_enabled():
            auto_switch_bgm(reply_text=reply)
        if sound_enabled:
            if not speak_with_ducking(reply, scene=detect_tts_scene(reply)):
                print("⚠️ 语音输出失败，已切换到纯文字模式")
                sound_enabled = False
        return True

    print("=" * 50)
    print("欢迎来到中文 AI 剧本杀 DM")
    print(f"剧本：{dm.get_script_display_title()}")
    print(f"Schema shadow：{dm.schema_shadow_status}")
    print("=" * 50)
    print()
    print("【交互说明】")
    print("- DM 点名后，下一条输入默认属于该玩家")
    print("- DM 会在需要主持、追问、点名、发线索时发言")
    print("- 语音输出已开启（女声 DM，男声业主），输入 '/sound off' 可关闭")
    print("- 背景音乐已开启，输入 '/bgm off' 可关闭")
    print("- SFX 音效已开启，输入 '/sfx off' 可关闭")
    print("- 讨论 10 分钟后可输入 '/search [地点]' 搜索证据")
    print("- 结局后输入 '/review' 可进入完整结构化复盘，也可以直接追问")
    print("- 输入 '/save [文件名]' 保存游戏，'/load [文件名]' 读取")
    print()
    print_help()
    print()

    if bgm_enabled:
        if bgm.is_auto_mood_enabled():
            auto_switch_bgm(force=True)
        else:
            bgm.play("opening")
    trigger_sfx_event("opening_start", force=True)

    opening_reply = dm.start_game()
    auto_trigger_sfx_for_phase_change()
    if opening_reply:
        print(f"\nDM: {opening_reply}")
        if bgm_enabled and bgm.is_auto_mood_enabled():
            auto_switch_bgm(reply_text=opening_reply)
        if sound_enabled:
            if not speak_with_ducking(opening_reply, scene="dm"):
                print("⚠️ 语音输出失败，已切换到纯文字模式（可输入 /sound on 重新开启）")
                sound_enabled = False

    while True:
        for timed_reply in dm.poll_timed_events():
            print(f"\nDM: {timed_reply}")
            timed_clue_released = "【线索公开" in timed_reply or "【发现到的线索" in timed_reply
            if timed_clue_released:
                trigger_sfx_event("clue_reveal")
            if bgm_enabled and bgm.is_auto_mood_enabled():
                auto_switch_bgm(reply_text=timed_reply, force=timed_clue_released)
            if sound_enabled:
                scene = "clue" if timed_clue_released else detect_tts_scene(timed_reply)
                if not speak_with_ducking(timed_reply, scene=scene):
                    print("⚠️ 语音输出失败，已切换到纯文字模式")
                    sound_enabled = False

        prompt_text = dm.get_turn_prompt_text()
        user_input = read_input_with_idle_events(prompt_text, idle_callback=handle_idle_intervention)
        lowered = user_input.lower()

        # --- 命令处理 ---
        if lowered == "quit":
            if sound_enabled:
                speak_with_ducking("游戏结束，感谢游玩", scene="ending")
            print("游戏结束，再见")
            break

        if lowered == "reset":
            dm.reset()
            last_phase_for_sfx = dm.game_phase
            print("游戏已重置，重新开场")
            opening_reply = dm.start_game()
            auto_trigger_sfx_for_phase_change(force=True)
            if bgm_enabled:
                if bgm.is_auto_mood_enabled():
                    auto_switch_bgm(reply_text=opening_reply or "", force=True)
                else:
                    bgm.play("opening")
            trigger_sfx_event("opening_start", force=True)
            if opening_reply:
                print(f"\nDM: {opening_reply}")
                if sound_enabled:
                    if not speak_with_ducking(opening_reply, scene="dm"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if lowered == "status":
            print(f"\n{dm.get_status_text()}")
            continue

        if lowered.startswith("/phase"):
            parts = user_input.split()
            if len(parts) < 2:
                print("用法：/phase next 或 /phase [phase_id]")
                continue
            target_phase = None if parts[1].lower() == "next" else parts[1]
            clues_before = set(dm.released_clues)
            reply = dm.advance_schema_phase(target_phase)
            phase_changed = auto_trigger_sfx_for_phase_change()
            clue_released = bool(set(dm.released_clues) - clues_before)
            if reply:
                print(f"\nDM: {reply}")
                if clue_released:
                    trigger_sfx_event("clue_reveal")
                if bgm_enabled and bgm.is_auto_mood_enabled():
                    auto_switch_bgm(reply_text=reply, force=phase_changed or clue_released)
                if sound_enabled:
                    if not speak_with_ducking(reply, scene=detect_tts_scene(reply)):
                        print("语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if lowered.startswith("/packet"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                print("用法：/packet [角色名或 character_id]")
                continue
            packets = dm.get_unlocked_role_packets(parts[1].strip())
            if not packets:
                print("当前没有为该角色解锁的 role packet。")
                continue
            print("\n[主持人私密查看：不会进入公共知识或 TTS]")
            for packet in packets:
                title = packet.get("packet_id", "packet")
                visibility = packet.get("visibility", "")
                instruction = packet.get("reveal_instruction", "")
                content = packet.get("content", "")
                print(f"\n--- {title} ({visibility}, {instruction}) ---\n{content or '[内容为空或读取失败]'}")
            continue

        if lowered.startswith("/schema resolve"):
            reply = dm.resolve_schema_actions()
            print(f"\nDM: {reply}")
            continue

        if lowered.startswith("/schema reveal"):
            try:
                tokens = shlex.split(user_input)
            except ValueError as exc:
                print(f"schema reveal parse error: {exc}")
                continue
            values = {}
            positional = []
            for token in tokens[2:]:
                if "=" in token:
                    key, value = token.split("=", 1)
                    values[key.strip().lower()] = value.strip()
                else:
                    positional.append(token)
            code_word = values.get("code_word") or values.get("code") or (positional[0] if positional else "")
            condition = values.get("condition", "")
            reply = dm.reveal_next_schema_final_step(code_word=code_word, condition=condition)
            print(f"\nDM: {reply}")
            continue

        if lowered.startswith("/schema submit"):
            try:
                tokens = shlex.split(user_input)
            except ValueError as exc:
                print(f"schema submit parse error: {exc}")
                continue
            values = {}
            for token in tokens[2:]:
                if "=" not in token:
                    continue
                key, value = token.split("=", 1)
                values[key.strip().lower()] = value.strip()
            actor = values.pop("actor", "")
            form_id = values.pop("form", values.pop("form_id", ""))
            if not actor or not form_id:
                print("Usage: /schema submit actor=<role> form=<form_id> action=<ACTION> target=<role> vote=<role> declaration=\"...\"")
                continue
            reply = dm.submit_schema_form(actor, form_id, values)
            print(f"\nDM: {reply}")
            continue

        if lowered == "/sound on":
            sound_enabled = True
            print("√ 语音输出已开启")
            continue

        if lowered == "/sound off":
            sound_enabled = False
            print("√ 语音输出已关闭")
            tts.stop()
            continue

        if lowered == "/sound test":
            print("正在测试语音输出...")
            speak_with_ducking("你好，我是 DM。语音输出测试成功。", scene="dm")
            print("测试完成")
            continue

        if lowered.startswith("/bgm mood"):
            parts = user_input.split()
            if len(parts) >= 3 and parts[2].lower() == "list":
                catalog = bgm.get_mood_catalog()
                available = [f"{mood}({count})" for mood, count in catalog.items() if count > 0]
                if available:
                    print("可用情绪：" + "、".join(available))
                else:
                    print("当前没有可用情绪素材。请先运行：python download_moods_freesound.py")
                continue

            if len(parts) >= 3:
                mood_slug = parts[2].strip().lower()
                if bgm.play_mood(mood_slug):
                    print(f"√ 已切换到情绪：{mood_slug}")
                else:
                    available = bgm.list_available_moods()
                    print(f"未找到可播放的情绪素材：{mood_slug}")
                    if available:
                        print("当前可用：" + "、".join(available))
                continue

            print("用法：/bgm mood [slug] 或 /bgm mood list")
            continue

        if lowered.startswith("/bgm auto"):
            parts = lowered.split()
            if len(parts) >= 3 and parts[2] in {"on", "off"}:
                turn_on = parts[2] == "on"
                bgm.set_auto_mood(turn_on)
                print(f"√ 自动情绪映射已{'开启' if turn_on else '关闭'}")
                if turn_on and bgm_enabled:
                    auto_switch_bgm(force=True)
                continue
            print("用法：/bgm auto on 或 /bgm auto off")
            continue

        if lowered == "/bgm on":
            bgm_enabled = True
            if bgm.is_auto_mood_enabled():
                auto_switch_bgm(force=True)
            else:
                bgm.play("discussion")
            print("√ 背景音乐已开启")
            continue

        if lowered == "/bgm off":
            bgm_enabled = False
            bgm.stop()
            last_bgm_signature = None
            print("√ 背景音乐已关闭")
            continue

        if lowered.startswith("/bgm volume"):
            try:
                volume = float(user_input.split()[-1])
                if 0 <= volume <= 1:
                    bgm.set_volume(volume)
                    print(f"√ 背景音乐音量设置为 {volume}")
                else:
                    print("音量必须在 0-1 之间")
            except (ValueError, IndexError):
                print("用法：/bgm volume [0-1]，例如 /bgm volume 0.5")
            continue

        if lowered == "/sfx on":
            sfx_enabled = True
            sfx.set_enabled(True)
            sfx.refresh()
            print("♫ SFX 音效已开启")
            continue

        if lowered == "/sfx off":
            sfx_enabled = False
            sfx.set_enabled(False)
            print("♫ SFX 音效已关闭")
            continue

        if lowered.startswith("/sfx volume"):
            try:
                volume = float(user_input.split()[-1])
                if 0 <= volume <= 1:
                    sfx.set_volume(volume)
                    print(f"♫ SFX 音量设置为 {volume}")
                else:
                    print("音量必须在 0-1 之间")
            except (ValueError, IndexError):
                print("用法：/sfx volume [0-1]，例如 /sfx volume 0.6")
            continue

        if lowered == "/sfx status":
            status = sfx.get_status()
            categories = status.get("categories", {})
            events = status.get("events", [])
            print(f"SFX 开关：{'开' if status.get('enabled') else '关'}")
            print(f"Mixer 初始化：{'是' if status.get('mixer_initialized') else '否'}")
            print(f"当前音量：{status.get('volume')}")
            if isinstance(categories, dict) and categories:
                print("分类库存：" + "、".join(f"{name}({count})" for name, count in categories.items()))
            else:
                print("分类库存：空（请先运行 python download_sfx_library.py 下载）")
            if isinstance(events, list) and events:
                print("可用事件：" + "、".join(events))
            continue

        if lowered.startswith("/sfx event"):
            parts = user_input.split()
            if len(parts) >= 3:
                event_name = parts[2].strip()
                if sfx.play_event(event_name, force=True):
                    print(f"♫ 已触发事件音效：{event_name}")
                else:
                    print(f"事件音效触发失败：{event_name}（可能事件不存在、无素材或 mixer 不可用）")
            else:
                events = sfx.list_events()
                if events:
                    print("可用事件：" + "、".join(events))
                else:
                    print("当前没有可用事件，请检查 sfx_event_map.yaml")
            continue

        if lowered.startswith("/sfx category"):
            parts = user_input.split()
            if len(parts) >= 3 and parts[2].lower() == "list":
                catalog = sfx.get_catalog()
                if catalog:
                    print("可用分类：" + "、".join(f"{name}({count})" for name, count in catalog.items()))
                else:
                    print("当前没有可用 SFX 分类，请先下载素材。")
                continue
            if len(parts) >= 3:
                category = parts[2].strip().lower()
                if sfx.play_category(category, force=True):
                    print(f"♫ 已播放分类音效：{category}")
                else:
                    print(f"分类音效播放失败：{category}（可能不存在或无可用素材）")
                continue
            print("用法：/sfx category list 或 /sfx category [slug]")
            continue

        if lowered.startswith("/save"):
            parts = user_input.split()
            filename = parts[1] if len(parts) >= 2 else "savegame"
            success, message = dm.save_game(filename)
            print(message)
            continue

        if lowered.startswith("/load"):
            parts = user_input.split()
            filename = parts[1] if len(parts) >= 2 else "savegame"
            success, message = dm.load_game(filename)
            print(message)
            if success and bgm_enabled:
                if bgm.is_auto_mood_enabled():
                    auto_switch_bgm(force=True)
                else:
                    phase = dm.game_phase
                    if phase == "discussion":
                        bgm.play("discussion")
                    elif phase == "vote":
                        bgm.play("suspense")
                    elif phase == "owner_confrontation":
                        bgm.play("confrontation")
                    elif phase in ("ending", "postgame_review"):
                        bgm.play("ending")
            if success:
                auto_trigger_sfx_for_phase_change(force=True)
            continue

        if lowered in {"/review", "review", "复盘", "完整复盘"}:
            if dm.game_phase not in ("ending", "postgame_review"):
                print("\nDM: 复盘会在结局后开放。现在请先完成当前游戏流程。")
                continue
            reply = dm.chat(user_input)
            phase_changed = auto_trigger_sfx_for_phase_change()
            if reply:
                print(f"\nDM: {reply}")
                if bgm_enabled and bgm.is_auto_mood_enabled():
                    auto_switch_bgm(reply_text=reply, force=phase_changed)
                if sound_enabled:
                    if not speak_with_ducking(reply, scene="ending"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input == "/clue1":
            clues_before = set(dm.released_clues)
            reply = dm.release_clue("clue_1")
            clue_released = bool(set(dm.released_clues) - clues_before)
            if reply:
                print(f"\nDM: {reply}")
                if clue_released:
                    trigger_sfx_event("clue_reveal")
                if clue_released and bgm_enabled and bgm.is_auto_mood_enabled():
                    auto_switch_bgm(reply_text=reply, force=True)
                if sound_enabled:
                    if not speak_with_ducking(reply, scene="clue"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input == "/clue2":
            clues_before = set(dm.released_clues)
            reply = dm.release_clue("clue_2")
            clue_released = bool(set(dm.released_clues) - clues_before)
            if reply:
                print(f"\nDM: {reply}")
                if clue_released:
                    trigger_sfx_event("clue_reveal")
                if clue_released and bgm_enabled and bgm.is_auto_mood_enabled():
                    auto_switch_bgm(reply_text=reply, force=True)
                if sound_enabled:
                    if not speak_with_ducking(reply, scene="clue"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input == "/vote":
            reply = dm.start_vote()
            auto_trigger_sfx_for_phase_change(force=True)
            if reply:
                print(f"\nDM: {reply}")
                if sound_enabled:
                    if not speak_with_ducking(reply, scene="dm"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
                if bgm_enabled:
                    if bgm.is_auto_mood_enabled():
                        auto_switch_bgm(reply_text=reply, force=True)
                    else:
                        bgm.play("suspense")
            continue

        if lowered.startswith("/search") or user_input.startswith("/搜索"):
            evidence_before_search = set(dm.found_evidence)
            reply = dm.chat(user_input)
            auto_trigger_sfx_for_phase_change()
            found_new_evidence = bool(set(dm.found_evidence) - evidence_before_search)
            if reply:
                print(f"\nDM: {reply}")
                if found_new_evidence:
                    trigger_sfx_event("search_action")
                if bgm_enabled and bgm.is_auto_mood_enabled():
                    if found_new_evidence:
                        auto_switch_bgm(reply_text=reply, force=True, phase_override="search")
                if sound_enabled:
                    if not speak_with_ducking(reply, scene=detect_tts_scene(reply)):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if not user_input:
            print("请输入内容")
            continue

        # --- 普通对话处理 ---
        reply = dm.chat(user_input)
        phase_changed = auto_trigger_sfx_for_phase_change()
        if reply:
            print(f"\nDM: {reply}")
            if bgm_enabled and bgm.is_auto_mood_enabled():
                auto_switch_bgm(
                    reply_text=reply,
                    force=phase_changed and dm.game_phase in PHASE_ENTRY_SFX_EVENTS,
                )
            if sound_enabled:
                # 根据游戏阶段优先使用明确场景，避免文本匹配误判
                if dm.game_phase == "opening_rules":
                    scene = "task"  # 开场白流程（规则确认/戏剧演绎/剧本朗读/任务陈述）
                elif dm.game_phase == "owner_confrontation":
                    scene = "owner"  # 业主对峙使用男声愤怒
                elif dm.game_phase == "ending":
                    scene = detect_tts_scene(reply)  # 结局根据文本判断 happy/bad
                else:
                    scene = detect_tts_scene(reply)

                if not speak_with_ducking(reply, scene=scene):
                    print("⚠️ 语音输出失败，已切换到纯文字模式")
                    sound_enabled = False

    tts.unload()
    bgm.unload()
    sfx.unload()


if __name__ == "__main__":
    main()
