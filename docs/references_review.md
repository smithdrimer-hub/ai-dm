# Open-Source Reference Review for AI-DM

## Clone Status

`external_references/` was created for local reference checkouts and is ignored by git. The first shallow clone attempt failed because the current environment repeatedly reset or timed out GitHub HTTPS connections. The failures were recorded in `external_references/clone_status.json`.

| Project | Status | Reason |
| --- | --- | --- |
| boardgame.io | failed | `Recv failure: Connection was reset` |
| ink | failed | `RPC failed; curl 28 Recv failure: Connection was reset` |
| Yarn Spinner | failed | `Failed to connect to github.com port 443` |
| foundryvtt/dnd5e | failed | `Failed to connect to github.com port 443` |
| Fluid HTN | failed | `Failed to connect to github.com port 443` |

The failure was fixable. A second pass used:

- `--depth 1`
- `--filter=blob:none`
- `--single-branch`
- `--sparse`
- HTTP/1.1
- Narrow sparse checkout paths for large repositories

All five repositories were cloned successfully on the retry. The successful retry results were recorded in `external_references/clone_status_retry.json`.

| Project | Retry Status | Local Source Reviewed |
| --- | --- | --- |
| boardgame.io | cloned | `docs/documentation/*`, `src/core/*`, `src/master/*` |
| ink | cloned | `Documentation/*`, `compiler/*`, `ink-engine-runtime/*` |
| Yarn Spinner | cloned | `Documentation/*`, `Tests/TestCases/*`, diagnostics definitions |
| foundryvtt/dnd5e | cloned | `system.json`, `module/data/*` |
| Fluid HTN | cloned | `README.md`, `Fluid-HTN/*`, unit tests |

This review now uses those local checkouts plus the current local project files:

- Current runtime: `detective_game_engine.py`
- Current single-player schema: `game_schema.py`, `schemas/game_schema_v0_1.schema.json`
- Current script/import schema: `script_schema.py`, `schemas/script_schema_v0_2_1.schema.json`
- Current medium case: `scripts/schema_examples/medium_detective_case_v0_1.json`
- Current evaluator: `scripts/evaluate_detective_game_v0_1.py`

Reference URLs:

- boardgame.io documentation: https://boardgame.io/documentation/
- ink documentation: https://www.inklestudios.com/ink/
- Yarn Spinner documentation: https://docs.yarnspinner.dev/
- Foundry VTT dnd5e repository: https://github.com/foundryvtt/dnd5e
- Fluid HTN repository: https://github.com/ptrefall/fluid-hierarchical-task-network

## Source Code Review Addendum

### Clone Failure Fix

The clone failures were mainly transport-size and connection-stability problems, not repository problems. The practical fix is to keep reference clones partial and sparse:

- Prefer `git clone --depth 1 --filter=blob:none --single-branch --sparse`.
- Fetch only review paths with `git sparse-checkout set ...`.
- For repos with large histories or content packs, do not immediately checkout the full tree.

This approach should be reused for future reference reviews.

### boardgame.io Source Lessons

Source/doc files checked: `src/core/flow.ts`, `src/core/reducer.ts`, `src/core/logger.ts`, `docs/documentation/phases.md`, `docs/documentation/stages.md`, `docs/documentation/testing.md`.

Borrowable methods:

1. `G` and `ctx` separation. boardgame.io treats game data and framework context as separate state concerns. AI-DM should keep static `GameSchema` separate from dynamic `GameState`: current phase, turn index, unlocked scenes, clue states, NPC runtime, action log.
2. Reducer pipeline. Moves go through validation, state update, plugin flush, log creation, transient error handling, and event processing. AI-DM's `handle_command_result()` can stay simple, but every command should continue returning a stable `ActionResult` with code, state delta, and history entry.
3. Phase/turn/stage control. Phases own move/action availability; stages subdivide a turn. In AI-DM, `phase.allowed_actions` and future `interaction_stage` can prevent `/accuse` too early, allow `/confront` only when evidence is revealed, and model special "final accusation" mode.
4. Deltalog/replay. boardgame.io logs action, state id, turn, and phase. AI-DM should add a lightweight `state_id` or `snapshot_hash` later so evaluator reports can prove replay determinism without storing huge snapshots.
5. Testing strategy. boardgame.io explicitly separates move unit tests from scenario tests. AI-DM already has replay and auto-eval; the next useful step is small command-level tests for lifecycle, scene conditions, and NPC action ticks.

Avoid for now:

- Multiplayer turn order, network synchronization, plugin APIs, undo/redo stacks, and client/server views are too heavy for the current single-player detective runtime.

### ink Source Lessons

Source/doc files checked: `Documentation/WritingWithInk.md`, `ink-engine-runtime/Story.cs`, `ink-engine-runtime/StoryState.cs`, `ink-engine-runtime/StatePatch.cs`, `compiler/ParsedHierarchy/Tag.cs`, `compiler/ParsedHierarchy/Divert.cs`, `compiler/ParsedHierarchy/Choice.cs`.

Borrowable methods:

1. Narrative nodes plus controlled diverts. AI-DM should not execute ink, but `scene_graph` should borrow the idea of named narrative nodes, explicit entry/exit conditions, and controlled branch events.
2. State patching. `StatePatch` tracks changed variables, visit counts, and turn indices. AI-DM can use this idea in evaluator reports: list only changed clue states, unlocked truths, NPC runtime changes, and fired rules per turn.
3. Tags as metadata. Tags are a clean way to annotate prose without exposing it as player text. AI-DM's importer can generate internal tags like `red_herring`, `exonerating`, `motive`, `method`, `timeline`, `npc_hint`, `recap_only`.
4. Visit counts. Ink uses visit count/turn index concepts to control repeatable content. AI-DM can use similar counters for clue reveal once-only behavior, NPC line cooldowns, and action profile `max_times`.

Avoid for now:

- A full interactive-fiction compiler, free-form knot/stitch authoring, and general text flow execution.

### Yarn Spinner Source Lessons

Source/doc files checked: `Documentation/Yarn-Spec.md`, `Tests/TestCases/Commands.yarn`, `Tests/TestCases/Commands.testplan`, parse-failure fixtures, diagnostics definitions such as `YS0060-UnknownCommand.md`.

Borrowable methods:

1. Dialogue text and commands are separate. Yarn commands are bridge points that the host game handles. AI-DM should keep NPC speech expressive, but every state-changing command must remain engine-owned: `/search`, `/confront`, `/accuse`, NPC action ticks.
2. Scripted dialogue tests. Yarn's `.testplan` files are close to our replay JSONs. For future LLM actor work, add sampled actor-eval transcripts with expected risk flags rather than brittle full text equality.
3. Static diagnostics. Yarn's parser fixtures catch duplicate node names, missing node bodies, unknown commands, and invalid option conditions. AI-DM validators should keep growing this style: dangling refs, unknown condition keys, impossible exits, unknown action types.
4. Header tags and hashtags. This is useful for the md/txt importer: a source text can include or the parser can infer metadata tags without asking the author to fill large forms.

Avoid for now:

- A Yarn compiler, node group saliency engine, and full branching dialogue language. Our single-player runtime only needs structured topics, conditions, and command-triggered reaction guidance.

### foundryvtt/dnd5e Source Lessons

Source files checked: `system.json`, `module/data/abstract/system-data-model.mjs`, `module/data/abstract/actor-data-model.mjs`, `module/data/abstract/item-data-model.mjs`, `module/data/item/templates/identifiable.mjs`, `module/data/fields/identifier-field.mjs`.

Borrowable methods:

1. Document type registry. `system.json` declares Actor, Item, JournalEntryPage, and related document types. AI-DM should make the same conceptual split explicit: `Character`, `Clue`, `Location`, `Scene`, `TruthNode`, `EndingRule`, `GameState`.
2. Template mix-ins. Foundry composes common schemas by templates. AI-DM can keep this lightweight by defining shared validation helpers for `id`, `condition`, `lifecycle`, `reference`, and `visible_to_player`.
3. Identifiable items. Foundry separates identified and unidentified item descriptions. This maps very well to clue lifecycle: hidden/discoverable/discovered/revealed, with safe public summaries before full reveal.
4. Identifier validation. A dedicated identifier field is better than letting arbitrary strings become ids. AI-DM validators should reject ids with spaces, accidental Chinese punctuation, duplicate aliases, or inconsistent case in v0.3+ fixtures.
5. Migration discipline. Foundry keeps versioned data models and migrations. AI-DM should keep v0.1/v0.3 side by side until there are enough cases to justify a migration command.

Avoid for now:

- Full document framework, compendium packs, rich sheet UI, migration pipeline, and embedded item collections.

### Fluid HTN Source Lessons

Source files checked: `README.md`, `Fluid-HTN/DomainBuilder.cs`, `Fluid-HTN/Planners/Planner.cs`, `Fluid-HTN/Tasks/CompoundTasks/Selector.cs`, `Fluid-HTN/Tasks/CompoundTasks/Sequence.cs`, `Fluid-HTN/Tasks/PrimitiveTasks/PrimitiveTask.cs`, `Fluid-HTN/Debug/DecompositionLogEntry.cs`.

Borrowable methods:

1. Context as blackboard. Fluid HTN plans against a context/world state. AI-DM's NPC autonomy should read only `GameState`: phase, discovered/revealed clues, broken lies, searched scenes, NPC runtime, and last player action.
2. Selector before sequence. We do not need full HTN, but current priority-based `action_profile.rules` is a tiny selector. It should explain why the winning rule fired and why other rules did not.
3. Conditions and executing conditions. NPC actions should validate conditions before selection and re-check reachability/phase before applying effects, especially after movement or game-over transitions.
4. Effects. Fluid HTN distinguishes planning effects and execution effects. AI-DM can borrow this by separating `selected_action_policy` for LLM performance from actual engine mutations to NPC location, stance, stress, and suspicion target.
5. Decomposition logging. The debug log is the biggest immediate win. `npc_action_history` should keep `matched_conditions`, `failed_conditions`, `reason`, and source rule id so dead rules are explainable.

Avoid for now:

- Total-order planner, domain splicing, plan continuation, smart-object slots, and NPC-NPC autonomous conversation.

## Author Guidance Strategy

The project should not rely on a broad author guide as the main path. The intended product loop is "input script text, system extracts structure, system validates and repairs where possible." Therefore:

- Do not ask the author to manually learn `action_profile`, `entry_condition`, lifecycle fields, or truth graph syntax in the normal path.
- Auto-generate those fields from the source script and mark confidence/risk in the review report.
- Only ask the author targeted questions when NPC characterization is too thin for believable roleplay.
- The author-facing questions should be generated as `review.author_questions`, not as a static guide.

Suggested NPC completeness checks:

- Missing or generic `public_profile`.
- Missing private pressure point, motive, fear, or relationship to victim.
- Missing speech style or conversational boundary.
- Missing what the NPC knows, what they hide, and what they must never reveal.
- Missing initial stance, stress baseline, or goal directive for action_profile generation.

Example targeted questions:

- "What is this NPC most afraid the detective will discover?"
- "How does this NPC speak when cornered: defensive, sarcastic, evasive, cooperative, or emotional?"
- "Which person does this NPC instinctively blame, and why?"
- "What fact can this NPC hint at without directly solving the case?"

## boardgame.io

### Useful Design Points

1. Explicit `phases`, `turns`, `stages`, and `moves`.
2. Moves are deterministic functions that update game state.
3. Phase and turn transitions are structured, not inferred from prose.
4. Logs/replay are first-class enough to reconstruct game progress.
5. Plugin-style state extension is separated from core game flow.

### Migration To AI-DM

- `phases` maps directly to `GameSchema.phases`.
- `moves` map to `/search`, `/show`, `/ask`, `/confront`, `/accuse`, `/status`.
- `turn log` maps to `ActionResult` and `action_history` in `DetectiveGameEngine`.
- `stages` map to finer detective sub-states: normal investigation, evidence confrontation, final accusation, recap.
- Replay maps to `scripts/playthroughs/*` and `scripts/evaluate_detective_game_v0_1.py`.

### Current Gaps

- v0.1 phases have `allowed_actions` but weak `entry_condition` and `exit_condition`.
- Runtime state exists, but static schema does not define the expected `GameState` snapshot.
- Replay exists, but schema cannot yet declare mandatory events that must happen before a phase is considered complete.

### Not For Now

- Do not adopt boardgame.io itself or a boardgame-style multiplayer turn framework.
- Do not introduce plugins or networking abstractions.

## ink

### Useful Design Points

1. Narrative is organized as nodes/knots/stitches rather than one long text.
2. Branches use explicit conditions and variables.
3. Tags can annotate narrative chunks without changing the visible prose.
4. Flow can jump, divert, or return in controlled ways.
5. State variables make replayable narrative possible.

### Migration To AI-DM

- Knots/stitches map to `scene_graph` and phase/scene event nodes.
- Conditions map to `entry_condition`, `exit_condition`, `discoverable_when`, and `unlock_condition`.
- Tags map to `scene_tags`, clue tags, red herring tags, exonerating tags, and pacing hints.
- Variables map to `GameState`: discovered clues, revealed clues, broken lies, unlocked truths, NPC runtime state.

### Current Gaps

- Current `scenes` are mostly containers for evidence, not graph nodes.
- Clue release is still mostly scene search plus phase unlocks.
- There is no schema-level way to express branch events or optional narrative beats.

### Not For Now

- Do not embed or execute ink scripts.
- Do not build a general interactive-fiction runtime.

## Yarn Spinner

### Useful Design Points

1. Dialogue nodes are independent units with names and runtime state.
2. Choices and commands can trigger external game logic.
3. Variables gate lines and options.
4. Dialogue runner emits events that the host game handles.
5. Commands are structured bridge points between narrative and program.

### Migration To AI-DM

- NPC dialogue packages should be node-like: topic, condition, allowed facts, hidden facts, and reaction guidance.
- `/ask` stays dialogue; `/confront` stays a command-like judge action.
- `selected_action_policy` in actor context is similar to a dialogue command: the engine chooses it, the actor performs it.
- Future `dialogue_events` can represent "NPC says hint", "NPC redirects suspicion", "NPC refuses", without letting the LLM judge truth.

### Current Gaps

- NPC lines are generated from role context, not from structured dialogue nodes.
- There is no stable schema for conditional lines or command-triggered dialogue events.
- Actor context isolation exists, but authored dialogue intent is still thin.

### Not For Now

- Do not import Yarn Spinner or add a full dialogue compiler.
- Do not add complex branching conversation graphs before the case runtime is stricter.

## foundryvtt/dnd5e

### Useful Design Points

1. Data object separation: Actor, Item, Journal, Scene.
2. Data models and migrations are versioned.
3. Validation is close to the model.
4. Content data is separated from runtime game state.
5. Items can carry typed behavior and references.

### Migration To AI-DM

- `Actor` maps to `npc_characters`.
- `Item` maps to `evidence` / `clues`.
- `Journal` maps to recap, truth timeline, and authored DM notes.
- `Scene` maps to searchable locations and scene graph nodes.
- Migration discipline maps to keeping v0.1 and v0.3 loaders side by side.

### Current Gaps

- `GameSchema v0.1` mixes "evidence as content" with runtime assumptions such as `initially_discovered`.
- There is no formal `GameState` model, only the engine snapshot.
- Schema migration is ad hoc.

### Not For Now

- Do not build a Foundry-style document system.
- Do not add full migration infrastructure until there are several schema versions in use.

## Fluid HTN

### Useful Design Points

1. NPC action can be modeled as goal, task, condition, action.
2. Conditions keep behavior bounded and inspectable.
3. Planner output should be concrete actions, not free-form intent.
4. Effects update world state after the chosen action.
5. Debuggability matters: why a task matched is part of the design.

### Migration To AI-DM

- Current `action_profile.goals` and `rules` are the right minimal shape.
- `conditions` map to structured `GameState`.
- `action.type` maps to bounded actions: move, change stance, raise stress, redirect suspicion, withdraw.
- `npc_action_history.matched_conditions`, `source_action`, and `reason` are the necessary debug trail.

### Current Gaps

- `action_profile` was still an additional property in v0.1, not formal schema.
- Validator did not consistently catch dead rules or unsupported condition keys until evaluator/lint support was added.
- There is no authored distinction between long-term goal and current tactical policy beyond simple priority.

### Not For Now

- Do not implement full HTN planning, GOAP, or NPC-NPC free simulation.
- Keep NPC autonomy turn-based and engine-selected.

## Current Project Gaps

### GameSchema

- v0.1 has useful core objects but weak lifecycle semantics for clues.
- v0.1 phase graph is shallow: `allowed_actions` exists, but entry/exit conditions and events are not formal.
- Truth nodes link to evidence but do not distinguish required clues, supporting clues, timeline refs, and unlock condition.
- `action_profile` exists in medium case but is not a formal schema concept.

### ScriptSchema

- `ScriptSchema v0.2.1` is better for authored murder mystery materials, role packets, reveal rules, forms, and DM workflow.
- It should remain the text/import and multiplayer-host-facing layer.
- It should not become the single-player detective runtime state model.

### GameState

- `DetectiveGameEngine.get_progress_snapshot()` is the real runtime state today.
- v0.3 should document and test it explicitly: phase, unlocked/searched scenes, discovered/revealed clues, broken lies, unlocked truths, NPC runtime, action history, accusation history, last result.

### Validator

The most important missing checks were:

- Dangling refs in new lifecycle and condition fields.
- Critical clues needed by ending rules but unreachable.
- Phase entries with no exit condition.
- Truth nodes without evidence support.
- Ending rules without enough structured refs.
- NPC spoiler boundary risks around culprit truth.
- NPC roleplay readiness risks: missing personality, thin public/private profile, missing speech style, missing pressure point, missing knowledge/forbidden boundaries.

## GameSchema v0.3 Minimal Upgrade

Implemented as a side-by-side schema, not a replacement:

- `schemas/game_schema_v0_3.schema.json`
- `game_schema_v0_3.py`
- `scripts/schema_examples/medium_detective_case_v0_3.json`
- `scripts/playthroughs/medium_detective_game_v0_3_replay.json`

### v0.3 Fields

- `evidence.source_scene_id`
- `evidence.lifecycle.initial_state`
- `evidence.lifecycle.discoverable_when`
- `evidence.lifecycle.reveal_when`
- `evidence.lifecycle.lock_reason`
- `scenes.entry_condition`
- `scenes.exit_condition`
- `scenes.search_result_events`
- `scenes.scene_tags`
- `phases.entry_condition`
- `phases.exit_condition`
- `phases.mandatory_events`
- `phases.optional_events`
- `truth_nodes.required_clue_ids`
- `truth_nodes.supporting_character_ids`
- `truth_nodes.timeline_refs`
- `truth_nodes.unlock_condition`
- `ending_rules`
- `game_state_spec`

### Runtime Mapping

- `DetectiveGameEngine` now loads v0.1 and v0.3.
- v0.3 clue lifecycle drives discovery without changing slash commands.
- Snapshot includes `clue_state_by_id`.
- Scene entry conditions can unlock scenes when state changes.
- Truth unlocks respect `required_clue_ids` and `unlock_condition`.

## Most Worth Doing Next

1. Keep `medium_detective_case_v0_3.json` as the schema design fixture and avoid drifting new ideas into untested examples.
2. The md/txt importer now writes a GameSchema v0.3 draft and friendly `review.author_questions`; next, improve automatic tags for `red_herring`, `motive`, `method`, `timeline`, and `npc_hint`.
3. Auto-eval now reports clue lifecycle coverage, snapshot deltas, snapshot hashes, and NPC rule diagnostics; next, use those reports to tune generated cases rather than asking authors to inspect schema syntax.
4. Expand validator/evaluator reporting for generated `entry_condition`, clue lifecycle, truth graph references, and NPC action rules whenever importer-generated cases become more varied.
5. Keep `dm_engine.py` untouched until the single-player runtime and importer loop are stable and well-tested.

## v0.4 Deferred

- Broad author-facing schema guide. A short internal reference is fine, but the product should not depend on authors hand-writing runtime fields.
- Full schema migration tool.
- Visual scene graph editor.
- Natural-language command parser.
- Full HTN planner or behavior tree.
- Multiplayer room state.
- General ink/Yarn runtime.
- Foundry-style full data model and content pack system.
