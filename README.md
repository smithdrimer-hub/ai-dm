# 中文 AI 剧本杀 DM

## 项目简介

本项目是一个基于 ECNU（华东师范大学）大语言模型平台的 AI 剧本杀主持人（DM）系统，支持固定剧本《Monsters Halloween Night》的完整主持流程。

**当前版本**：v0.8.0  
**最后更新**：2026-04-13  
**适用剧本**：Monsters Halloween Night（4 人，60 分钟）

---

## 📚 文档索引

| 文档 | 说明 |
|------|------|
| [DM 使用说明手册.md](DM 使用说明手册.md) | 面向使用/调试者的完整操作指南 |
| [项目开发与文档.md](项目开发与文档.md) | 面向开发者的架构说明和开发指南 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |
| `legacy/` | 历史文档归档文件夹 |

---

## 快速开始

### 环境要求

- Python 3.13 或更高版本
- ECNU LLM 平台 API Key（学校提供的 OpenAI 兼容接口）
- 网络连接（调用学校 API）

### 安装依赖

```bash
pip install -r requirements.txt
```

依赖包：
- `openai` - ECNU LLM API 客户端
- `python-dotenv` - 环境变量管理
- `requests` - HTTP 请求（TTS 使用）
- `pygame` - 音频播放

### 可选：生成或批量下载背景音乐

如需快速测试背景音乐功能，可运行以下命令生成合成音乐：

```bash
python generate_bgm.py
```

这将在 `music/` 目录生成 8 个 WAV 格式的氛围音乐文件（每个约 30 秒）。

如需按情绪批量下载（Freesound API，默认每类 10 条、20-180 秒，且默认仅下载 CC0）：

```bash
python download_moods_freesound.py --dry-run
python download_moods_freesound.py --resume
```

如需提升情绪匹配精度，可增加文本匹配阈值与更严格时长：

```bash
python download_moods_freesound.py --resume --min-duration 30 --min-text-match 0.08
```

如需在你确认后允许 CC BY 补位，可追加参数：

```bash
python download_moods_freesound.py --resume --allow-cc-by-fallback
```

SFX pipeline quick start (v2, keyword-level):

SFX library bootstrap (6 categories / 50 keyword buckets, strict CC0, target 3 each):

```bash
python download_sfx_library.py --audit-only --target-per-keyword 3
python download_sfx_library.py --resume --target-per-keyword 3 --max-page-limit 2 --max-per-query 30 --max-candidates-per-keyword 100 --max-attempts-per-keyword 45
```

Optional scoped retry (single or multiple keyword buckets):

```bash
python download_sfx_library.py --resume --target-per-keyword 3 --keyword-scope "ending:warm resolve,ending:relief chime"
```

SFX outputs:
- `audio_library/sfx/<category>/*.mp3`
- `audio_library/sfx/metadata.csv`
- `audio_library/sfx/rejected.csv`
- `audio_library/sfx/summary.json`
- `audio_library/sfx/license_manifest.csv`
- `audio_library/sfx/keyword_audit.csv`
- `audio_library/sfx/keyword_audit.json`
- `audio_library/sfx_demo_bundle/` (offline demo subset)

SFX gap retry playbook (current known gaps):

```bash
python download_sfx_library.py --resume --target-per-keyword 3 --keyword-scope "environment:door knock" --max-author-per-keyword 3 --max-page-limit 4 --max-per-query 80 --max-candidates-per-keyword 240 --max-attempts-per-keyword 140 --rate-limit 45
python download_sfx_library.py --resume --target-per-keyword 3 --keyword-scope "clue_search:photo pickup,ending:warm resolve,ending:mystery resolve,ending:relief chime,ending:ending swell" --max-author-per-keyword 2 --max-page-limit 5 --max-per-query 100 --max-candidates-per-keyword 300 --max-attempts-per-keyword 180 --rate-limit 45
```

SFX orphan cleanup playbook (metadata-driven, mp3 only):
- 仅删除 `audio_library/sfx/<category>/` 和 `audio_library/sfx_demo_bundle/<category>/` 下未被各自 `metadata.csv` 引用的 mp3。
- 不删除 `.csv/.json`；不跨目录删除；先 dry-run 统计再执行。
- 若普通权限删除报 `WinError 5 Access denied`，使用管理员/提升权限执行同一套 metadata 驱动删除流程。

下载脚本会将文件保存到 `music/moods/<mood_slug>/`，并生成：
- `music/moods/index.json`（全量索引）
- `music/moods/attribution.csv`（仅需署名素材）

说明：
- 播放系统优先按 `index.json` 加载情绪音效；未在索引中的文件默认视为“已移除”。
- 在当前 Windows 权限环境下，如遇文件无法 move/delete，可先采用“索引移除 + `_rejected` 复制归档”的软移除方案；具备管理员权限时可执行 metadata 驱动的硬删除清理孤儿文件。

推荐质检闭环（先筛选，再回补，再复筛）：

```bash
python filter_moods_library.py --apply --min-duration 30 --max-duration 180 --min-rms 120 --min-active-ratio 0.02 --min-head-rms 20
python download_moods_freesound.py --resume --per-mood 10 --min-duration 30 --max-duration 180 --min-text-match 0.08
python filter_moods_library.py --apply --min-duration 30 --max-duration 180 --min-rms 120 --min-active-ratio 0.02 --min-head-rms 20
```

### 配置 API Key

在项目根目录创建 `.env` 文件：

```bash
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://chat.ecnu.edu.cn/open/api/v1
OPENAI_MODEL=ecnu-max
ECNU_TTS_MODEL=ecnu-tts
ECNU_DEFAULT_VOICE=xiayu
FREESOUND_API_KEY=your_freesound_api_key_here
```

### 运行游戏

```bash
py -3.13 main.py
```

---

## 游戏流程

### 完整流程图

```
┌─────────────────────────────────────────────────────────────┐
│                      游戏开始                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  第一阶段：开场白（五步流程）                                 │
│  1. 规则说明 → 2. 规则确认 → 3. 戏剧演绎 → 4. 剧本朗读 → 5. 任务陈述 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  第二阶段：自由讨论                                           │
│  - DM 点名发言，玩家轮流陈述                                   │
│  - 线索在 10 分钟、20 分钟时自动公开                            │
│  - 讨论 10 分钟后可输入 `/search [地点]` 搜索证据              │
│  - DM 仅在必要时介入（规则问答、维持秩序等）                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  第三阶段：最终公开答案（/vote）                              │
│  1. 玩家在纸上写下答案                                         │
│  2. 所有人同时公开答案                                         │
│  3. 按顺序录入四位角色的答案（犯人/碎布/橱柜）                 │
│  4. 答案锁定，不可修改                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  第四阶段：业主对峙与结局                                     │
│  - 业主（魔法师）赶到，质问怪物们                              │
│  - 玩家集体解释经过（2 轮对话）                                 │
│  - 根据诚实度触发不同结局：                                   │
│    * Happy Ending: 诚实 + 道歉 → 业主原谅，魔法复活孩子        │
│    * Bad Ending: 隐瞒 → 业主惩罚怪物们                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 可用命令

### 基础命令

| 命令 | 说明 |
|------|------|
| `quit` | 退出程序 |
| `reset` | 重置整局游戏，重新开始 |
| `status` | 查看当前游戏状态（阶段、发言玩家、线索等） |

### 线索与搜证

| 命令 | 说明 |
|------|------|
| `/clue1` | 手动公开线索 1（补给橱柜的合页被破坏了） |
| `/clue2` | 手动公开线索 2（在补给橱柜里找到了钥匙） |
| `/search [地点]` | 搜索指定地点（讨论 10 分钟后开放） |
| `/vote` | 进入最终公开答案阶段 |

### 存档/读档

| 命令 | 说明 |
|------|------|
| `/save [文件名]` | 保存游戏进度（默认 savegame.json） |
| `/load [文件名]` | 读取游戏进度 |

### 语音与背景音乐

| 命令 | 说明 |
|------|------|
| `/sound on` | 开启语音输出 |
| `/sound off` | 关闭语音输出 |
| `/sound test` | 测试语音输出功能 |
| `/bgm on` | 开启背景音乐 |
| `/bgm off` | 关闭背景音乐 |
| `/bgm volume [0-1]` | 设置背景音乐音量 |
| `/bgm mood list` | 显示可用情绪及数量 |
| `/bgm mood [slug]` | 手动切换到指定情绪 |
| `/bgm auto on/off` | 开关自动情绪映射 |
| `/sfx on` | Enable SFX |
| `/sfx off` | Disable SFX |
| `/sfx volume [0-1]` | Set SFX volume |
| `/sfx status` | Show SFX catalog and events |
| `/sfx event [name]` | Trigger SFX event manually |
| `/sfx category list` | List SFX categories |
| `/sfx category [slug]` | Play one SFX by category |

---

## 交互规则

### 发言机制

1. **DM 点名**：DM 会点名指定某位玩家发言
2. **默认归属**：点名后，下一条输入默认属于该玩家，无需输入"角色名：内容"
3. **插话确认**：如果出现明显插话，DM 会进入主持确认流程，要求只输入角色名完成确认

### 讨论模式

- **普通对话**：DM 保持沉默，不打断玩家讨论
- **规则问题**：DM 简明回答（如"规则是什么"）
- **流程问题**：DM 直接回答（如"该谁发言"）
- **线索问题**：DM 告知当前线索状态
- **剧情问题**：DM 引导玩家自行推理，不剧透

### 最终公开答案阶段

1. DM 提示玩家**在纸上写下三道答案**，不要让他人看到
2. 所有玩家**同时公开**答案
3. 操作者按顺序录入四位角色的答案
4. 录入格式：`犯人答案/碎布答案/橱柜答案`
5. **答案锁定**：录入时必须按照写下的答案，不能修改

示例录入：
```
狼/孩童衣服的碎片/女巫发现人类后用钥匙把孩童藏进补给橱柜
```

---

## 语音输出

### 声音配置

| 场景 | 声音 | 语速 | 说明 |
|------|------|------|------|
| DM/旁白 | 女声 (xiayu) | 1.0 | 温柔亲切 |
| 业主（愤怒） | 男声 (liwa) | 1.15 | 急促/愤怒 |
| 业主（原谅） | 男声 (liwa) | 0.85 | 感性/缓慢 |
| 线索公开 | 女声 (xiayu) | 0.9 | 神秘感 |
| 结局演绎 | 女声 (xiayu) | 0.85 | 收尾氛围 |
| Happy Ending | 女声 (xiayu) | 0.9 | 温暖治愈 |
| 任务陈述 | 女声 (xiayu) | 0.95 | 清晰稳重 |

### 场景自动识别

程序会根据 DM 回复内容自动切换语音场景：
- 包含"业主说"、"业主："、"业主喊道" → 男声（愤怒）
- 包含"原谅"、"复活" → 男声（原谅）
- 包含"Happy Ending"、"幸福地生活" → 女声（温暖治愈）
- 包含"真相"、"结束"、"犯人" → 女声（结局）
- 包含"线索"、"公开"、"发现" → 女声（线索）

---

## 剧本核心信息

### 三道最终公开答案

1. **谁是真正的犯人？**
   - 标准答案：狼

2. **木乃伊身上的漂亮碎布究竟是什么？**
   - 标准答案：孩童衣服的碎片
   - 关键词匹配：孩童/孩子/小孩 + 衣服/衣物 + 碎片/碎布/碎

3. **孩童为什么会被放进上锁的补给橱柜？**
   - 标准答案：女巫发现等候室里还有人类后，用钥匙把孩童藏进了上锁的补给橱柜
   - 关键词匹配：女巫 + 发现/察觉 + 人类/孩童 + 钥匙/橱柜 + 藏进

### 真相时间线

| 时间 | 事件 |
|------|------|
| 18:00 | 木乃伊发现迷路孩童，带进等候室后离开去找业主 |
| 19:00 | 吸血鬼进入等候室，被孩童吓跑 |
| 20:00 | 女巫发现孩童，用钥匙将其藏进补给橱柜 |
| 更晚 | 狼撬坏橱柜，吃掉孩童，撕碎衣服 |
| 22:00 | 木乃伊回到等候室，捡到碎布当绷带 |

---

## 代码结构

### 文件列表

```
murder-mystery-dm/
├── config.py                  # 配置与 API 客户端初始化
├── script_data.py             # 结构化剧本数据
├── dm_engine.py               # 核心 DM 引擎（游戏逻辑、状态管理）
├── tts_engine.py              # 语音合成模块（ECNU TTS API）
├── bgm_engine.py              # 背景音乐播放模块
├── main.py                    # 命令行入口（集成 TTS+BGM）
├── generate_bgm.py            # 背景音乐生成脚本（测试用）
├── download_moods_freesound.py# Freesound 情绪音效批量下载脚本
├── mood_config.py             # 情绪分类、检索词、自动映射配置
├── test_api.py                # API 测试脚本
├── requirements.txt           # Python 依赖列表
├── .env                       # 环境变量（API Key，需自行配置）
├── DM 使用说明手册.md         # 面向使用者的操作手册
├── 项目开发与文档.md           # 面向开发者的技术文档
├── README.md                  # 项目总览（本文件）
├── CHANGELOG.md               # 版本更新日志
├── legacy/                    # 历史文档归档文件夹
├── music/                     # 背景音乐文件目录
└── China/                     # 剧本原始资料
```

### 核心模块职责

| 文件 | 职责 | 不负责 |
|------|------|--------|
| `config.py` | 配置加载、API 客户端初始化、多 API 提供商切换 | 不使用配置，仅导出 |
| `script_data.py` | 剧本结构化数据（角色卡、线索、答案、世界设定） | 无逻辑，纯数据定义 |
| `dm_engine.py` | 游戏状态机、LLM 调用、玩家输入处理、问题分类 | 不调用 TTS/BGM，不定义剧本数据 |
| `tts_engine.py` | TTS API 调用、声音配置、音频播放、长文本分割 | 不判断场景，由外部传入 scene |
| `bgm_engine.py` | 场景/情绪 BGM 播放、自动情绪映射、音量控制 | 不判断游戏阶段，由外部传入 phase |
| `main.py` | 整合三大引擎、命令解析、TTS 场景判断、BGM 自动切换 | 不含游戏逻辑 |
| `mood_config.py` | 情绪定义、Freesound 检索词、阶段 - 情绪映射 | 无逻辑，纯配置 |

### 数据流向

```
玩家输入 → main.py (命令解析) → dm_engine.chat() → LLM
                                           ↓
                                    DM 回复文本
                                           ↓
                    main.py (detect_tts_scene) → tts_engine.speak()
                    main.py (auto_switch_bgm) → bgm_engine.play_for_phase()
```

### 关键方法索引

#### dm_engine.py
- `start_game()` - 启动五步开场白流程
- `chat(user_input: str) -> str` - 处理玩家输入，返回 DM 回复
- `start_vote()` - 进入最终公开答案阶段
- `release_clue(clue_id: str) -> str` - 手动公开指定线索
- `save_game(filename: str) -> tuple[bool, str]` - 存档
- `load_game(filename: str) -> tuple[bool, str]` - 读档

#### tts_engine.py
- `speak(text: str, scene: str, blocking: bool) -> bool` - 合成并播放语音
- `set_voice_for_scene(scene: str)` - 切换声音配置

#### bgm_engine.py
- `play(scene: str, fade_ms: int) -> bool` - 播放场景音乐
- `play_mood(mood: str, fade_ms: int) -> bool` - 播放情绪音乐
- `play_for_phase(phase: str, reply_text: str, fade_ms: int) -> bool` - 根据阶段自动播放
- `set_auto_mood(enabled: bool)` - 开关自动情绪映射

#### main.py
- `detect_tts_scene(reply: str) -> str` - 根据 DM 回复判断 TTS 场景
- `main()` - 启动游戏

---

## 技术细节

### API 调用

使用 ECNU LLM 平台的 OpenAI 兼容接口：

```python
from config import client, MODEL_NAME

response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=[
        {"role": "system", "content": "你是一位中文剧本杀 DM..."},
        {"role": "user", "content": "玩家输入内容"}
    ],
    stream=False,
    timeout=60
)
```

### 控制标记格式

DM 模型输出需包含 6 个控制标记：

```
DM_ACTION: SPEAK 或 SILENT
NEXT_SPEAKER: 狼 | 女巫 | 吸血鬼 | 木乃伊 | ALL | UNCHANGED
PHASE_UPDATE: OPENING | DISCUSSION | VOTE | ENDING | UNCHANGED
INPUT_EVAL: ON_TOPIC | LIGHT_OFFTOPIC | HARD_OFFTOPIC | JAILBREAK | RULES_QUESTION
PROGRESS_SIGNAL: PROGRESS | STALLED | BREAKTHROUGH | UNCHANGED
MEMORY_UPDATE: {"confirmed_facts":[], ...}
```

### 答案检查逻辑

采用关键词分组匹配：

```python
# 碎布答案检查示例
keyword_groups = [
    ["孩童", "孩子", "小孩"],
    ["衣服", "衣物", "衣料"],
    ["碎片", "碎布", "布片", "碎"]
]
# 匹配 2 组以上即判定为正确
```

---

## 已知限制

1. **API 稳定性**：ECNU 接口偶尔返回 Internal Server Error，代码已增加重试和降载机制
2. **时钟机制**：内部时钟仅在每轮输入前检查，长时间无输入不会自动触发线索
3. **角色秘密信息**：需外部人工分发，程序不负责私聊发送角色卡
4. **说话人识别**：依赖 DM 点名流程，无实际语音识别

---

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)

### v0.6.0 (2026-04-07)
- **说明文档同步更新**：README、CHANGELOG、功能清单与实际代码保持一致
- **版本晋升**：从 v0.5.0 升至 v0.6.0，标志核心功能完整实现

### v0.5.0 (2026-04-07)
- **业主对峙环节**：正式实现 2 轮对话流程
- **诚实度检测系统**：关键词分析 + AI 语义判断
- **双重结局完整实现**：
  - Happy Ending：诚实 + 道歉 → 业主原谅，魔法复活孩子
  - Bad Ending：隐瞒 → 业主惩罚怪物们
- **结局文本优化**：完整的 Happy Ending 和 Bad Ending 叙事

### v0.4.0 (2026-04-07)
- 五步开场白流程 + 规则确认环节
- 讨论模式优化（普通对话时 DM 沉默）
- 投票流程优化（写答案环节 + 答案锁定）
- Happy Ending 双重结局系统

### v0.3.0 (2026-04-07)
- TTS 语音输出功能
- 多场景声音配置

---

## 故障排除

### TTS API 调用失败

1. 检查网络连接是否正常
2. 确认 API Key 是否正确
3. 检查 `BASE_URL` 是否配置正确

### 语音播放问题

1. 确认电脑音量正常
2. 确认 pygame 已正确安装：`pip install pygame`
3. 检查音频设备是否正常

### 模型返回结构不完整

1. 尝试输入 `reset` 重置游戏
2. 检查 API 调用是否频繁（可能触发限流）
3. 等待一段时间后重试

---

## 许可证

本项目仅供学习和研究使用。

剧本《Monsters Halloween Night》版权归原作者或发行方所有。
