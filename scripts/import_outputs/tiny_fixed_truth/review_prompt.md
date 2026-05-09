# AI-Assisted Semantic Review Prompt

You are reviewing a semi-automatically imported murder-mystery ScriptSchema draft. Do not expand the schema and do not rewrite the story. Your job is to identify semantic risks and produce a concise human-review report.

Use these local artifacts as the source of truth:
- script.json: generated schema draft with x_import_trace.
- import_report.md: extraction confidence, source trace, missing fields.
- schema_gap_report.md: human review gaps.
- validator_errors.json: structural validation status.

Review priorities:
1. public/private isolation: public_materials, public cast profiles, clues, prompt-facing content must not contain role secrets or final truth.
2. role packet ownership: each private packet must belong to the correct character, phase, and reveal instruction.
3. clue timing: every clue should reveal at the intended phase and should not appear too early.
4. truth logic: truth_nodes should be supported by evidence_links and not contradict public materials.
5. ending consistency: final_reveal_sequence should reveal truth in a coherent order, including any code-word chain.
6. spoiler risk: forbidden_spoilers should cover final truth and any aliases that would spoil before allowed phases.

Return format:
- Blocking issues
- High-risk ambiguities
- Suggested manual edits
- Questions for the human script owner
- Safe-to-demo verdict: yes/no and why

## Validator Status

```json
{
  "valid": true,
  "error_count": 0,
  "errors": []
}
```

## Local High-Risk Heuristics

| level | area | item | why | suggested_check |
| --- | --- | --- | --- | --- |
| MEDIUM | import_gap | missing/manual field | Character relationships are not inferred. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | No content_ref role packet files were inferred. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | action_rules remain disabled in imported drafts. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | License and redistribution rights are unknown. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | truth_logic | evidence_links | Multiple truth nodes are linked to one clue only. | Check whether evidence links were over-collapsed by the importer. |

## Draft Summary

- script_id: tiny_fixed_truth_imported

- title: Tiny Imported Manor

- game_mode: fixed_truth

- player_count: {'min': 3, 'max': 3, 'recommended': 3}



## Phase / Release Map

| order | phase_id | type | materials | clues |
| --- | --- | --- | --- | --- |
| 1 | intro | intro |  |  |
| 2 | discussion | free_discussion |  |  |
| 3 | clue_1_release | discovery |  | clue_1 |
| 4 | clue_2_release | discovery |  | clue_2 |
| 5 | accusation | accusation |  |  |
| 6 | recap | recap |  |  |



## Clues

| clue_id | title | visibility | reveal_phase | related_characters | content |
| --- | --- | --- | --- | --- | --- |
| clue_1 | Tarnished Cup | hidden | clue_1_release |  | The silver cup has a bitter almond smell. |
| clue_2 | Muddy Key | hidden | clue_2_release |  | The dining room key has greenhouse mud on it. |



## Role Packets

| packet_id | character | phase | visibility | after_reveal | instruction | content_or_ref |
| --- | --- | --- | --- | --- | --- | --- |
| packet_char_ada_intro | char_ada | intro | private | private | reveal_only_when_challenged | Ada moved the silver cup before dinner. |
| packet_char_bruno_intro | char_bruno | intro | private | private | reveal_only_when_challenged | Bruno saw Ada near the study. |
| packet_char_cora_intro | char_cora | intro | private | private | reveal_only_when_challenged | Cora heard a code word in the hallway. |



## Truth Nodes

| node_id | type | related_clues | related_characters | content |
| --- | --- | --- | --- | --- |
| truth_1 | fact | clue_1 | char_ada | The cup was poisoned before dinner. |
| truth_2 | fact | clue_1 | char_ada | Ada moved the poisoned cup from the study to the dining room. |



## Final Reveal Sequence

| step | trigger | code_word | content_ref | next_step_condition |
| --- | --- | --- | --- | --- |
| 1 | dm_reveal |  | truth_1 |  |
| 2 | code_word | LANTERN | truth_2 |  |



## Forbidden Spoilers

| spoiler_id | type | allowed_after_phase | allowed_after_rule | content |
| --- | --- | --- | --- | --- |
| spoiler_truth_1 | truth_node | accusation |  | The cup was poisoned before dinner. |
| spoiler_truth_2 | truth_node | accusation |  | Ada moved the poisoned cup from the study to the dining room. |

## Source Trace

| field | heading | lines | evidence |
| --- | --- | --- | --- |
| title | Tiny Imported Manor | 1-5 | Tiny Imported Manor |
| author |  | 3-3 | Author: Demo Author |
| setting |  | 4-4 | Setting: A storm keeps four guests inside a quiet manor. |
| public_intro | Public Intro | 6-9 | The host is found unconscious after dinner. Everyone stayed inside the manor, and the DM should keep the first discussion focused on public timelines. |
| rules_text | Rules | 10-13 | Discuss openly, reveal clues when the DM advances phases, then make an accusation before the final reveal. |
| cast.Ada | Cast | 14-19 | Ada: A calm botanist who says she checked the greenhouse. \| Secret: Ada moved the silver cup before dinner. \| Goal: Avoid being blamed for the cup. |
| cast.Bruno | Cast | 14-19 | Bruno: A nervous butler who controls the dining room keys. \| Secret: Bruno saw Ada near the study. \| Goal: Protect the household reputation. |
| cast.Cora | Cast | 14-19 | Cora: A visiting journalist who wants the truth. \| Secret: Cora heard a code word in the hallway. \| Goal: Publish the correct story. |
| clues.Tarnished Cup | Clues | 20-24 | Tarnished Cup: The silver cup has a bitter almond smell. |
| clues.Muddy Key | Clues | 20-24 | Muddy Key: The dining room key has greenhouse mud on it. |
| truth_model.Truth 1 | Truth | 25-29 | The cup was poisoned before dinner. |
| truth_model.Truth 2 | Truth | 25-29 | [code: LANTERN] Ada moved the poisoned cup from the study to the dining room. |

## Import Report Excerpt

# Import Report

- Source: `D:\3plus\111inovation\script\murder-mystery-dm\scripts\import_samples\tiny_fixed_truth.md`
- Output directory: `D:\3plus\111inovation\script\murder-mystery-dm\scripts\import_outputs\tiny_fixed_truth`
- Draft title: Tiny Imported Manor
- Language: en
- Characters detected: 3
- Clues detected: 2
- Truth items detected: 2
- Validator status: PASS

## Confidence

| area | confidence |
|---|---:|
| actions | 0.00 |
| author | 0.85 |
| cast | 1.00 |
| clues | 1.00 |
| overall | 0.92 |
| public_materials | 0.75 |
| title | 0.90 |
| truth_model | 1.00 |

## Missing Fields / Manual Review

- Character relationships are not inferred.
- No content_ref role packet files were inferred.
- action_rules remain disabled in imported drafts.
- License and redistribution rights are unknown.

## Private/Public Isolation Warnings

- None

## Source Trace

| field | heading | lines | evidence |
|---|---|---|---|
| script_info.title | Tiny Imported Manor | 1-5 | Tiny Imported Manor |
| script_info.author |  | 3-3 | Author: Demo Author |
| public_materials.setting |  | 4-4 | Setting: A storm keeps four guests inside a quiet manor. |
| public_materials.public_intro | Public Intro | 6-9 | The host is found unconscious after dinner. Everyone stayed inside the manor, and the DM should keep the first discussion focused on public timelines. |
| public_materials.rules_text | Rules | 10-13 | Discuss openly, reveal clues when the DM advances phases, then make an accusation before the final reveal. |
| cast.Ada | Cast | 14-19 | Ada: A calm botanist who says she checked the greenhouse. \| Secret: Ada moved the silver cup before dinner. \| Goal: Avoid being blamed for the cup. |
| cast.Bruno | Cast | 14-19 | Bruno: A nervous butler who controls the dining room keys. \| Secret: Bruno saw Ada near the study. \| Goal: Protect the household reputation. |
| cast.Cora | Cast | 14-19 | Cora: A visiting journalist who wants the truth. \| Secret: Cora heard a code word in the hallway. \| Goal: Publish the correct story. |
| clues.Tarnished Cup | Clues | 20-24 | Tarnished Cup: The silver cup has a bitter almond smell. |
| clues.Muddy Key | Clues | 20-24 | Muddy Key: The dining room key has greenhouse mud on it. |
| truth_model.Truth 1 | Truth | 25-29 | The cup was poisoned before dinner. |
| truth_model.Truth 2 | Truth | 25-29 | [code: LANTERN] Ada moved the poisoned cup from the study to the dining room. |

## Detected Sections

```json
{
  "other": [
    "Tiny Imported Manor"
  ],
  "intro": [
    "Public Intro"
  ],
  "rules": [
    "Rules"
  ],
  "cast": [
    "Cast"
  ],
  "clues": [
    "Clues"
  ],
  "truth": [
    "Truth"
  ]
}
```

## Chunks

| # | heading | lines | chars |
|---:|---|---|---:|
| 1 | Tiny Imported Manor | 1-5 | 76 |
| 2 | Public Intro | 6-9 | 150 |
| 3 | Rules | 10-13 | 106 |
| 4 | Cast | 14-19 | 427 |
| 5 | Clues | 20-24 | 117 |
| 6 | Truth | 25-29 | 117 |

## Validator Errors

- None

## Manual Confirmation

This draft was written only because --confirm-manual-review was supplied. Review license, spoilers, cast packets, truth, and clue timing before live use.

