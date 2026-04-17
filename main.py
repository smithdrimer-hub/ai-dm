"""命令行入口，集成 TTS 语音输出和 BGM 背景音乐"""

from dm_engine import DMEngine
from tts_engine import TTSEngine
from bgm_engine import BGMEngine

# 初始化 TTS 引擎（第一版不建议缓存）
tts = TTSEngine(use_cache=False)

# 初始化 BGM 引擎
bgm = BGMEngine()

# 全局开关
sound_enabled = True
bgm_enabled = True


def print_help():
    """打印可用命令。"""
    print("可用命令：")
    print("  quit              退出程序")
    print("  reset             重置整局游戏")
    print("  status            查看当前游戏状态")
    print("  /clue1            公开线索 1")
    print("  /clue2            公开线索 2")
    print("  /search [地点]     搜索指定地点（讨论 10 分钟后开放）")
    print("  /vote             进入最终公开答案阶段")
    print("  /save [文件名]     保存游戏进度")
    print("  /load [文件名]     读取游戏进度")
    print("  /sound on/off     开关语音输出")
    print("  /sound test       测试语音输出")
    print("  /bgm on/off       开关背景音乐")
    print("  /bgm volume [0-1] 设置背景音乐音量")
    print("  角色名            当 DM 正在确认插话人时，只输入角色名完成确认")


def main():
    """启动命令行游戏。"""
    global sound_enabled, bgm_enabled

    dm = DMEngine()

    print("=" * 50)
    print("欢迎来到中文 AI 剧本杀 DM")
    print("剧本：《Monsters Halloween Night》")
    print("=" * 50)
    print()
    print("【交互说明】")
    print("- DM 点名后，下一条输入默认属于该玩家")
    print("- DM 会在需要主持、追问、点名、发线索时发言")
    print("- 语音输出已开启（女声 DM，男声业主），输入 '/sound off' 可关闭")
    print("- 背景音乐已开启，输入 '/bgm off' 可关闭")
    print("- 讨论 10 分钟后可输入 '/search [地点]' 搜索证据")
    print("- 输入 '/save [文件名]' 保存游戏，'/load [文件名]' 读取")
    print()
    print_help()
    print()

    # 播放开场 BGM
    if bgm_enabled:
        bgm.play("opening")

    opening_reply = dm.start_game()
    if opening_reply:
        print(f"\nDM: {opening_reply}")
        if sound_enabled:
            if not tts.speak(opening_reply, scene="dm"):
                print("⚠️ 语音输出失败，已切换到纯文字模式（可输入 /sound on 重新开启）")
                sound_enabled = False

    while True:
        # 检查定时事件（线索公开）
        for timed_reply in dm.poll_timed_events():
            print(f"\nDM: {timed_reply}")
            if sound_enabled:
                if not tts.speak(timed_reply, scene="clue"):
                    print("⚠️ 语音输出失败，已切换到纯文字模式")
                    sound_enabled = False

        prompt_text = dm.get_turn_prompt_text()
        user_input = input(f"\n{prompt_text}: ").strip()

        # --- 命令处理 ---

        if user_input.lower() == "quit":
            if sound_enabled:
                tts.speak("游戏结束，感谢游玩", scene="ending")
            print("游戏结束，再见")
            break

        if user_input.lower() == "reset":
            dm.reset()
            print("游戏已重置，重新开场")
            opening_reply = dm.start_game()
            if opening_reply:
                print(f"\nDM: {opening_reply}")
                if sound_enabled:
                    if not tts.speak(opening_reply, scene="dm"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input.lower() == "status":
            print(f"\n{dm.get_status_text()}")
            continue

        if user_input.lower() == "/sound on":
            sound_enabled = True
            print("√ 语音输出已开启")
            continue

        if user_input.lower() == "/sound off":
            sound_enabled = False
            print("√ 语音输出已关闭")
            tts.stop()
            continue

        if user_input.lower() == "/sound test":
            print("正在测试语音输出...")
            tts.speak("你好，我是 DM。语音输出测试成功。", scene="dm")
            print("测试完成")
            continue

        # BGM 控制命令
        if user_input.lower() == "/bgm on":
            bgm_enabled = True
            bgm.play("discussion")
            print("√ 背景音乐已开启")
            continue

        if user_input.lower() == "/bgm off":
            bgm_enabled = False
            bgm.stop()
            print("√ 背景音乐已关闭")
            continue

        if user_input.lower().startswith("/bgm volume"):
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

        # 存档/读档命令
        if user_input.lower().startswith("/save"):
            parts = user_input.split()
            if len(parts) >= 2:
                filename = parts[1]
            else:
                filename = "savegame"
            success, message = dm.save_game(filename)
            print(message)
            continue

        if user_input.lower().startswith("/load"):
            parts = user_input.split()
            if len(parts) >= 2:
                filename = parts[1]
            else:
                filename = "savegame"
            success, message = dm.load_game(filename)
            print(message)
            if success and bgm_enabled:
                # 根据游戏阶段播放对应 BGM
                phase = dm.game_phase
                if phase == "discussion":
                    bgm.play("discussion")
                elif phase == "vote":
                    bgm.play("suspense")
                elif phase == "owner_confrontation":
                    bgm.play("confrontation")
                elif phase == "ending":
                    bgm.play("ending")
            continue

        if user_input == "/clue1":
            reply = dm.release_clue("clue_1")
            if reply:
                print(f"\nDM: {reply}")
                if sound_enabled:
                    if not tts.speak(reply, scene="clue"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input == "/clue2":
            reply = dm.release_clue("clue_2")
            if reply:
                print(f"\nDM: {reply}")
                if sound_enabled:
                    if not tts.speak(reply, scene="clue"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
            continue

        if user_input == "/vote":
            reply = dm.start_vote()
            if reply:
                print(f"\nDM: {reply}")
                if sound_enabled:
                    if not tts.speak(reply, scene="dm"):
                        print("⚠️ 语音输出失败，已切换到纯文字模式")
                        sound_enabled = False
                # 切换到悬疑 BGM
                if bgm_enabled:
                    bgm.play("suspense")
            continue

        # 搜证命令（也可以直接在 DM 引擎中处理）
        if user_input.lower().startswith("/search") or user_input.startswith("/搜索"):
            reply = dm.chat(user_input)
            if reply:
                print(f"\nDM: {reply}")
            continue

        if not user_input:
            print("请输入内容")
            continue

        # --- 普通对话处理 ---

        reply = dm.chat(user_input)
        if reply:
            print(f"\nDM: {reply}")
            if sound_enabled:
                # 根据内容自动判断场景
                scene = "dm"
                # 只有直接引用业主说话时才用男声（避免仅仅提到"业主"就误判）
                if "业主说" in reply or "业主：" in reply or "业主喊道" in reply:
                    scene = "owner"
                elif "原谅" in reply or "原谅你们" in reply or "复活" in reply:
                    scene = "owner_forgiveness"
                elif "Happy Ending" in reply or "幸福地生活" in reply or "后续故事" in reply:
                    scene = "ending_happy"
                elif "真相" in reply or "结束" in reply or "犯人" in reply:
                    scene = "ending"
                elif "线索" in reply and ("公开" in reply or "收到" in reply or "发现" in reply):
                    scene = "clue"
                if not tts.speak(reply, scene=scene):
                    print("⚠️ 语音输出失败，已切换到纯文字模式")
                    sound_enabled = False

    # 清理资源
    tts.unload()
    bgm.unload()


if __name__ == "__main__":
    main()
