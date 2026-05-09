# AI-DM Demo Playbook

面向比赛展示与后续开发的最短操作手册。本文只说明当前可演示能力，不代表完整商业剧本自动导入已经完成。

## 1. 启动演示

默认固定 demo：《Monsters Halloween Night》。

```powershell
python -B .\main.py
```

启动第二个 schema 示例剧本：

```powershell
python -B .\main.py --script-id second_sample
```

启动指定 schema 文件：

```powershell
python -B .\main.py --schema-path .\scripts\schema_examples\fixed_truth_minimal.json
```

关闭 schema runtime，回到旧固定流程兜底：

```powershell
python -B .\main.py --no-schema
```

也可以用环境变量选择：

```powershell
$env:AI_DM_SCRIPT_ID="second_sample"
python -B .\main.py
```

真实运行需要 `.env` 中有可用 LLM key；离线 replay/acceptance 测试不需要真实 key。

## 2. 展示流程建议

### Monsters demo

1. 启动：`python -B .\main.py`
2. 开场后输入 `理解了` 进入讨论。
3. 使用 `/phase next` 推进 schema 阶段。
4. 使用 `/packet wolf` 展示“主持人可查看私密角色包，但不会进公共知识/prompt”。
5. 继续 `/phase next` 到 `clue_1_release`、`search`、`clue_2_release`，展示线索自动公开。
6. 旧完整局仍可用 `/vote`、结局后 `/review` 演示固定剧本复盘。

### Second sample

```powershell
python -B .\main.py --script-id second_sample
```

适合展示多剧本切换、不同 cast/public_materials/clues/reveal_rules 随 `script_id` 改变。

### Action/form runtime 示例

```powershell
python -B .\main.py --schema-path .\scripts\schema_examples\emergent_resolution_minimal.json
```

示例命令：

```text
/schema submit actor=Claude form=action_card action=GUARD target=Andre
/schema submit actor=Andre form=action_card action=GUARD target=Andre
/schema submit actor=Beatrice form=action_card action=MURDER target=Andre
/schema resolve
```

预期：两次 `GUARD` 同目标会阻止 `MURDER`。未被阻止的 `MURDER` 会改变 `alive/can_vote/can_be_candidate`，并可驱动后续 phase route。

### Final reveal 示例

```powershell
python -B .\main.py --schema-path .\scripts\schema_examples\fixed_truth_minimal.json
```

示例命令：

```text
/phase next
/schema reveal
/schema reveal code_word=OPEN
```

预期：终局前 `/schema reveal` 会被拒绝；进入 accusation/resolution/recap 后，按 `ending_rules.final_reveal_sequence.step` 顺序公开。需要 `required_code_word` 的步骤必须给对 code word。

## 3. 常用命令

| 命令 | 用途 |
|---|---|
| `/phase next` | 推进到下一个 schema phase，并按 phase 解锁材料、线索、role_packets |
| `/phase <phase_id>` | 直接进入指定 schema phase |
| `/packet <role>` | 主持人本地查看已解锁私密包；不会进入 public knowledge 或 prompt |
| `/schema submit actor=<id> form=<id> action=<ACTION> target=<id>` | 提交 action/form |
| `/schema submit actor=<id> form=<id> vote=<id>` | 提交投票表单 |
| `/schema submit actor=<id> form=<id> declaration="..."` | 提交公开声明，声明会先过防剧透过滤 |
| `/schema resolve` | 本地 deterministic 结算 action/form，并按结果尝试推进 phase |
| `/schema reveal [code_word=...]` | 推进 `final_reveal_sequence` 的下一步公开 |
| `/clue1`、`/clue2` | 旧 demo 手动公开线索，保持兼容 |
| `/vote` | 旧固定剧本最终答案录入流程 |
| `/review` | 结局后结构化复盘 |
| `status` | 查看当前阶段、线索、schema 状态和主持建议 |

## 4. Replay 与验收测试

Replay 用 JSON 脚本模拟完整局部流程，不调用真实 API。

```powershell
python -B .\scripts\replay_playthrough.py .\scripts\playthroughs\schema_runtime_replay.json
```

Text/Markdown 半自动导入小样本：

```powershell
python -B .\scripts\import_text_script_v0_1.py .\scripts\import_samples\tiny_fixed_truth.md --out-dir .\scripts\import_outputs\tiny_fixed_truth --script-id tiny_fixed_truth_imported
python -B .\scripts\import_text_script_v0_1.py .\scripts\import_samples\tiny_fixed_truth.md --out-dir .\scripts\import_outputs\tiny_fixed_truth --script-id tiny_fixed_truth_imported --confirm-manual-review --force
python -B .\scripts\generate_ai_review_pack.py .\scripts\import_outputs\tiny_fixed_truth --force
python -B .\scripts\replay_playthrough.py .\scripts\playthroughs\imported_tiny_replay.json
python -B .\scripts\test_text_import_v0_1.py
```

第一条命令会拒绝写入并提示需要人工确认；第二条命令在显式确认后输出 `script.json`、`import_report.md`、`schema_gap_report.md`、`validator_errors.json`、`review_prompt.md`、`review_checklist.md`、`high_risk_items.md`。导入报告包含 source trace、置信度、缺失字段、人工待确认项和 private/public 隔离告警。`generate_ai_review_pack.py` 可对已有 import output 重新生成 GPT/Claude 语义复核材料。

当前 replay 覆盖：

- demo 启动、phase 推进、线索公开；
- `/packet` 私密信息不进入 public knowledge/prompt；
- action/form submit 与 `/schema resolve`；
- `final_reveal_sequence` 顺序、code word、终局前不泄露。
- text/markdown 导入样本生成的 draft schema 可被 runtime 加载，并通过 replay 验证；导入器 mock 测试覆盖固定真相、分轮私密包、行动机制三类文本。

基础 acceptance：

```powershell
python -B .\scripts\acceptance_monsters_halloween.py
python -B .\scripts\test_script_schema_v0_2_1.py
```

语法检查：

```powershell
python -B -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p)) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in p.parts and '__pycache__' not in p.parts]; print('AST OK')"
```

## 5. 当前已支持

- ScriptSchema v0.2.1 加载、校验、demo/second_sample/custom schema 选择。
- `public_materials`、`cast`、`phases`、`clues`、`reveal_rules` 接入运行时。
- `role_packets` 解锁与可见性隔离：私密包不进 public prompt。
- 防剧透过滤：hint、declaration、prompt/public knowledge 边界。
- `/phase next` 阶段推进，阶段内自动释放公开材料/线索/可公开 role packet。
- 通用 action/form 最小子集：`MURDER`、`GUARD`、`INVESTIGATE`、`VOTE`、`DECLARE`。
- `/schema resolve` 本地结算与低风险 phase routing。
- `ending_rules.final_reveal_sequence` 最小运行：step、code word、content_ref、next_step_condition。
- replay runner 与无 API acceptance 测试。
- text/markdown 剧本半自动导入 v0.1：分块、结构识别、字段候选提取、source trace、置信度、缺失项报告、private/public 隔离告警、validator 校验、draft 输出、AI-assisted review pack 输出。

## 6. 当前不支持或仍是占位

- 不解析 PDF/DOCX，不做“陌生商业剧本自动导入”。
- text/markdown 导入只生成 schema draft，不会直接开局；必须人工确认版权、剧透边界、角色包和真相逻辑。
- 不让 LLM 从自然语言自由判定 action/form，行动必须通过本地命令提交。
- `scoring_rules` 未接入自动胜负/目标判定。
- `ending_rules.conditions` 未做复杂规则引擎，只支持 final reveal 顺序公开。
- `action_rules` 只实现通用最小子集，不是完整 Shadow 类自由行动系统。
- 真实私聊分发未实现；`/packet` 是主持人本地查看工具。
- 音频、TTS、BGM/SFX 是展示增强，不是 schema 能力的核心验收条件。

## 7. 开发者提示

- 新 runtime 能力优先写进 replay，再补 acceptance。
- 任何进入 `public_knowledge` 或 prompt 的内容，都必须先考虑可见性和 forbidden spoilers。
- 旧 Monsters 流程是兜底，改 schema runtime 时必须保持 `acceptance_monsters_halloween.py` 通过。
