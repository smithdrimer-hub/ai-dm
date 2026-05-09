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
