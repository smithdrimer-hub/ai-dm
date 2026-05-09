# ScriptSchema v0.2.1 Skeleton

> This is a JSONC skeleton. Remove comments before using it as strict JSON.

```jsonc
{
  "schema_version": "string // required, fixed value for this version: 0.2.1",

  "script_info": {
    "id": "string // stable script id",
    "title": "string",
    "author": "string | null",
    "game_mode": "fixed_truth | emergent_resolution | hybrid",
    "player_count": {
      "min": "number",
      "max": "number",
      "recommended": "number"
    },
    "language": "string // e.g. zh-CN, en-US"
  },

  "license_info": {
    "source": "string // where the script/material came from",
    "license_type": "string // e.g. original, permission_granted, unknown, CC-BY",
    "commercial_allowed": "boolean | null",
    "redistribution_allowed": "boolean | null",
    "attribution_required": "boolean",
    "notes": "string"
  },

  "public_materials": {
    "setting": "string // public setting only",
    "public_intro": "string // public premise/introduction only",
    "rules_text": "string // player-facing rules",
    "cast_public_list": [
      {
        "character_id": "string",
        "display_name": "string",
        "public_profile": "string"
      }
    ],
    "opening_script": "string // DM opening script, no private role facts",
    "player_guidance": "string // how players should speak/play",
    "content_notes": "string // public content notes/warnings"
  },

  "player_config": {
    "mode": "all_role_players | role_players_plus_observers | role_players_plus_detectives",
    "role_player_slots": [
      {
        "slot_id": "string",
        "character_id": "string",
        "required": "boolean"
      }
    ],
    "observer_slots": [
      {
        "slot_id": "string",
        "display_name": "string",
        "player_type": "observer | detective",
        "permissions": {
          "can_speak": "boolean",
          "can_vote": "boolean",
          "can_accuse": "boolean",
          "can_receive_private_packets": "boolean"
        }
      }
    ]
  },

  "cast": [
    {
      "character_id": "string",
      "display_name": "string",
      "public_profile": "string",
      "goals": [
        {
          "goal_id": "string",
          "description": "string",
          "visibility": "public | private"
        }
      ],
      "relationships": [
        {
          "target_id": "string",
          "relation_type": "ally | rival | family | romantic | hostile | secret_link | other",
          "public_description": "string",
          "private_description": "string | null"
        }
      ],
      "secrets": [
        {
          "secret_id": "string",
          "description": "string",
          "reveal_policy": "keep_secret | reveal_only_when_challenged | may_share | must_reveal_later"
        }
      ]
    }
  ],

  "phases": [
    {
      "phase_id": "string",
      "title": "string",
      "phase_type": "intro | free_discussion | search | discovery | examination | accusation | resolution | confession_chain | recap",
      "order": "number",
      "materials_to_release": ["string // public material ids if split externally"],
      "clues_to_reveal": ["string // clue ids"],
      "dm_instructions": {
        "opening_text": "string",
        "pace_notes": "string",
        "transition_condition": "manual | timed | all_players_ready | form_submitted | action_resolved | custom"
      }
    }
  ],

  "role_packets": [
    {
      "packet_id": "string",
      "character_id": "string",
      "phase_id": "string",
      "content": "string | null // inline packet text",
      "content_ref": "string | null // asset_id or external content id",
      "visibility": "private | public | dm_only | group_limited",
      "recipients": ["string // required when visibility or after_reveal_visibility is group_limited"],
      "after_reveal_visibility": "private | public | dm_only | group_limited",
      "reveal_instruction": "keep_secret | must_read_aloud | reveal_only_when_challenged | reveal_at_phase_start | may_share"
    }
  ],

  "clues": [
    {
      "clue_id": "string",
      "title": "string",
      "clue_type": "text | letter | newspaper | map | object | testimony | rule_extract",
      "content": "string",
      "asset_refs": ["string // asset_id list"],
      "initial_visibility": "hidden | public | role_private | dm_only",
      "reveal_phase": "string | null // phase_id",
      "related_characters": ["string // character_id"]
    }
  ],

  "assets": [
    {
      "asset_id": "string",
      "asset_type": "image | audio | document | handout | map | other",
      "path": "string",
      "description": "string",
      "linked_clue_id": "string | null",
      "visibility": "hidden | public | role_private | dm_only | group_limited",
      "source_page": "string | number | null",
      "requires_manual_review": "boolean"
    }
  ],

  "reveal_rules": [
    {
      "rule_id": "string",
      "target_type": "clue | role_packet | public_material | asset | truth_node | form",
      "target_id": "string",
      "trigger_type": "phase_start | phase_end | timed | dm_manual | player_action | form_submit | challenge | code_word",
      "phase_id": "string | null",
      "recipients": ["string // character_id, slot_id, group id, or ALL"],
      "after_reveal_visibility": "private | public | dm_only | group_limited",
      "announcement_template": "string"
    }
  ],

  "truth_model": {
    "truth_type": "fixed | emergent | hybrid",
    "case_questions": [
      {
        "question_id": "string",
        "prompt": "string",
        "expected_answer_node_ids": ["string // truth_node ids"]
      }
    ],
    "truth_nodes": [
      {
        "node_id": "string",
        "node_type": "fact | condition | consequence | contradiction | motive | method | alibi",
        "content": "string",
        "conditions": [
          {
            "if": "string // condition expression",
            "then": "string // resulting truth/consequence"
          }
        ],
        "related_characters": ["string"],
        "related_clues": ["string"]
      }
    ],
    "evidence_links": [
      {
        "link_id": "string",
        "truth_node_id": "string",
        "clue_id": "string",
        "strength": "supports | contradicts | proves | suggests",
        "explanation": "string"
      }
    ]
  },

  "forbidden_spoilers": [
    {
      "spoiler_id": "string",
      "spoiler_type": "truth_node | clue | role_secret | ending | action_result | custom",
      "content": "string",
      "aliases": ["string"],
      "forbidden_until_phase": "string | null",
      "allowed_after_phase": "string | null",
      "allowed_after_reveal_rule": "string | null // reveal_rules.rule_id",
      "allowed_after_condition": "string | null"
    }
  ],

  "action_rules": {
    "enabled": "boolean",
    "action_types": [
      {
        "action_type": "MURDER | GUARD | INVESTIGATE | DECLARE | VOTE | ACCUSE | CUSTOM",
        "actor_scope": "role_player | detective | any_player | specific_character",
        "target_scope": "character | clue | location | form | none",
        "input_form_id": "string | null",
        "changes_character_state": "boolean",
        "changes_voting_eligibility": "boolean",
        "changes_candidate_eligibility": "boolean"
      }
    ],
    "resolution_order": [
      "string // ordered action_type list; actions can be placed before VOTE"
    ],
    "blocking_rules": [
      {
        "rule_id": "string",
        "blocked_action_type": "string",
        "blocked_when": "string // e.g. same target has GUARD count >= 2 this round",
        "blocked_by_action_type": "string | null",
        "minimum_block_count": "number | null",
        "same_target_required": "boolean",
        "result": "action_fails | target_protected | no_effect | custom"
      }
    ],
    "outcomes": [
      {
        "outcome_id": "string",
        "trigger_condition": "string",
        "result_type": "character_state_change | voting_eligibility_change | candidate_eligibility_change | clue_reveal | ending_flag | score_change | declaration_validated",
        "result_payload": "object"
      }
    ]
  },

  "forms": [
    {
      "form_id": "string",
      "title": "string",
      "form_type": "declaration_card | accusation_sheet | vote_card | action_card | resolution_card | custom",
      "per_player_or_global": "per_player | global",
      "read_aloud_after_submit": "boolean",
      "used_for_resolution": "boolean",
      "fields": [
        {
          "field_id": "string // e.g. vote, decisive_action, declaration, whodunit, how, why",
          "label": "string",
          "field_type": "character_ref | action_type | free_text | clue_ref | choice | boolean",
          "required": "boolean"
        }
      ],
      "submit_phase": "string"
    }
  ],

  "ending_rules": {
    "ending_type": "fixed_reveal | action_based | hybrid",
    "conditions": [
      {
        "ending_id": "string",
        "priority": "number",
        "when": "string // condition expression",
        "ending_title": "string",
        "ending_text_ref": "string"
      }
    ],
    "final_reveal_sequence": [
      {
        "step": "number",
        "trigger": "code_word | confession_statement | dm_reveal | player_accusation | action_result",
        "speaker_character_id": "string | null",
        "required_code_word": "string | null",
        "content_ref": "string // packet_id, clue_id, truth_node_id, asset_id, or text id",
        "next_step_condition": "string | null"
      }
    ]
  },

  "scoring_rules": {
    "enabled": "boolean",
    "goal_checks": [
      {
        "character_id": "string",
        "goal_id": "string",
        "success_condition": "string",
        "score_delta": "number | null"
      }
    ]
  },

  "hint_rules": [
    {
      "hint_id": "string",
      "level": "L1 | L2 | L3",
      "phase_id": "string | null",
      "allowed_when": "string // condition expression",
      "allowed_clue_ids": ["string"],
      "allowed_truth_nodes": ["string"],
      "forbidden_truth_nodes": ["string"],
      "template": "string",
      "cooldown_turns": "number",
      "spoiler_check_mode": "strict | phase_limited | off"
    }
  ]
}
```

## Notes

`final_reveal_sequence` now lives only under `ending_rules`, because it describes performance order and reveal ceremony rather than the truth graph itself. `truth_model` is kept for case structure: `case_questions`, `truth_nodes`, and `evidence_links`.

`reveal_rules` gives clues, packets, assets, public materials, and truth nodes one unified reveal entry point without requiring a full rules engine in v0.2.1. `role_packets` can store inline `content` or point to `content_ref`; `recipients` is required whenever either current or post-reveal visibility is `group_limited`.

`action_rules` remains a skeleton, but it can now represent Guard stacking, resolution order before voting, and action outcomes that change character state, voting eligibility, or candidate eligibility. `license_info`, `public_materials`, `assets`, and `hint_rules` are included so implementation can start without mixing private role information into public-facing materials.
