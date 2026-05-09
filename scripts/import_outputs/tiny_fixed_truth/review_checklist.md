# AI Review Checklist

Use this checklist when asking GPT/Claude or a human reviewer to inspect the imported draft.

## Scope Snapshot

```json
{
  "characters": 3,
  "role_packets": 3,
  "clues": 2,
  "truth_nodes": 2,
  "final_steps": 2,
  "local_risks": 5
}
```

## Public / Private Isolation

- [ ] Public intro, setting, rules, opening script contain no role secrets.
- [ ] Public cast profiles do not include private goals, alibis, hidden identity, culprit, method, or final truth.
- [ ] Clue content is safe at its reveal phase and not safe earlier.
- [ ] Role packet content is absent from public materials unless reveal_instruction explicitly makes it public.

## Role Packets

- [ ] Every packet belongs to the correct character.
- [ ] phase_id matches when the packet should unlock.
- [ ] visibility, after_reveal_visibility, recipients, and reveal_instruction match the source text.
- [ ] keep_secret / reveal_only_when_challenged packets are not placed in public knowledge.

## Clue Timing

- [ ] Each clue has the correct reveal_phase.
- [ ] Each clue has a matching reveal_rule.
- [ ] reveal_rule announcement does not reveal extra truth.
- [ ] clue order supports the intended player reasoning path.

## Truth Logic

- [ ] Every truth_node is accurate and source-grounded.
- [ ] evidence_links actually support the linked truth node.
- [ ] case_questions ask the right final questions.
- [ ] imported placeholder links are replaced or explicitly approved.

## Ending Consistency

- [ ] final_reveal_sequence step order is correct.
- [ ] code_word steps are present only when the source script requires them.
- [ ] content_ref points to the intended truth/clue/asset.
- [ ] final reveal does not skip any required truth.

## Spoiler Safety

- [ ] forbidden_spoilers cover culprit, method, hidden identity, motive, code words, and aliases.
- [ ] allowed_after_phase / allowed_after_reveal_rule are not too early.
- [ ] hint_rules do not allow truth nodes before they should be known.
- [ ] review any locally detected high-risk item below.

## Local High-Risk Items

| level | area | item | why | suggested_check |
| --- | --- | --- | --- | --- |
| MEDIUM | import_gap | missing/manual field | Character relationships are not inferred. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | No content_ref role packet files were inferred. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | action_rules remain disabled in imported drafts. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | import_gap | missing/manual field | License and redistribution rights are unknown. | Compare against source text and decide whether the draft needs manual edits. |
| MEDIUM | truth_logic | evidence_links | Multiple truth nodes are linked to one clue only. | Check whether evidence links were over-collapsed by the importer. |
