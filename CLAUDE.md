# CLAUDE.md - AI 助手协作规范

> **项目**：AI 剧本杀 DM v0.8.0 | **剧本**：Monsters Halloween Night（4人）
> **当前阶段**：比赛准备 | **最高原则**：最小改动 + 不破坏验收测试

---

## 一、铁律（必须遵守，无例外）

1. **最小改动**：只改实现功能所需的最少代码。不重构、不顺手改无关代码、不添加未请求的功能。
2. **先计划再动手**：改动前用 2-3 句话说明改什么、影响哪些文件、如何验证。
3. **验收测试是安全网**：`scripts/acceptance_monsters_halloween.py`（35 项）必须保持通过。改动前先运行确认基线。
4. **程序是裁判，LLM 是演员**：行动结算、剧透检测、阶段推进是确定性代码，不依赖 LLM 判断。不要用 LLM 替代程序能确定的事。
5. **新增 > 修改**：新功能优先加新文件/新函数，避免在已有复杂函数中插入分支。

---

## 二、项目速览

**技术栈**：Python 3.13 + ECNU LLM API + pygame

### 2.1 核心模块

| 文件 | 职责 | 安全约束 |
|------|------|----------|
| `config.py` | API 客户端初始化、多提供商切换 | 不含逻辑 |
| `dm_engine.py` | 游戏状态机、LLM 调用、进度追踪、引导 | ⚠️ 已膨胀至 ~4600 行，禁止再加代码 |
| `script_schema.py` | ScriptSchema v0.2.1 加载/校验 | 不含运行时 |
| `script_data.py` | 旧版硬编码剧本数据（回退安全网） | 无逻辑 |
| `main.py` | CLI 入口、4 引擎整合、命令解析 | 不含游戏逻辑 |
| `tts_engine.py` | TTS 合成与播放 | 不判断场景 |
| `bgm_engine.py` | BGM 情绪播放、自动映射 | 不判断阶段 |
| `sfx_engine.py` | SFX 事件驱动播放、冷却去重 | 不判断事件 |
| `sfx_config.py` | SFX 常量 | 无逻辑 |
| `sfx_event_map.yaml` | 事件→分类映射 | 纯配置 |
| `mood_config.py` | 20 情绪桶定义、阶段映射 | 纯配置 |
| `detective_game_engine.py` | 单人侦探游戏运行时 | 独立产品线，不与 DM 引擎混用 |
| `detective_llm_actor.py` | 侦探游戏 NPC 扮演（可选） | 仅用于侦探游戏 |
| `game_schema.py` / `game_schema_v0_3.py` | 侦探游戏 Schema 校验 | 独立产品线 |

### 2.2 架构：双模式运行时

dm_engine.py 通过 `_schema_active()` 门控切换数据源，**不是两套引擎，是同一引擎的两种数据模式**：

```
                    dm_engine.py（同一个 chat() 入口）
                           │
              _schema_active() ?
              ┌───────────────┴───────────────┐
         Schema 模式（默认）                  Legacy 模式
         ScriptSchema JSON                   SCRIPT_DATA 常量
         AI_DM_SCHEMA_ENABLED=1             AI_DM_SCHEMA_ENABLED=0
```

- **Legacy 模式是回退安全网**：如果 Schema 出问题，关掉环境变量即可恢复
- **~70 个 Schema 方法都以 `if not self._schema_active(): return` 开头**
- **另有独立产品线：`detective_game_engine.py`** — 单人侦探游戏，不同运行时，不同 Schema 格式

### 2.3 数据流向（完整版）

```
玩家输入 → main.py
              ├─ 命令解析（/phase, /vote, /sfx, /bgm...）
              ├─ dm_engine.chat() → LLM → DM 回复
              │     └─ _build_system_prompt() ─ 切换 Schema/Legacy 数据
              │     └─ _analyze_reasoning_progress() ─ 本地语义分析
              │     └─ poll_idle_intervention() ─ 真实静默→DM 插话
              ├─ detect_tts_scene() → tts_engine.speak()
              ├─ auto_switch_bgm() → bgm_engine.play_for_phase()
              └─ trigger_sfx_event() → sfx_engine.play_event()
```

### 2.4 游戏阶段

```
opening → opening_rules → discussion → vote → owner_confrontation → ending → postgame_review
```

---

## 三、架构边界（禁止跨越）

1. **dm_engine.py 禁止再加代码**：已达 ~4600 行。新功能加新文件，或提取现有子系统后再说。Phase 1 已计划提取 `schema_runtime.py`。
2. **main.py 只能做整合**：不含游戏逻辑。新命令尽量轻（解析参数→调用引擎→输出结果）。
3. **侦探游戏禁止混入 DM 系统**：`detective_game_engine.py` 是独立产品线，不与 dm_engine 共享状态。
4. **不解析 PDF/DOCX**：文本导入只支持 Markdown/TXT。

---

## 四、安全约束（违反会导致演示失败）

1. **私有角色包永不泄露**：private role_packets 不能进入 LLM 提示词、公共知识、TTS、存档公开字段。验收测试 `test_bad_save_private_packet_scrubbed_from_prompt` 专门检查此项。
2. **剧透由程序控制，不由 LLM 自觉**：`forbidden_spoilers` 在 `_sanitize_hint_for_spoilers()` 和 `_schema_public_text_forbidden_hits()` 中由代码强制执行。
3. **存档必须向后兼容**：新增状态字段必须提供 `_coerce_schema_runtime_defaults()` 回填逻辑。验收测试 `test_legacy_save_compatibility` 检查此项。
4. **API 调用必须 try/except**：任意 API 调用失败不得中断游戏。降级到纯文字/TTS 关闭/BGM 回退。

---

## 五、测试与验证

### 5.1 运行验收测试（每次改动后必须执行）

```bash
# AST 语法检查（最快）
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in p.parts]; print('AST OK')"

# 核心验收测试（35 项，无 API 调用）
python -B scripts/acceptance_monsters_halloween.py

# Schema 校验
python -B scripts/test_script_schema_v0_2_1.py
```

### 5.2 FakeDMEngine 模式

验收测试通过重写 `_call_model()` 实现无 API 测试：
- `FakeDMEngine(DMEngine)` 用关键字匹配替代 LLM 调用
- 所有状态机逻辑、引导策略、剧透防护通过 FakeDMEngine 完整验证
- 新增验收测试应继承 `FakeDMEngine`，不调用真实 API

### 5.3 手动冒烟

```bash
python -B main.py                     # 默认 schema 模式
python -B main.py --no-schema          # legacy 回退模式
python -B main.py --script-id second_sample  # 多剧本切换
```

---

## 六、当前状态与优先级（2026-05-08）

### 比赛优先级

| 优先级 | 事项 | 状态 |
|--------|------|------|
| P0 | Legacy Monsters 流程端到端稳定 | ✅ 35 项验收通过 |
| P0 | TTS + BGM + SFX 音频链路稳定 | ⚠️ 末章 SFX 5 个关键词桶缺口 |
| P1 | Schema 多剧本切换演示（`--script-id second_sample`） | ✅ 可演示 |
| P1 | Action/Form 确定性结算演示 | ✅ emergent_resolution 可演示 |
| P2 | Text→Game 导入管线 | ⚠️ 实验性，仅 Markdown/TXT |

### 已知缺口

- SFX ending 分类：5 个关键词桶低库存（warm resolve, mystery resolve, relief chime, ending swell: 0-1 条）
- dm_engine.py 膨胀：已规划 Phase 1 提取 `schema_runtime.py`（比赛后可做）
- 没有 `/demo` 一键演示模式

---

## 七、文档导航

| 文件 | 何时查阅 |
|------|----------|
| `README.md` | 项目总览、快速开始、命令列表 |
| `demo_playbook.md` | 比赛演示流程、验收命令 |
| `DM 使用说明手册.md` | 游戏操作指南 |
| `项目开发与文档.md` | 扩展/修改代码指南、Prompt 模板 |
| `plan.md` | 当前功能完成度报告、P0/P1/P2 优先级 |
| `docs/` | 侦探游戏 CHANGELOG、参考笔记 |
