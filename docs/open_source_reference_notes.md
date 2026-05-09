# 开源项目参考笔记

## 本次阅读范围

本次在 `external_repos/` 下克隆并阅读以下项目，仅提取设计思路，不复制代码到主项目：

- `DigitalBoopLtd/murder-mystery`
- `eliotjlee/holmes`
- `sebastian-ahmed/adventure_game`
- `RALWORKS/intficpy`
- `qemqemqem/ClueEval`

注意：`ClueEval` 仓库包含 Windows 不合法文件名，例如生成样例文件名里带冒号。普通 checkout 会失败。本地已通过 sparse checkout 检出可读的 `README.md`、`config/`、`story/`、`utils/`、`lm_eval/` 等源码与评测目录，生成样例目录主要通过 `git show` 阅读。

本次结论服务于当前目标：把剧本杀文本转化为可运行的单人 AI 推理游戏。近期只优化 `GameSchema v0.1` 和 `DetectiveGameEngine` 最小运行时，不改 `dm_engine.py` 主流程，不引入大型框架，不把项目改造成通用文字冒险引擎。

## 总体结论

最值得吸收的不是 UI、RAG、自然语言解析或大型 IF 框架，而是五个小而稳的设计原则：

1. 真相与表演分离：程序持有真相并裁决，NPC 只拿到可见信息。
2. 状态显式保存：阶段、已发现线索、已搜索地点、已击破谎言、行动历史、指认历史都应能快照化。
3. 命令是受控动作：`search`、`show`、`ask`、`confront`、`accuse`、`status` 应先是确定性 API，再接 CLI 或 UI。
4. 解锁条件结构化：线索释放、地点开放、谎言击破、真相节点解锁都应由 schema 字段驱动。
5. 回放先于复杂智能：用 scripted playthrough 保证案件能跑通，比先接 LLM 更重要。

当前 `DetectiveGameEngine` 已经具备最小闭环：加载 confirmed GameSchema、搜索场景、展示证据、模板化 NPC 回答、击破谎言、推进阶段、指认凶手和复盘。下一步应在这个基础上补齐显式状态和显式对质，不需要重构成新框架。

## DigitalBoopLtd/murder-mystery

### 可借鉴设计

这个项目最有价值的是 “Oracle Pattern”：GM 或玩家可见层不是最终裁判，真相被隔离在 `MysteryOracle` 一类的对象里。玩家动作通过工具调用进入 oracle，oracle 再返回受控结果。它与当前原则 “LLM 是演员，程序是裁判” 高度一致。

它的 game state 比当前项目完整，包含：

- 当前 mystery 与公开 mystery。
- 已发现线索 `clues_found`、`clue_ids_found`。
- 已询问嫌疑人 `suspects_talked_to`。
- 已搜索地点 `searched_locations`。
- 已解锁地点 `unlocked_locations`。
- 错误指认次数 `wrong_accusations`。
- 指认历史 `accusation_history`。
- 游戏结束、是否胜利、是否被解雇等结局状态。
- 每个嫌疑人的状态，如信任、紧张、矛盾点。

它的动作设计也很清晰：`interrogate_suspect`、`search_location`、`make_accusation`、`find_contradictions`、`get_timeline` 等都不是自由文本入口，而是受控工具。这个思路适合我们保留。

### 对当前项目的启发

当前 engine 已有 `current_phase_id`、`unlocked_scene_ids`、`discovered_evidence_ids`、`unlocked_truth_ids`、`broken_lie_ids`、`asked_character_ids`、`history`。建议下一步补齐：

- `searched_scene_ids`：区分“地点已解锁”和“地点已搜过”。
- `accusation_history`：允许记录多次错误指认或至少记录最终提交。
- `wrong_accusations`、`game_over`、`won`：让 `/status` 和测试能检查终局状态。
- `last_action_result` 或统一 action result：方便未来 UI 和 scripted replay 验证。

### 暂不采用

不采用 MCP server、Gradio、语音、图像生成、向量检索、复杂情绪系统。它们适合成熟产品，但会让当前最小运行时过重。

## eliotjlee/holmes

### 可借鉴设计

`holmes` 的核心价值是按嫌疑人组织视角。它有一个 `Plot` 对象保存案件摘要、受害者、谋杀细节、嫌疑人、共享互动和时间线；每个 `Suspect` 有公开信息、是否有罪、记忆路径。更关键的是，它区分了：

- 给玩家或选择菜单看的嫌疑人摘要。
- 给某个嫌疑人自己的上下文。
- 给其他嫌疑人的摘要。

这对我们未来接 LLM 很重要。NPC prompt 不应该拿整份真相，而应该通过一个 context builder 只获得：

- 自己的公开档案。
- 自己的私密档案中当前允许扮演的信息。
- 当前已解锁 truth nodes 中，且不在 forbidden list 里的部分。
- 当前尚未被击破的谎言。
- 玩家与该角色的对话历史。

### 风险点

`holmes` 的嫌疑人上下文里会明确告诉 guilty suspect 自己有罪并描述作案，这适合让 NPC 演出，但如果直接用于我们的 LLM prompt，存在提前泄露风险。当前项目应坚持 `forbidden_truth_ids` 和按阶段解锁，凶手是否知道真相也要通过 GameSchema 明确控制。

### 暂不采用

不采用 LangChain、Chroma、动态生成完整故事、pickle 存档。当前输入是剧本杀文本和结构化 schema，第一版应保持 JSON 可审查、可测试。

## sebastian-ahmed/adventure_game

### 可借鉴设计

这是传统文字冒险项目，最有用的是测试和回放思路。它的 level 可以带 `testScript`，玩家有效命令也能记录成 `input-log.json`，测试脚本可以重放一整条通关路径。

它的状态模型包含：

- 当前 level。
- 当前地点。
- 玩家状态和背包。
- 地点连接、物品、阻碍物。
- 命令记录和测试脚本。

这些不是剧本杀的直接模型，但 “scripted playthrough” 非常适合当前项目。我们可以为 tiny case 和 medium case 增加回放文件，例如：

- 输入命令列表。
- 每一步期望当前阶段。
- 每一步期望新增证据或击破谎言。
- 最终期望指认结果和分数。

这样后续改 parser、LLM actor 或 schema 都能有回归基线。

### 暂不采用

不采用方向移动、背包、生命值、通用 obstruction、地图图算法和图形界面。当前项目不是通用文字冒险，而是推理案件运行时。

## RALWORKS/intficpy

### 可借鉴设计

`intficpy` 是完整 parser-based interactive fiction 引擎，有丰富的动词、房间、物品、NPC topic、保存加载、分数、事件序列和测试。对我们有用的是三点：

1. Topic 模型：NPC 可以按 `ask`、`tell`、`give`、`show` 对不同话题或物品给出不同反应。它提醒我们 `/ask` 和 `/confront` 应该分离，询问是话题，对质是证据动作。
2. Turn event 模型：每回合产生一组事件，再统一输出。这适合未来把 engine 返回值改成结构化 action result，同时保留文本。
3. Sequence 模型：可以记录阶段性剧情、菜单选项和中断恢复。当前不需要完整实现，但可以借鉴“阶段推进是显式状态，而不是自由文本判断”。

它的测试覆盖了 parser、conversation、travel、score、serializer 等很多系统。对我们而言，最应吸收的是测试粒度：每个命令都有最小单元测试，复杂流程另有回放测试。

### 暂不采用

不采用自然语言 parser、80 个动词、房间物品系统、通用序列引擎、pickle 存档。当前 slash command 足够支撑最小版本。

## qemqemqem/ClueEval

### 可借鉴设计

`ClueEval` 不是游戏运行时，而是推理评测生成器。它把案件拆成：

- killer、victim、weapon、location、setting。
- 每个角色的 means、motive、opportunity。
- true story 与 story to detective。
- 支持有罪、证明有罪、支持无罪、证明无罪、无关信息、叙事信息。
- before crime、during crime、after crime 等时间标签。
- 最终选择题和标准答案。

这些结构非常适合改进 medium case 和最终指认评分。当前 tiny case 只判定凶手，下一步 medium case 应该要求玩家提交：

- 凶手。
- 动机。
- 手法或凶器。
- 关键时间线。
- 支撑证据链。

同时，ClueEval 的 “红鲱鱼 + 证明无罪线索 + 只有一人同时具备动机、手段、机会” 很适合做剧本杀单人推理的公平性检查。

### 暂不采用

不采用它的 LLM 批量生成流程、不接 lm-evaluation-harness、不把当前项目变成模型评测基准。当前只借鉴证据分类和标准答案结构。

## 对当前 GameSchema v0.1 的映射

### 已经匹配的能力

当前 GameSchema 已能表达：

- 案件公开信息：`public_case`。
- NPC 公开/私密信息：`npc_characters.public_profile`、`private_profile`。
- NPC 可知真相和禁说真相：`known_truth_ids`、`conversation_rules.forbidden_truth_ids`。
- 场景和证据：`scenes`、`evidence`。
- 谎言与击破条件：`lies.required_evidence_ids`、`break_result`。
- 真相节点：`truth_model.truth_nodes`。
- 阶段推进：`phases`。
- 指认评分规则：`accusation_rules.scoring_items`。
- 复盘：`recap`。

### 建议补强但不立刻改 schema 的字段

短期可以先通过 engine runtime state 或 schema `additionalProperties` 试用，不急着升 schema 版本：

- evidence 的 `tags`：如 `motive`、`means`、`opportunity`、`timeline`、`red_herring`、`exonerating`。
- lie 的 `target_character_id`：便于 `/confront <character_id> <evidence_id>` 精准判定。
- accusation scoring item 的 `expected_evidence_ids` 或 `accepted_truth_ids`：用于证据链评分。
- truth node 的 `when`：如 before/during/after crime。
- scene 的 `search_once` 或 `search_state_text`：用于重复搜索反馈。

这些可以先在 medium case 中以非强制字段验证价值，再决定是否进入 `GameSchema v0.2`。

## 对 DetectiveGameEngine 的最小改进建议

### 1. 状态补齐

不重构类，只在现有 `__init__` 和 `get_progress_snapshot()` 中增加字段：

- `searched_scene_ids: set[str]`
- `shown_evidence_ids: set[str]`
- `accusation_history: list[dict]`
- `wrong_accusations: int`
- `game_over: bool`
- `won: bool`

`history` 建议保留，但记录内容从 `{"action": str, "value": str, "phase_id": str}` 稍微扩展为包含 `result_code`，例如 `found_evidence`、`no_new_evidence`、`lie_broken`、`wrong_accusation`。

### 2. 显式增加 `/confront`

当前 `/ask` 在证据满足时会自动击破 NPC 谎言。这个行为适合 smoke test，但与剧本杀体验不够一致。建议新增：

```text
/confront <character_id> <evidence_id>
```

规则：

- evidence 必须已发现。
- character 必须当前可接触。
- evidence 的 `can_confront_lie_ids` 与该 NPC 的 `lie_ids` 有交集。
- lie 的 `required_evidence_ids` 必须已满足。
- 成功后写入 `broken_lie_ids`，解锁 truth 和 phase。

为了小步改动，可以先保留 `/ask` 自动击破逻辑，但测试中新增显式 `/confront` 路线。下一版再决定是否让 `/ask` 只负责表演，不负责击破。

### 3. `/accuse` 从只判凶手扩展为结构化提交

保持 slash command，不做自然语言解析。建议支持：

```text
/accuse culprit=lin_wei motive=truth_motive_contract method=truth_poison_tea evidence=evidence_contract,evidence_security_log,evidence_tea_cup
```

最小实现可以解析 `key=value`：

- `culprit` 对 `truth_model.culprit_character_id`。
- `motive`、`method` 对 truth node id。
- `evidence` 对已发现证据 id 列表。
- 分数继续复用 `accusation_rules.scoring_items`，缺字段时只给凶手分。

这一步能让 “程序是裁判” 更完整，也能直接服务复盘中的遗漏内容。

### 4. 输出结构化 ActionResult

不必现在改 CLI，但 engine 内部可以新增私有 helper 返回结构化结果，再由现有方法转成文本。建议结果包含：

- `ok`
- `action`
- `message`
- `phase_id`
- `new_evidence_ids`
- `new_truth_ids`
- `broken_lie_ids`
- `unlocked_scene_ids`
- `score_delta`

这样未来接 UI、LLM actor 和 replay runner 时不会反复解析中文文本。

## 测试脚本建议

### 保留当前 smoke tests

当前 `scripts/test_detective_game_engine_v0_1.py` 应继续覆盖：

- `/status`
- `/search`
- `/show`
- `/ask`
- `/accuse`
- 命令路由

### 新增 replay 测试

建议新增：

- `scripts/playthroughs/tiny_detective_case_replay.json`
- `scripts/test_detective_game_replay_v0_1.py`

回放 JSON 可以先很小：

```json
{
  "schema_path": "scripts/schema_examples/tiny_detective_case_v0_1.json",
  "steps": [
    {
      "command": "/search scene_lobby",
      "expect_phase": "phase_investigation",
      "expect_new_evidence": ["evidence_visit_log"]
    },
    {
      "command": "/confront qin_yu evidence_visit_log",
      "expect_phase": "phase_confrontation",
      "expect_broken_lies": ["lie_qin_no_gap"]
    }
  ]
}
```

测试不应断言完整中文输出，只断言 snapshot、结果码和关键 id。这样文案以后改动不会打碎测试。

## Medium Case 建议

当前只有 tiny case，适合验证命令能跑通，但不够验证成熟推理产品能力。建议新增一个手写 medium case，而不是自动生成：

- 4 名 NPC：1 名真凶、2 名强嫌疑人、1 名信息型 NPC。
- 5 个场景：案发地、公共区、嫌疑人工作/房间、隐藏区域、复盘用区域。
- 8 到 10 个证据：至少 3 个关键证据、2 个红鲱鱼、2 个证明无罪证据、1 个时间线证据。
- 4 个谎言：其中 2 个属于真凶，2 个属于非真凶但能制造误导。
- 8 到 12 个 truth nodes：覆盖动机、手法、机会、时间线、伪装、无罪证明。
- 4 个阶段：intro、investigation、confrontation、recap。
- 结构化指认评分：凶手、动机、手法、关键证据链分别计分。

Medium case 的目的不是剧情华丽，而是验证这些产品能力：

- 玩家可能先怀疑错人。
- 错人有合理动机但缺关键机会。
- 真凶至少有一个谎言必须通过证据对质击破。
- 仅靠搜索不能满分，必须问话或对质。
- 最终复盘能指出遗漏证据和未击破谎言。

## 不做的大项

当前阶段明确不做：

- 不接真实 LLM。
- 不接向量数据库或 RAG。
- 不做自然语言命令解析。
- 不做通用文字冒险 parser。
- 不做多人房间、账号、支付、剧本库。
- 不做语音、图片生成、复杂 UI。
- 不改 `dm_engine.py`。

## 建议下一步执行顺序

1. 在 `detective_game_engine.py` 增加显式 runtime state：`searched_scene_ids`、`shown_evidence_ids`、`accusation_history`、`wrong_accusations`、`game_over`、`won`。
2. 新增 `/confront <character_id> <evidence_id>`，让证据对质成为独立动作。
3. 扩展 `/accuse` 支持 `key=value` 结构化提交，但保留旧的 `/accuse <suspect_id>` 兼容 tiny case。
4. 新增 replay JSON 和 replay 测试，测试只断言 id、phase、score，不断言整段文案。
5. 手写 medium case，用它验证红鲱鱼、证明无罪、阶段解锁、对质和结构化评分。

这个顺序是小步扩展现有 engine，而不是推倒重写。完成后再考虑 LLM actor prompt builder，会更稳。
