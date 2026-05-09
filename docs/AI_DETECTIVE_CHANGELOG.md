# AI Detective Change Log

## 2026-05-02 - Text import to GameSchema v0.3 draft loop

### Background

The current product priority is the full loop from plain md/txt input to an automatically structured, playable detective game. Authors should not need to learn schema fields; the system should generate structure and only ask friendly follow-up questions when NPC characterization is too thin.

### Changes

- Updated `scripts/import_text_script_v0_1.py`.
  - Added a GameSchema v0.3 draft branch alongside the existing ScriptSchema v0.2.1 draft.
  - Generates a conservative single-player case draft with imported characters, clues, truth nodes, phases, accusation rules, recap, and import trace.
  - Runs `validate_game_schema_v0_3()` after import and writes a dedicated validator report.
  - Runs `build_npc_author_questions()` and writes friendly NPC follow-up questions to `review.author_questions`.
  - Adds output files: `game_schema_v0_3.json`, `game_schema_v0_3_validator_errors.json`, `game_schema_v0_3_author_questions.md`, and `game_schema_v0_3_report.md`.
- Updated `detective_game_engine.py`.
  - NPC action history now records failed condition keys for selected rules and clearer selection reasons.
- Updated `scripts/evaluate_detective_game_v0_1.py`.
  - Added lightweight snapshot hashes before and after each turn.
  - Expanded snapshot delta reporting for clue state changes, NPC runtime changes, and newly fired NPC rules.
  - Added clue lifecycle coverage.
  - Added NPC rule diagnostics for repeated rules and invalid movement destinations.
- Updated tests.
  - `scripts/test_text_import_v0_1.py` now checks GameSchema v0.3 draft output, validation, and friendly author questions.
  - `scripts/test_detective_game_auto_eval_v0_1.py` now checks snapshot hashes, lifecycle coverage, and NPC rule explanation fields.

### Not Changed

- Did not modify `dm_engine.py`.
- Did not connect real LLM calls to importer or evaluator.
- Did not add UI, natural-language command parsing, or external runtime dependencies.
- Did not ask authors to hand-write `action_profile`, condition fields, truth ids, or schema syntax.

### Verification

- `python -B .\scripts\test_text_import_v0_1.py`
- `python -B .\scripts\test_detective_game_auto_eval_v0_1.py`

## 2026-05-02 - NPC author questions and profile completeness validation

### Background

The product direction is to avoid asking authors to learn GameSchema fields. The system should automatically derive runtime structure where possible, and only ask the author plain-language questions when NPC personality or character setup is too thin for believable roleplay.

### Changes

- Updated `game_schema_v0_3.py`.
  - Added `build_npc_author_questions()`.
  - Added NPC profile completeness checks for public identity, private pressure, voice/attitude, knowledge boundaries, and behavior goals.
  - Added `review.author_questions` validation.
  - Incomplete NPC setup now requires matching author questions instead of silently passing as a weak character.
  - Author-facing questions reject technical wording such as `schema`, `json`, `public_profile`, `private_profile`, `truth_id`, and `action_profile`.
- Updated `schemas/game_schema_v0_3.schema.json`.
  - Added the `review.author_questions` array shape.
  - Each question records `question_id`, `target_type`, `target_id`, `topic`, `question`, `why`, and `blocking`.
- Updated `scripts/schema_examples/medium_detective_case_v0_3.json`.
  - Added `review.author_questions: []` because the hand-authored medium fixture already has sufficiently complete NPC setup.
- Updated `scripts/test_game_schema_v0_3.py`.
  - Confirms complete cases do not ask unnecessary questions.
  - Confirms thin NPC profiles require targeted `review.author_questions`.
  - Confirms generated questions are friendly and avoid schema jargon.

### Not Changed

- Did not modify `dm_engine.py`.
- Did not ask authors to hand-write `action_profile`, lifecycle, phase conditions, or truth graph fields.
- Did not connect this to the text importer yet; the helper and validator are ready for that next step.

### Verification

- `python -B .\scripts\test_game_schema_v0_3.py`
- `python -B .\scripts\test_game_schema_v0_1.py`
- `python -B .\scripts\test_detective_game_engine_v0_1.py`
- `python -B .\scripts\test_medium_detective_game_v0_3_replay.py`
- `python -B .\scripts\test_detective_game_auto_eval_v0_1.py`

## 2026-05-02 - Open-source reference review and GameSchema v0.3 minimum slice

### Background

This change follows the reference-review plan: read useful patterns from boardgame.io, ink, Yarn Spinner, Foundry dnd5e, and Fluid HTN, then apply only a small runtime-safe slice to the current single-player detective engine.

### Changes

- Added `external_references/` to `.gitignore`.
- Attempted all requested shallow clones into `external_references/`; all failed due GitHub connection resets/timeouts, and the results were recorded in `external_references/clone_status.json`.
- Retried the failed clones with HTTP/1.1, partial clone, and sparse checkout; all five repositories were cloned successfully, and the retry result was recorded in `external_references/clone_status_retry.json`.
- Added `docs/references_review.md`.
  - Records clone status.
  - Summarizes transferable ideas from phases/moves/replay, narrative conditions, dialogue commands, data model separation, and lightweight HTN.
  - Adds a source-code review addendum based on checked local files from boardgame.io, ink, Yarn Spinner, foundryvtt/dnd5e, and Fluid HTN.
  - Records the product direction that authors should not be asked to hand-write schema guides; only incomplete NPC personality/person setup should generate targeted author questions.
  - Maps each idea to current files such as `game_schema.py`, `script_schema.py`, `detective_game_engine.py`, the medium case, and evaluator.
  - Splits immediate v0.3 work from v0.4 deferrals.
- Added side-by-side GameSchema v0.3 support.
  - New validator: `game_schema_v0_3.py`.
  - New JSON Schema shell: `schemas/game_schema_v0_3.schema.json`.
  - New medium fixture: `scripts/schema_examples/medium_detective_case_v0_3.json`.
  - New replay fixture: `scripts/playthroughs/medium_detective_game_v0_3_replay.json`.
- Updated `detective_game_engine.py`.
  - Loads v0.1 and v0.3 schemas without changing the public command interface.
  - Adds `clue_state_by_id` to progress snapshots.
  - Supports v0.3 clue lifecycle for hidden/discoverable/discovered/revealed clues.
  - Uses scene entry conditions and truth unlock conditions while preserving v0.1 behavior.
- Added tests.
  - `scripts/test_game_schema_v0_3.py` validates dangling refs, unreachable critical clues, missing phase exits, truth nodes without evidence, incomplete ending rules, and NPC spoiler boundaries.
  - `scripts/test_medium_detective_game_v0_3_replay.py` validates v0.3 replay plus auto-eval completion.

### Not Changed

- Did not modify `dm_engine.py`.
- Did not import any reference project as a dependency.
- Did not add a natural-language command parser, UI, full HTN planner, or general interactive-fiction runtime.

## 2026-05-01 - 自动测评工具与 NPC 行动可测性

### 背景

用户暂时不想通过人工试玩来检查功能，因此本次新增离线自动测评工具，用代码模拟几类玩家路径，生成可检查的结构化报告。目标是减少试玩负担，同时让 NPC 行动纲领更容易发现死规则、拼写错误和失控风险。

### 本次改动

- 新增 `scripts/evaluate_detective_game_v0_1.py`
  - 默认使用确定性规则模板，不读取真实 API。
  - 支持 `--case tiny|medium|path`、`--policy completion|misled|npc-autonomy|all`、`--json`、`--output`、`--llm-eval` 和 `--max-llm-turns`。
  - `completion` 使用 schema 标准答案做 oracle completion，验证案件是否能完整通关，不伪装成真实玩家推理能力。
  - `misled` 模拟被红鲱鱼误导后的错误指认，检查错误结局和复盘状态是否稳定。
  - `npc-autonomy` 专门触发 medium case 的 NPC 行动规则，检查 fired/dead rules、可见事件和最终 runtime state。
  - 报告包含 summary、coverage、npc_action_report、risk_flags 和逐回合 ActionResult 记录。
- 更新 `detective_game_engine.py`
  - NPC 行动规则支持 `max_times` 与 `cooldown_turns`，用于限制重复触发和事件刷屏。
  - `npc_action_history` 增加 `matched_conditions`、`source_action` 和 `reason`，方便回放和排查规则为什么触发。
  - 继续只向 `ActionResult.data["npc_action_policies"]` 暴露执行结果，不暴露 goals/directive。
- 新增 `scripts/test_detective_game_auto_eval_v0_1.py`
  - 覆盖 tiny completion、medium completion、medium misled、medium npc-autonomy 和 action_profile lint。
  - 断言报告不包含 `private_profile`、`culprit_character_id`、完整 `action_profile` 或 `directive` 等敏感标记。
- 更新 `.gitignore`
  - 忽略 `scripts/eval_outputs/`，避免本地测评报告污染仓库。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级 GameSchema 大版本。
- 默认测评不调用真实 LLM；只有显式 `--llm-eval` 才会加载 `OpenAINPCActor.from_env()`。
- 未让 LLM 选择 NPC 行动、推进阶段、解锁线索或参与评分。
- 未引入行为树、GOAP、NPC-NPC 自由对话等大型框架。

### 下一步建议

1. 给 `action_profile` 写一份作者指南，说明推荐 trigger/conditions/action 写法和常见死规则。
2. 为 evaluator 增加一个 `--output scripts/eval_outputs/...` 的批量报告命令，用于每次改 medium case 后自动留档。
3. 等 NPC 行动规则稳定后，再考虑加入“NPC 计划变更”或“阶段性行动目标”，仍保持程序裁判、LLM 表演。

## 2026-05-01 - NPC 行动纲领与轻量自主行动

### 背景

在 NPC 视角隔离和显式对质稳定后，需要让 NPC 不只是“被问才回答”，而是能按结构化行动纲领在玩家行动后产生轻量状态变化。目标不是开放世界模拟，而是用程序控制的回合制自主行动提升可玩性，同时继续保持 LLM 只负责表演。

### 本次改动

- 更新 `detective_game_engine.py`
  - 新增 NPC runtime state：`location_scene_id`、`stance`、`stress`、`suspicion_target_id`、`last_action_id`。
  - 新增 `npc_action_history` 和 `visible_npc_events`，并写入 `get_progress_snapshot()`。
  - 成功的 `/search`、`/ask`、`/confront` 后会运行 deterministic NPC autonomy tick；`/status`、失败命令和 `/accuse` 不触发。
  - 支持 `action_profile.rules` 的最小规则匹配：trigger、phase、目标角色、场景、证据、已发现证据、已击破谎言、本回合新增证据/谎言、NPC stance/stress。
  - 第一版支持行动类型：`stay`、`move_to_scene`、`change_stance`、`raise_stress`、`redirect_suspicion`、`ask_player_question`、`withdraw`。
  - NPC 移动现在会影响 `_is_npc_reachable()`；玩家只能询问/对质当前可接触 NPC。
  - `ActionResult.data` 新增 `npc_events`、`visible_events` 和 `npc_action_policies`；玩家-facing 文案会附加可见 NPC 事件。
  - `/status` 增加当前可接触 NPC 和最近 NPC 事件，但不暴露 goal/directive。
  - Actor context 增加 `npc_runtime` 和 `selected_action_policy`，LLM 只能表演程序已选行动。
- 更新 `scripts/schema_examples/medium_detective_case_v0_1.json`
  - 只在 medium case 增加 `action_profile`，tiny case 保持静态基线。
  - Arden 会在 security 搜索后转移怀疑到 Liam，并在 rooftop keycard 对质后退回 atrium。
  - Mira 会在 security 线索出现后变得紧张。
  - Liam 会在红纤维被发现后表现出被误导指向的不耐烦。
  - Nova 会在 drone receipt 出现后紧张，并在对质后转为 cooperative。
- 更新测试和 replay
  - Engine 测试覆盖 NPC 初始位置、autonomy tick、visible event、runtime movement 对可接触性的影响、对质后的 selected action policy。
  - Medium replay 覆盖 security 搜索、rooftop 搜索、Nova 对质、Arden 对质后的 NPC 事件和 runtime state。
  - Actor 测试确认 context 只包含 runtime 与 selected policy，不泄露完整 `action_profile`。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级 GameSchema 大版本；`action_profile` 使用当前 schema 的 `additionalProperties` 试用。
- 未让 LLM 选择或执行 NPC 行动。
- 未做复杂 GOAP、行为树框架、自然语言意图解析或 NPC-NPC 自由对话。

### 下一步建议

1. 做一次 medium case 的真实 `--llm` 试玩，观察行动纲领是否让 NPC 更有“人味”，以及事件文案是否太吵。
2. 给 `action_profile` 增加一个小型作者指南，说明 trigger、conditions、action 的推荐写法。
3. 如果后续多个案件都使用稳定，再把 `action_profile` 正式纳入 GameSchema v0.2。

## 2026-05-01 - Holmes 风格 NPC 视角隔离增强

### 背景

项目已经有可选 AI NPC 扮演层，但上下文结构仍偏通用。为了更接近 `holmes` 的“按嫌疑人视角组织信息”思路，本次在不重写 actor 层的前提下，把传给 LLM 的内容改为更清晰、可审计的单 NPC 视角包。

### 本次改动

- 更新 `detective_game_engine.py`
  - `_build_npc_actor_context()` 改为输出 `viewer_character_id`、`case_public`、`self_view`、`other_characters_public`、`player_known`、`allowed_truths`、`active_lies`、`broken_lies_this_turn`、`presented_evidence` 等分区。
  - 默认仍不向 LLM 传 `private_profile`、`truth_model.culprit_character_id`、完整 schema、完整 truth/lies 或未发现证据。
  - 新增 actor context 审计：发现敏感字段、forbidden truth、locked truth 或 hidden evidence 时，不调用 actor，直接 fallback 到规则模板。
  - audit 失败会在 `ActionResult.data.actor_error` 中记录 `context_audit_failed:<reason>`。
- 更新 `detective_llm_actor.py`
  - Prompt 改为基于 NPC perspective packet，强化“只能使用包内信息”。
  - 明确 `/ask` 只做普通角色回答，`/confront` 必须跟随程序裁判的 `judge_result` 和 `broken_lies_this_turn`。
- 更新 `scripts/test_detective_llm_actor_v0_1.py`
  - 断言 actor context 不含私密字段、真凶字段、forbidden truth、locked truth 和 hidden evidence。
  - 断言 ask/confront 的上下文形状符合 NPC 视角包。
  - 新增 audit fallback 测试，确认泄露上下文不会传给 fake actor。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级 GameSchema。
- 未改变 `npc_actor`、`OpenAINPCActor.from_env()` 或 CLI `--llm` 的使用方式。
- 未让 LLM 参与线索释放、谎言击破、阶段推进或最终评分。

### 下一步建议

1. 做一次 medium case 的真实 `--llm` 人工试玩，检查 NPC 语气、对质张力和是否有软剧透。
2. 增加一份“LLM actor prompt 调参记录”，把人工试玩观察转成可追踪 prompt 迭代。
3. 在后续文本导入器中生成更清楚的 `known_truth_ids` 和 `forbidden_truth_ids`，否则视角隔离质量会受 schema 输入质量限制。

## 2026-05-01 - 普通询问与结构化指认评分

### 背景

显式 `/confront` 已经接管“出示证据击破谎言”的核心动作，因此 `/ask` 不应继续隐式推进裁判状态。本次改动把普通对话和证据对质的边界切清楚，并把最终指认从 culprit-only 扩展为凶手、动机、手法、证据链的结构化评分。

### 本次改动

- 更新 `detective_game_engine.py`
  - `/ask` 现在只记录询问、推进普通阶段和生成 NPC 回答，不再自动击破谎言、不再解锁 truth/scene。
  - `/confront` 继续作为唯一的谎言击破入口。
  - `accuse_result()` 新增结构化参数：`motive_truth_id`、`method_truth_id`、`evidence_chain_ids`、`lie_ids`、`truth_ids`。
  - `/accuse` 命令新增 key=value 格式：
    - `motive=<truth_id>`
    - `method=<truth_id>`
    - `evidence=<evidence_id,...>`
    - `lies=<lie_id,...>`
    - 可选 `truths=<truth_id,...>`
  - 评分现在遍历 `accusation_rules.scoring_items`，输出总分、满分、是否通过、是否满分、缺失字段、无效提交和逐项 `score_breakdown`。
  - 玩家提交的证据必须已发现、谎言必须已击破、truth 必须已解锁，才会计入分数。
  - 旧命令 `/accuse <suspect_id>` 保持兼容，但只能拿凶手分，并在结果中标出缺少 motive/method/evidence_chain。
- 更新 replay 和测试
  - tiny replay 现在搜索档案室，并用结构化 `/accuse` 完整通关。
  - medium replay 的正确路径改为结构化提交，完整分数为 10。
  - engine 测试覆盖 `/ask` 不再击破、结构化满分指认、旧指认兼容和新评分字段。
  - LLM actor 测试更新为普通 `/ask` 不泄露被击破后的 truth，对质测试继续验证 actor 不改裁判结果。
- 更新 CLI 帮助
  - 展示结构化 `/accuse` 示例格式。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级 GameSchema 大版本。
- 未加入自然语言解析；结构化指认仍是命令式 key=value。
- 未让 LLM 参与最终评分。

### 下一步建议

1. 给 CLI 增加 `/help accuse` 或示例输出，降低结构化提交的输入门槛。
2. 给 structured accusation 增加更友好的中文复盘，把每个扣分项翻译成玩家能理解的遗漏原因。
3. 在 Markdown/txt 导入器里优先生成 `accusation_rules.scoring_items`，否则最终评分体验会很薄。

## 2026-05-01 - 显式证据对质

### 背景

上一版已经能通过 `/ask` 隐式触发谎言击破，但剧本杀推理游戏里最核心的手感应该是“拿出证据对质”。本次改动把证据对质从普通询问中拆出来，继续保持程序裁判、LLM 表演的边界。

### 本次改动

- 更新 `detective_game_engine.py`
  - 新增 `confront_result(character_id, evidence_id)` 和兼容文本方法 `confront()`。
  - 新增命令 `/confront <character_id> <evidence_id>`。
  - 对质时依次校验：游戏是否结束、角色是否存在且可接触、证据是否存在且已发现、证据是否匹配该角色谎言、组合证据是否已满足。
  - 成功对质后由规则引擎击破谎言，解锁 truth、阶段和新场景，并返回稳定 `ActionResult.code=confront_lie_broken`。
  - 增加稳定失败 code：`confront_hidden_evidence`、`confront_no_matching_lie`、`confront_lie_already_broken`、`confront_missing_required_evidence` 等。
  - 可选 LLM actor 现在也能接收对质上下文，但仍只能改写角色反应，不能决定谎言是否击破。
- 更新 `scripts/run_tiny_detective_game.py`
  - CLI 帮助中加入 `/confront`。
- 更新 tiny/medium replay
  - 关键谎言击破路径改为显式 `/confront`。
  - medium case 中 Mira、Nova、Arden 的谎言击破都通过证据对质完成。
- 更新测试
  - 增加对显式对质成功、重复对质、隐藏证据、无匹配谎言、组合证据不足的断言。
  - 增加 LLM actor 对质上下文测试，验证不泄露 private/forbidden truth，且 actor 不改变裁判结果。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级 GameSchema 大版本。
- 未让 LLM 参与核心判定。
- 未删除 `/ask` 的旧兼容行为；它目前仍能按旧逻辑触发谎言击破，后续可逐步迁移为纯对话。
- 未加入自然语言命令解析、UI 或多人能力。

### 下一步建议

1. 将 `/ask` 的自动击破谎言改为可配置或逐步关闭，让“普通询问”和“证据对质”的产品边界更清楚。
2. 扩展 `/accuse` 为结构化提交：凶手、动机、手法、证据链分别评分。
3. 用 medium case 做一轮 `--llm` 人工试玩，重点调对质时 NPC 的情绪变化和剧透控制。
4. 启动 Markdown/txt 到 GameSchema draft 的最小导入器，尽快展示“文本 -> 可玩游戏”的差异化闭环。

## 2026-05-01 - Playable AI Vertical Slice

### 背景

在 tiny/medium case 和结构化 replay 稳定后，下一步需要尽快让单人推理游戏具备“AI 嫌疑人表演”的手感，同时继续坚持核心原则：LLM 只是演员，程序仍然是裁判。

### 本次改动

- 新增 `detective_llm_actor.py`
  - 提供可选的 `OpenAINPCActor`。
  - 使用 OpenAI-compatible chat completions，但只在显式启用时懒加载客户端。
  - 不复用 `config.py`，避免默认测试或 replay 被 API key 绑定。
  - LLM prompt 明确禁止决定裁判结果、泄露隐藏真相、泄露禁用 truth、引用未发现证据。
- 更新 `detective_game_engine.py`
  - `DetectiveGameEngine` 新增可选参数 `npc_actor`。
  - 默认不传 actor 时仍使用原规则模板，保持 replay 确定性。
  - `ask_result()` 先由规则引擎完成谎言击破、truth 解锁、阶段推进和 `ActionResult.code` 判定，再把受限 context 交给 actor 改写 NPC 表达。
  - 新增 NPC context builder，只暴露公开信息、当前阶段、已发现证据、允许 truth、当前仍可说的谎言、刚被击破的谎言和对话历史。
  - 新增每个 NPC 的对话历史快照，便于后续 LLM 角色连续性。
  - actor 出错或返回空文本时自动回退到确定性模板，`ActionResult.code` 不变。
- 更新 `scripts/run_tiny_detective_game.py`
  - 新增 `--llm` 参数。
  - 默认仍是规则模板；加 `--llm` 后才调用 OpenAI-compatible NPC actor。
- 更新 `.env.example`
  - 增加 `AI_DETECTIVE_LLM_MODEL`、timeout、temperature、max tokens 等可选配置。
- 新增 `scripts/test_detective_llm_actor_v0_1.py`
  - 使用 fake actor 测试，不触发真实网络。
  - 验证 actor 只能拿到受限上下文。
  - 验证 actor 不能改变裁判结果、击破谎言、阶段和 code。
  - 验证 actor 失败时回退到模板输出。

### 没有改动

- 未修改 `dm_engine.py`。
- 未改变 GameSchema 版本。
- 未让 LLM 决定线索释放、谎言击破、阶段推进或最终评分。
- 未让 replay 依赖真实 LLM。

### 下一步建议

1. 新增显式 `/confront <character_id> <evidence_id>`，让最有戏剧感的“出示证据”成为核心交互。
2. 为 `OpenAINPCActor` 增加一条人工试玩 demo 流程，用 medium case 检查角色是否自然、是否剧透、对质是否有冲击力。
3. 开始做 Markdown 模板到 GameSchema draft 的最小导入器，打通“输入文本 -> 可玩游戏”的产品卖点。

## 2026-05-01 - Phase 2 中等案件与回放验收

### 背景

在 `DetectiveGameEngine` 支持结构化 `ActionResult`、显式状态和 tiny replay 后，需要一个中等复杂度案件来压力测试当前 GameSchema v0.1 与运行时：多角色、多场景、多证据、误导线索、多角色谎言、组合证据解锁真相、错误指认和正确通关。

### 本次改动

- 新增 `scripts/schema_examples/medium_detective_case_v0_1.json`
  - 4 个角色：真凶、安保、投资人误导嫌疑人、实验室助手。
  - 5 个场景：中庭、安保室、样本实验室、屋顶服务门、冷藏柜。
  - 12 条证据，其中 `evidence_red_fiber` 和 `evidence_drone_receipt` 为误导线索。
  - 3 条角色谎言，覆盖 Mira、Arden、Nova。
  - 11 个 truth nodes，覆盖动机、手法、时间线、误导澄清、组合证据真相和真凶。
  - `truth_combo_access_route` 需要 `evidence_manual_override` 与 `evidence_rooftop_keycard` 同时满足后，通过击破 Arden 的谎言解锁。
- 新增 `scripts/playthroughs/medium_detective_game_replay.json`
  - 包含一条错误指认路径：被红纤维误导后指认 Liam。
  - 包含一条完整正确路径：搜索多个场景、查看证据、询问角色、击破谎言、解锁组合真相、最终指认 Arden。
- 新增 `scripts/test_medium_detective_game_replay_v0_1.py`
  - 使用 `ActionResult.code`、新增 id 列表、snapshot 和 accusation result 断言。
  - 不依赖大段玩家-facing 文案。
- 更新 `scripts/test_game_schema_v0_1.py`
  - 增加 medium case 的 schema 加载与基础复杂度断言。

### 没有改动

- 未修改 `dm_engine.py`。
- 未接入 LLM。
- 未升级 GameSchema 大版本。
- 未新增玩法命令。
- 未对 `DetectiveGameEngine` 做运行时补丁；当前结构化状态与多证据谎言击破已能支撑本次 medium case。

### 下一步建议

1. 基于 medium case 增加显式 `/confront <character_id> <evidence_id>`，把“询问触发击破”拆成更像剧本杀的证据对质动作。
2. 扩展 `/accuse` 的结构化评分，让 motive、method、evidence_chain 也由程序计分，而不只是当前 culprit 分。
3. 将 medium case 用作后续 LLM actor 接入前的回归基线，确保 prompt 文案变化不会影响裁判逻辑。

## 2026-05-01 - DetectiveGameEngine 运行时稳定化

### 背景

当前阶段目标不是增加玩法，而是让单人推理运行时从“能跑的 demo”变成“可测试、可检查、可回放、可复盘”的系统基础。核心原则仍然是：LLM 以后只做演员，程序和 GameSchema 负责状态与裁判。

### 本次改动

- 更新 `detective_game_engine.py`
  - 新增 `ActionResult` 结构化结果，固定包含 `ok`、`action`、`code`、`message`、`phase_id`、`turn_index`、`command`、`target_id`、新增线索/真相/谎言/场景、`score_delta` 和 `data`。
  - 新增双轨 API：`status_result()`、`search_result()`、`show_result()`、`ask_result()`、`accuse_result()`、`handle_command_result()`。
  - 保留旧接口：`get_status_text()`、`search()`、`show()`、`ask()`、`accuse()`、`handle_command()` 继续返回文本，兼容 CLI demo。
  - 补齐显式状态：已搜索场景、已查看证据、行动历史、指认历史、错误指认次数、游戏结束状态、胜负状态、回合序号、最后一次行动结果。
  - 扩展 `get_progress_snapshot()`，让测试和未来 UI 可以直接读取结构化状态，不需要解析玩家-facing 文案。
  - 指认后设置 `game_over=True`；正确指认为 `won=True`，错误指认为 `won=False` 并累计 `wrong_accusations`。
  - 指认后非 `/status` 命令返回稳定 code：`game_already_over`。
- 更新 `scripts/test_detective_game_engine_v0_1.py`
  - 保留文本兼容检查。
  - 新增对 `ActionResult.code`、`ok`、phase、新增证据、击破谎言、终局状态、错误指认次数和历史记录的断言。
- 新增 `scripts/playthroughs/tiny_detective_game_replay.json`
  - 用命令脚本描述 tiny case 的稳定通关路径。
- 新增 `scripts/test_detective_game_replay_v0_1.py`
  - 按 replay JSON 执行 `/status`、`/search`、`/show`、`/ask`、`/accuse`。
  - 只断言稳定结构字段和关键 id，不依赖完整中文文案。

### 没有改动

- 未修改 `dm_engine.py`。
- 未升级或修改 GameSchema。
- 未接入真实 LLM。
- 未新增 `/confront`、自然语言解析、UI 或新玩法。

### 下一步建议

1. 在当前稳定状态基础上新增显式 `/confront <character_id> <evidence_id>`，让证据对质与普通询问分离。
2. 将 `/accuse <suspect_id>` 扩展为结构化提交，逐步支持凶手、动机、手法和证据链评分。
3. 手写 medium case，用更多红鲱鱼、证明无罪线索和多阶段对质验证运行时能力。

> 本文档专门记录“剧本文本 -> 结构化 schema -> 单人 AI 推理游戏”方向的每次改动。后续相关修改都应在这里追加说明，便于持续优化和回溯。

## 2026-04-30 - 新增 DetectiveGameEngine 最小可玩版本

### 背景

在 GameSchema v0.1 基础建立后，需要证明 `scripts/schema_examples/tiny_detective_case_v0_1.json` 可以通过命令式交互运行，形成“schema -> 可玩案件”的第一条闭环。

### 本次改动

- 新增 `detective_game_engine.py`
  - 读取并校验 GameSchema。
  - 仅允许 `review.status=confirmed` 的案件进入游戏。
  - 管理当前阶段、已解锁场景、已发现线索、已解锁真相、已击破谎言和指认结果。
  - 支持确定性命令：
    - `/status`：查看阶段、已发现线索、可搜索区域、已击破谎言。
    - `/search <area_id>`：搜索已解锁区域并公开该区域证据。
    - `/show <clue_id>`：查看已发现证据详情。
    - `/ask <character_id> <question>`：使用规则模板生成 NPC 回答，不调用 LLM。
    - `/accuse <suspect_id>`：根据 `truth_model.culprit_character_id` 判定指认结果并进入复盘。
  - 谎言击破采用规则判定：当某 NPC 的谎言所需证据都已发现时，询问该 NPC 会自动击破谎言、解锁对应真相和阶段。

- 新增 `scripts/run_tiny_detective_game.py`
  - 提供最小 CLI demo。
  - 默认加载 `scripts/schema_examples/tiny_detective_case_v0_1.json`。
  - 不接 LLM、不做 UI、不做自然语言解析。

- 新增 `scripts/test_detective_game_engine_v0_1.py`
  - 覆盖 `/status`、`/search`、`/show`、`/ask`、`/accuse` 和命令路由。
  - 验证大厅搜索、秦雨谎言击破、办公室解锁、林唯谎言击破、正确/错误指认。

### 没有改动

- 未接入真实 LLM。
- 未实现自然语言意图解析。
- 未实现 UI、存档、复杂评分或完整动机/手法填写。
- 未修改旧 `dm_engine.py` 多人 DM 主流程。

### 下一步建议

1. 将 `/accuse <suspect_id>` 扩展为结构化提交：`culprit`、`motive`、`method`、`evidence_chain`。
2. 增加 `/show <npc> <evidence>` 或 `/confront`，让证据对质从“询问时自动击破”升级为显式动作。
3. 为 tiny case 增加 replay JSON，作为后续导入器和运行时改动的回归基线。

## 2026-04-30 - 建立 GameSchema v0.1 最小基础

### 背景

项目目标从“多人剧本杀 AI DM”调整为“把剧本杀文本转化为可运行的单人 AI 推理游戏”。新目标强调：

- LLM 是演员，程序是裁判。
- 线索释放、谎言击破、阶段推进、最终评分必须由结构化 schema 和规则引擎控制。
- 第一版只跑通一个完整案件，不做平台、多人房间、支付、剧本库和复杂语音。

### 本次改动

- 新增 `game_schema.py`
  - 定义 `GAME_SCHEMA_VERSION = "game_schema_v0.1"`。
  - 提供 `load_game_schema()` 和 `validate_game_schema()`。
  - 覆盖顶层必填字段、枚举字段、唯一 ID、跨字段引用、阶段、谎言、证据、真相节点、最终指认评分规则等基础校验。

- 新增 `schemas/game_schema_v0_1.schema.json`
  - 提供 GameSchema v0.1 的 JSON Schema 草案。
  - 明确单人侦探模式的主要结构：案件信息、来源信息、人工复核、公开案情、NPC、场景、证据、谎言、真相模型、阶段、机制、评分和复盘。

- 新增 `docs/game_schema_v0_1.md`
  - 说明 GameSchema 的目标、原则、顶层字段职责和 v0.1 最小闭环。
  - 明确与现有 ScriptSchema 的边界：GameSchema 服务单人侦探游戏，ScriptSchema 继续作为旧多人主持流程资产。

- 新增 `scripts/schema_examples/tiny_detective_case_v0_1.json`
  - 提供一个可校验的最小单人推理案件《午夜档案室》。
  - 包含 3 个 NPC、3 个场景、4 个证据、2 个谎言、7 个真相节点、5 个阶段和完整最终评分规则。

- 新增 `scripts/test_game_schema_v0_1.py`
  - 增加 GameSchema 基础 smoke tests。
  - 覆盖 JSON Schema 可解析、示例案件可加载、未知引用拒绝、重复 ID 拒绝、最终指认必填字段校验。

### 没有改动

- 未修改现有 `dm_engine.py` 主流程。
- 未删除或降级旧多人 DM 功能，只新增并行的 GameSchema 方向基础。
- 未接入 LLM、TTS、BGM、SFX 或前端。

### 下一步建议

1. 新增 `DetectiveGameEngine` 最小运行时，只支持加载 confirmed GameSchema。
2. 实现 `/search`、`/ask`、`/show`、`/accuse`、`/status` 的单人 CLI 闭环。
3. 将 `tiny_detective_case_v0_1.json` 做成 replay，用无 API 测试验证阶段推进和证据击破。
4. 再改造 md/txt 导入器，让它输出 GameSchema draft 和人工复核报告。
