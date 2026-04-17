"""Monsters Halloween Night 的第一版结构化剧本数据。"""

SCRIPT_DATA = {
    "meta": {
        "script_id": "monsters_halloween_night_cn",
        "title": "Monsters Halloween Night",
        "language": "zh-CN",
        "player_count": 4,
        "estimated_duration_minutes": 60,
        "source_files": [
            "Announcement.docx",
            "Character sheet_mummy.docx",
            "Character sheet_Vampire.docx",
            "Character sheet_witch.docx",
            "Character sheet_wolf.docx",
            "What I noticed_1.docx",
            "What I noticed_2.docx",
            "Ending.docx",
        ],
        "source_quality_notes": [
            "公告文档提取质量较差，本版主要依据角色卡、线索卡、结局文件。",
            "部分中文文本存在 OCR 或转码瑕疵，已按上下文做最小清洗。",
            "少量时间线和因果链来自多份材料交叉推断，相关字段单独标注。",
        ],
    },
    "shared_rules": {
        "truth_rule": "犯人以外的人不能说谎。",
        "fallback_reply_rule": "如有不想透露的事，可以说“NO COMMENT”或“我不知道”。",
        "clue_release_rules": [
            {"clue_id": "clue_1", "trigger": "讨论开始后10分钟"},
            {"clue_id": "clue_2", "trigger": "讨论开始后20分钟"},
        ],
        "final_vote_rule": "所有玩家最后同时公开自己写下的答案。",
    },
    "final_answer_check": {
        "simultaneous_reveal_rule": "所有玩家先在线下同时公开自己写下的最终答案，再由操作者按顺序把四位角色的答案录入程序。",
        "input_format_hint": "每次录入一位角色时，统一使用“犯人答案/碎布答案/橱柜答案”的格式。",
        "reveal_order": ["狼", "女巫", "吸血鬼", "木乃伊"],
        "operator_tie_rule": "如果“谁是真正的犯人”这道题出现平票，请相关玩家先在线下自行决定最终结果，再把最终票选角色名输入程序。",
        "public_questions": [
            {
                "id": "culprit",
                "question": "谁是真正的犯人？",
                "expected_role": "wolf",
                "expected_answer": "狼",
            },
            {
                "id": "cloth",
                "question": "木乃伊身上的漂亮碎布究竟是什么？",
                "expected_answer": "孩童衣服的碎片。",
                "keyword_groups": [
                    ["孩童", "孩子", "小孩"],
                    ["衣服", "衣物", "衣料"],
                    ["碎片", "碎布", "布片", "碎"]
                ],
                "minimum_group_matches": 2,
            },
            {
                "id": "cabinet",
                "question": "孩童为什么会被放进上锁的补给橱柜？",
                "expected_answer": "女巫发现等候室里还有人类后，用钥匙把孩童藏进了上锁的补给橱柜。",
                "keyword_groups": [
                    ["女巫"],
                    ["发现", "察觉", "感知"],
                    ["人类", "孩童", "孩子", "小孩"],
                    ["钥匙", "上锁", "锁", "橱柜", "补给橱柜"],
                    ["藏进", "藏入", "放进", "锁进", "关进"]
                ],
                "minimum_group_matches": 3,
            },
        ],
    },
    "world": {
        "background": (
            "万圣节活动期间，四个真正的怪物在主题乐园“克苏鲁仙境”打工。"
            "闭园后，业主宣称有一名孩童失踪，并要求找出袭击客人的犯人。"
        ),
        "locations": {
            "waiting_room": {
                "name": "等候室",
                "description": "鬼怪们专用的休息室。",
                "known_facts": [
                    "画框后面藏着补给橱柜的钥匙。",
                ],
            },
            "supply_cabinet": {
                "name": "补给橱柜",
                "description": "存放鬼怪重要物品的橱柜，关上后会自动上锁。",
                "known_facts": [
                    "全员共用同一把钥匙。",
                    "里面放着野生动物的肉、返老还童的药、兔子的鲜血果汁和干燥剂等物品。",
                ],
            },
        },
    },
    "public_intro": {
        "story_hook": [
            "四位怪物在乐园的万圣节活动中担任工作人员。",
            "活动成功结束后，业主指控有人袭击了失踪的孩童。",
            "在找出犯人之前，所有人的报酬都会被冻结。",
        ],
        "public_roles": [
            {
                "role_id": "wolf",
                "name": "狼",
                "summary": "拥有强大力量的狼人，擅长用庞大的身体进行表演。",
                "attitude_to_humans": "看起来很好吃。",
            },
            {
                "role_id": "witch",
                "name": "女巫",
                "summary": "驼背的魔女，能把真正的魔法伪装成魔术表演。",
                "attitude_to_humans": "适合当魔法实验品。",
            },
            {
                "role_id": "vampire",
                "name": "吸血鬼",
                "summary": "面色苍白的真祖吸血鬼，举止天然就像吸血鬼。",
                "attitude_to_humans": "人类的血最美味。",
            },
            {
                "role_id": "mummy",
                "name": "木乃伊",
                "summary": "来自埃及的木乃伊，因原本是人类而更擅长服务游客。",
                "attitude_to_humans": "想找个同伴。",
            },
        ],
    },
    "roles": {
        "mummy": {
            "name": "木乃伊",
            "is_culprit": False,
            "private_summary": "发现喜欢的布就会拿来替换自己身上的绷带。",
            "known_other_facts": [
                "目击到女巫在还没到休息时间前进入等候室。",
                "22:00左右，发现吸血鬼的喉咙一直吞咽，眼里似乎布满血丝。",
            ],
            "self_facts": [
                "18:00左右，因为迷路孩童的哭泣而慌张，把孩童带进等候室。",
                "随后离开等候室去找业主。",
                "22:00左右回到等候室时，发现孩童已经不见了。",
                "之后在垃圾桶里发现漂亮碎布，并把它捡来当绷带。",
            ],
            "must_hide": [],
            "goals": [
                "投票给真正的犯人。",
                "说明那块漂亮碎布究竟是什么。",
            ],
        },
        "vampire": {
            "name": "吸血鬼",
            "is_culprit": False,
            "private_summary": "不熟悉现代社会，容易被一切事物惊吓到并大惊小怪。",
            "known_other_facts": [
                "目击到木乃伊在四处寻找业主。",
                "目击到女巫只对特定的小孩子做特别表演。",
            ],
            "self_facts": [
                "19:00左右，进入等候室，从补给橱柜里拿出鲜血果汁准备喝。",
                "与躲在房间角落、表情十分恐慌的孩童对上视线。",
                "被这突如其来的情况吓到，匆忙逃离等候室。",
            ],
            "must_hide": [],
            "goals": [
                "投票给真正的犯人。",
                "说明自己是第几个进入等候室的人。",
            ],
        },
        "witch": {
            "name": "女巫",
            "is_culprit": False,
            "private_summary": "只会从孩子中选出特别好看的对象，为其展示特别表演。",
            "known_other_facts": [
                "18:00左右，目击到木乃伊因为迷路孩童而非常混乱。",
                "目击到狼被孩童们误认为布偶服工作人员而被欺负。",
            ],
            "self_facts": [
                "20:00左右，因为没心情而去等候室偷懒。",
                "进入时发现地板上溅满了血。",
                "在地上找到补给橱柜的钥匙，并将其放回画框后面的藏匿处。",
                "同时感受到等候室里有人类存在。",
            ],
            "must_hide": [],
            "goals": [
                "投票给真正的犯人。",
                "说明自己是第几个进入等候室的人。",
            ],
        },
        "wolf": {
            "name": "狼",
            "is_culprit": True,
            "private_summary": "被孩童们误认为布偶服工作人员而遭欺负，是这起事件的直接犯人。",
            "known_other_facts": [
                "目击到吸血鬼从等候室里慌张逃走。",
                "22:00左右，注意到木乃伊绷带上沾着漂亮碎布。",
            ],
            "self_facts": [
                "在被孩童们猛烈欺负后逃入等候室。",
                "因等候室地板上的血滑倒。",
                "因为肚子饿了而寻找补给橱柜的钥匙，但没有找到。",
                "于是撬坏补给橱柜。",
                "打开后发现孩童被放在里面，并把孩童吃掉。",
                "把孩童衣服撕成小片，丢进垃圾桶。",
            ],
            "must_hide": [
                "自己是杀害孩童的犯人。",
                "自己撬坏了补给橱柜。",
                "自己撕碎并丢弃了孩童衣物。",
            ],
            "goals": [
                "让大家投票给真正的犯人，也就是自己。",
                "说明孩童为什么会被放进上锁的补给橱柜。",
            ],
        },
    },
    "clues": {
        "clue_1": {
            "name": "发现到的线索①",
            "release_phase": "discussion_10min",
            "content": "补给橱柜的合页被破坏了。",
        },
        "clue_2": {
            "name": "发现到的线索②",
            "release_phase": "discussion_20min",
            "content": "在补给橱柜里找到了钥匙。",
        },
    },
    "solution": {
        "culprit": "wolf",
        "direct_answer": [
            "犯人是狼。",
            "漂亮的碎布是孩童衣服的碎片。",
            "孩童会出现在上锁的补给橱柜里，是因为女巫发现等候室里还有人类后，用钥匙把孩童藏了进去。",
        ],
        "inferred_truth": [
            "木乃伊先把迷路孩童带进了等候室。",
            "吸血鬼在等候室里把孩童吓得继续躲藏。",
            "女巫发现人类存在后，使用钥匙把孩童藏进了补给橱柜。",
            "狼后来撬开补给橱柜，发现孩童并将其吃掉。",
        ],
        "finale_text": [
            "虽然犯人确实存在，但事情并不是单独由一个人的恶意造成的。",
            "每个人的行为都在不知不觉中推动了这起事件的发生。",
            "业主正朝房间走来，众人需要一起决定该如何讲述这个故事的结局。",
        ],
    },
    "timeline": [
        {
            "time": "18:00",
            "facts": [
                "木乃伊发现迷路哭泣的孩童。",
                "木乃伊把孩童带进等候室后离开，去寻找业主。",
                "女巫目击到木乃伊因孩童而慌乱。",
            ],
            "is_inferred": False,
        },
        {
            "time": "19:00",
            "facts": [
                "吸血鬼进入等候室，准备从补给橱柜里拿鲜血果汁。",
                "吸血鬼看到惊慌的孩童后，自己反而被吓跑。",
            ],
            "is_inferred": False,
        },
        {
            "time": "20:00",
            "facts": [
                "女巫进入等候室，发现地上有血和补给橱柜钥匙。",
                "女巫感知到等候室里仍有人类存在。",
                "结合结局文件推断，女巫随后把孩童藏进了补给橱柜。",
            ],
            "is_inferred": True,
        },
        {
            "time": "later",
            "facts": [
                "狼在被孩童们欺负后逃入等候室。",
                "狼找不到钥匙，于是撬坏补给橱柜。",
                "狼在橱柜里发现孩童并将其吃掉。",
                "狼把孩童衣服撕碎并丢进垃圾桶。",
            ],
            "is_inferred": False,
        },
        {
            "time": "22:00",
            "facts": [
                "木乃伊回到等候室，发现孩童已经不见。",
                "木乃伊在垃圾桶里找到漂亮碎布，并拿来当绷带。",
                "狼注意到木乃伊绷带上的漂亮碎布。",
            ],
            "is_inferred": False,
        },
    ],
    "dm_runtime_rules": {
        "language": "中文",
        "voice_mode_assumption": "外部语音转文字后输入给程序，程序本身不识别音色和说话人。",
        "turn_control_rules": [
            "DM 应先让全员安静，再点名指定某位玩家发言。",
            "DM 点名后，下一条输入默认视为该玩家的发言。",
            "若输入与当前被点名玩家不一致，DM 应提醒重新由被点名者发言。",
            "DM 需要主动控制节奏，按阶段公开线索并推进投票。",
        ],
        "spoiler_rules": [
            "在投票和结局阶段前，不得直接说出真相。",
            "当玩家追问超前信息时，只能用引导式提示，不可直接剧透。",
            "DM 需要提醒玩家遵守角色视角，避免说出角色不应知道的事实。",
        ],
    },
    "search_system": {
        "enabled_after_minutes": 10,
        "total_evidence_count": 2,
        "search_targets": {
            "等候室": {
                "name": "等候室",
                "description": "鬼怪们专用的休息室，墙上挂着装饰画框。",
                "clue_id": "clue_1",
                "success_message": "你仔细检查了等候室，发现画框后面藏着补给橱柜的钥匙。你把它放回了原处。",
                "found_clue_text": "【发现线索】画框后面藏着补给橱柜的钥匙！",
            },
            "补给橱柜": {
                "name": "补给橱柜",
                "description": "存放鬼怪重要物品的橱柜，关上后会自动上锁。",
                "clue_id": "clue_2",
                "success_message": "你打开补给橱柜，发现里面有一些生活用品和药物。橱柜的合页有明显的撬痕。",
                "found_clue_text": "【发现线索】补给橱柜的合页被破坏了，有明显撬痕！",
            },
            "橱柜": {
                "name": "补给橱柜",
                "description": "存放鬼怪重要物品的橱柜，关上后会自动上锁。",
                "clue_id": "clue_2",
                "success_message": "你打开补给橱柜，发现里面有一些生活用品和药物。橱柜的合页有明显的撬痕。",
                "found_clue_text": "【发现线索】补给橱柜的合页被破坏了，有明显撬痕！",
            },
            "垃圾桶": {
                "name": "垃圾桶",
                "description": "等候室角落的垃圾桶。",
                "clue_id": None,
                "success_message": "垃圾桶里有一些撕碎的布片，看起来像是衣服碎片。但这不是关键证据。",
                "found_clue_text": None,
            },
            "画框": {
                "name": "画框",
                "description": "等候室墙上的装饰画框。",
                "clue_id": "clue_1",
                "success_message": "你移开画框，发现后面藏着补给橱柜的钥匙。",
                "found_clue_text": "【发现线索】画框后面藏着补给橱柜的钥匙！",
            },
        },
        "search_result_messages": {
            "already_found": "这个线索你已经发现过了。",
            "no_clue_here": "你仔细搜索了这里，但没有发现新的线索。",
            "search_cooldown": "你刚搜索过，需要冷静一下再试。",
        },
    },
}
