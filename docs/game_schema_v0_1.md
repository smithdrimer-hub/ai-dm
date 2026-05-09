# GameSchema v0.1

> 目标：把剧本杀文本转化为可运行的单人 AI 推理游戏。

GameSchema 与现有 ScriptSchema 并行存在。ScriptSchema 偏多人剧本杀主持流程；GameSchema 只服务单人侦探模式：玩家扮演侦探，与 AI NPC 对话、搜证、出示证据、指认真凶。

## 核心原则

1. LLM 是演员，程序是裁判。
2. LLM 负责表达，不负责线索释放、谎言击破、阶段推进或最终评分。
3. 每次调用 NPC 只提供该 NPC 当前应该知道的信息。
4. 私密真相、未解锁事实、禁止泄露内容由 schema 和运行时隔离。
5. v0.1 只要求跑通一个完整案件，不追求任意小说自动转换。

## 顶层结构

```json
{
  "schema_version": "game_schema_v0.1",
  "game_info": {},
  "source_info": {},
  "review": {},
  "public_case": {},
  "npc_characters": [],
  "scenes": [],
  "evidence": [],
  "lies": [],
  "truth_model": {},
  "phases": [],
  "mechanics": {},
  "accusation_rules": {},
  "recap": {}
}
```

## 字段职责

`game_info`
案件元信息。v0.1 固定 `mode=single_player_detective`、`player_role=detective`。

`source_info`
输入来源与授权状态。当前优先支持 `source_type=murder_mystery_text`，输入格式为 `md` 或 `txt`。

`review`
人工复核结果。导入器必须写入缺失字段、逻辑风险、剧透风险、复核清单和 source trace。`status=confirmed` 前不应进入正式游戏。

`public_case`
玩家开局可见信息，包括背景、侦探任务、初始可访问场景和内容提示。

`npc_characters`
AI NPC 嫌疑人。每个 NPC 包含公开档案、私密档案、已知真相、可说谎点、禁止提前泄露的真相。

`scenes`
可搜索场景。场景控制证据和 NPC 的初始可达性。

`evidence`
可发现证据。证据可以关联真相节点，也可以声明能击破哪些谎言。

`lies`
谎言点。每个谎言绑定 NPC、对应真相、击破所需证据和击破后的解锁结果。

`truth_model`
案件真相。包含真凶、动机、手法、真相节点、时间线和证据到真相的关系。

`phases`
游戏阶段。v0.1 阶段类型为 `intro`、`investigation`、`confrontation`、`accusation`、`recap`。

`mechanics`
命令配置和初始阶段。v0.1 目标命令为 `/ask`、`/search`、`/inspect`、`/show`、`/accuse`、`/status`、`/hint`。

`accusation_rules`
最终指认评分规则。凶手、动机、手法和证据链必须由结构化规则评分。

`recap`
结局复盘素材。运行时根据玩家已发现内容和遗漏内容生成自然语言复盘。

## v0.1 最小闭环

1. 读取 md/txt 剧本文本。
2. 生成 GameSchema draft。
3. 输出 `missing_fields`、`logic_warnings`、`spoiler_risks`、`manual_checklist`。
4. 用户确认后将 `review.status` 改为 `confirmed`。
5. 运行单人侦探游戏：
   - `/search [scene]` 发现证据。
   - `/ask [npc] [question]` 与 NPC 对话。
   - `/show [npc] [evidence]` 击破谎言。
   - `/accuse` 提交凶手、动机、手法和证据链。
6. 程序评分并生成复盘。

## 文件

- JSON Schema: `schemas/game_schema_v0_1.schema.json`
- Python validator: `game_schema.py`
- Tiny example: `scripts/schema_examples/tiny_detective_case_v0_1.json`

