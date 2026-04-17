# 更新日志

## [0.8.0] - 2026-04-13

### 修复
- **TTS 超时问题**：
  - 将 TTS 请求超时从 30 秒增加到 60 秒
  - 新增 `_split_long_text()` 方法，自动将长文本按标点分割
  - 长文本分段合成播放，避免单次请求超时
  - 连续失败 3 次后提示用户检查网络或 API Key

### 新增
- **TTS 自动降级机制**：
  - TTS 失败时自动切换到纯文字模式
  - 输入 `/sound on` 可重新开启语音
  - 所有 TTS 调用处添加失败检测和提示

### 文档更新
- `DM 使用说明手册.md`：新增"背景音乐推荐"章节，推荐免费音乐网站
- `README.md`：更新版本号
- 更新故障排除章节，说明 v0.8.0 修复内容

### 修改
- `tts_engine.py`：
  - 新增 `TTS_TIMEOUT_SECONDS = 60` 配置
  - 新增 `_split_long_text()` 方法（按句号/问号/感叹号分割）
  - 新增 `_synthesize_and_play()` 内部方法
  - 新增 `consecutive_failures` 计数和自动降级
  - `speak()` 方法重构为支持分段播放
- `main.py`：
  - 所有 TTS 调用处添加返回值检查和自动降级逻辑
  - TTS 失败时提示"已切换到纯文字模式"

---

## [0.7.0] - 2026-04-07

- **简易搜证系统**：
  - 讨论 10 分钟后开放搜证环节
  - 支持 `/search [地点]` 命令搜索可疑地点
  - 预设 5 个可搜索目标（等候室、补给橱柜、垃圾桶、画框、橱柜）
  - 总共 2 个关键证据等待发现
  - 搜证冷却机制（2 回合）
- **游戏存档/读档功能**：
  - `/save [文件名]` 保存游戏进度到 JSON
  - `/load [文件名]` 读取游戏进度
  - 保存完整游戏状态（阶段、线索、搜证记录等）
- **背景音乐播放模块**：
  - 新增 `bgm_engine.py` 模块
  - 支持 9 种场景音乐配置（开场、讨论、搜证、悬疑、对峙、结局等）
  - 音量控制、淡入淡出效果
  - `/bgm on/off/volume` 命令控制
- **答案检查改进**：
  - 新增语义相似度算法（difflib.SequenceMatcher）
  - 关键词匹配 + 语义相似度双轨判定
  - 支持更多答案变体，提高容错性
- **背景音乐生成脚本**：
  - 新增 `generate_bgm.py` 脚本
  - 可生成 8 个 WAV 格式氛围音乐（无需额外依赖）
  - 用于测试目的，建议后续替换为真实音乐

### 修改
- `dm_engine.py`：
  - 新增搜证系统状态变量（`search_system_enabled`, `found_evidence` 等）
  - 新增 `save_game()` 和 `load_game()` 方法
  - 新增 `_handle_search_command()` 方法处理搜证命令
  - 新增 `_calculate_semantic_similarity()` 方法计算语义相似度
  - 改进 `_is_answer_correct()` 方法，添加语义相似度判断
  - `poll_timed_events()` 添加搜证系统开启通知
- `main.py`：
  - 集成 BGM 引擎
  - 新增 `/search`, `/save`, `/load`, `/bgm` 命令处理
  - 更新帮助文本
- `script_data.py`：
  - 新增 `search_system` 配置段落
  - 定义可搜索地点、线索映射、成功消息等

### 技术细节
- 语义相似度阈值：75%
- 搜证冷却时间：2 回合
- 存档格式：JSON
- 支持的音频格式：MP3, OGG, WAV, MID

---

## [0.6.0] - 2026-04-07

### 新增
- **说明文档同步更新**：确保 README.md、CHANGELOG.md、功能清单与改进方向.md 与实际代码保持一致

### 修改
- 版本号从 v0.5.0 升级至 v0.6.0，标志核心功能完整实现
- README.md：更新游戏流程、双重结局描述
- 功能清单与改进方向.md：标记 v0.5.0 三项高优先级改进为已完成，更新剩余改进方向

---

## [0.5.0] - 2026-04-07

### 新增
- **业主对峙环节正式实现**：
  - 2 轮对话收集玩家解释
  - 自动判定诚实度触发对应结局
- **诚实度检测系统**：
  - 关键词分析（诚实关键词 vs 推卸关键词）
  - AI 语义判断辅助
  - 临界情况自动处理
- **双重结局完整实现**：
  - **Happy Ending**：完整的原谅与复活叙事（765 字符）
  - **Bad Ending**：完整的惩罚叙事（678 字符）
  - 结局包含后续故事和主题升华

### 修改
- `dm_engine.py`：
  - 新增 `_start_owner_confrontation()` 方法
  - 新增 `_judge_player_honesty()` 方法
  - 新增 `_handle_owner_confrontation_input()` 方法
  - 新增 `_trigger_happy_ending()` 和 `_trigger_bad_ending()` 方法
  - 新增 `_build_happy_ending_text()` 完整文本
  - 新增 `_build_bad_ending_text()` 完整文本
- `dm_engine.py`：`chat()` 方法添加业主对峙环节处理
- `dm_engine.py`：`_finish_vote_and_reveal()` 修改为进入 `owner_confrontation` 阶段

### 技术细节
- 诚实度检测：诚实关键词 15 个，推卸关键词 10 个
- 对峙轮次：默认 2 轮后触发结局，额外轮次直接触发
- AI 判断失败时默认诚实（鼓励正向体验）

---

## [0.4.0] - 2026-04-07

### 新增
- **五步开场白流程**：规则说明 → 规则确认 → 戏剧演绎 → 剧本朗读 → 任务陈述
- **规则确认环节**：DM 询问玩家是否理解规则，自动判断玩家意图（选项 A：自动判断）
- **讨论模式优化**：DM 在普通对话时保持沉默，仅在玩家问问题时精准回应（规则/流程/线索/剧情）
- **投票流程优化**：新增"写答案"环节，强调同时公布，录入时提示答案不可修改
- **Happy Ending 双重结局系统**：
  - 业主是魔法师，拥有时间倒流/起死回生能力
  - 诚实 + 道歉 → 业主原谅并用魔法复活孩子（Happy Ending）
  - 隐瞒 → 业主惩罚怪物们（Bad Ending）
  - 结局包含业主对峙环节和后续故事旁白

### 修改
- `dm_engine.py`：重构开场白、讨论模式、投票流程和结局逻辑
- `main.py`：新增语音场景检测（owner_forgiveness、ending_happy）
- `tts_engine.py`：新增语音场景配置

### 技术细节
- 新增 `_handle_opening_rules_confirmation()` 方法处理规则确认
- 新增 `_classify_player_question()` 方法分类玩家问题（RULES/FLOW/CLUE/LORE/CHAT）
- 新增 `_continue_opening_drama()`、`_continue_opening_reading()`、`_continue_opening_tasks()` 方法
- Happy Ending Fallback 文本包含完整剧情：业主原谅、魔法复活、后续故事

---

## [0.3.1] - 2026-04-07

### 修复
- **修复 DM  voice 性别错误**：场景识别逻辑优化，仅当直接引用业主说话（"业主说"、"业主："）时才用男声，避免仅仅提到"业主"就误判
- **优化线索场景识别**：线索公开场景需同时包含"线索"和"公开/收到/发现"关键词，减少误触发

### 修改
- `main.py`：改进场景自动识别逻辑，增加关键词匹配精度
- `tts_engine.py`：添加声音配置注释，明确 xiayu 为女声、liwa 为男声

---

## [0.3.0] - 2026-04-07

### 新增
- **TTS 语音输出功能**：集成 ECNU 学校官方 TTS API
- **多场景声音配置**：
  - DM/旁白：女声 `xiayu`，语速 1.0
  - 业主：男声 `liwa`，语速 1.15（急促/愤怒）
  - 线索公开：女声 `xiayu`，语速 0.9（神秘感）
  - 结局演绎：女声 `xiayu`，语速 0.85（收尾氛围）
- **语音开关命令**：`/sound on`、`/sound off`、`/sound test`
- **场景自动识别**：根据回复内容自动切换声音（业主、线索、结局等）
- 新增 `requirements.txt` 依赖文件
- 新增 `tts_engine.py` 语音合成模块

### 修改
- `main.py`：集成 TTS 语音输出
- `config.py`：添加 TTS API 配置
- `CHANGELOG.md`：更新版本记录
- `README_使用说明.txt`：添加语音使用说明

### 技术细节
- TTS API：`https://chat.ecnu.edu.cn/open/api/v1/audio/speech`
- TTS 模型：`ecnu-tts`
- 声音选项：`xiayu` (女声), `liwa` (男声)
- 语速范围：0.25-4.0
- 依赖：`requests`, `pygame`

---

## [0.2.0] - 2026-04-07

### 修复
- 修复 `dm_engine.py` 中因 PowerShell 重写导致的 UTF-8 编码损坏问题
- 修复开场白事件文本乱码（第 66 行）
- 修复英文角色 ID 映射失效问题（wolf → 狼，witch → 女巫等）
- 修复非标准 phase 映射问题（`discussion_start` → `DISCUSSION`）
- 修复 `_extract_controls()` 方法中 control action 的中文关键词匹配
- 修复 `_infer_next_speaker_from_text()` 方法的 docstring 和正则表达式 patterns
- 修复兜底逻辑的窗口范围（从 `index:index+40` 改为前后各 15 字符）

### 增强
- 正则表达式 patterns 添加 `\s*` 支持，允许中英文混排和空格
- 文本提取发言人支持多种点名句式：
  - `请狼发言` / `请先狼发言`
  - `首先，请女巫发言`
  - `现在，请吸血鬼发言`
  - `请由木乃伊继续发言`
  - `轮到狼发言`
  - `请狼先说`
- 兜底逻辑支持关键词：`请`、`让`、`由`、`轮到`、`需要`、`应该`

### 新增
- 完整功能测试脚本（test_full.py）
- 本更新日志文件（CHANGELOG.md）

---

## [0.1.0] - 2026-04-06

### 新增
- 基础 AI DM 对话引擎
- 剧本《Monsters Halloween Night》数据结构
- 命令行交互界面
- 定时线索公开机制
- 插话确认机制
- 滚动案件摘要和结构化记忆

### 已知限制
- ECNU 接口偶尔返回 Internal Server Error
- 内部时钟仅在每轮输入前检查，长时间无输入不会自动触发线索
- 角色秘密信息需外部人工分发
- 结尾后需手动输入 `reset` 重新开始
