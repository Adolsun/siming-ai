"""Shared cataloging prompts for internal and external agents.

This is the single source of truth for project-initialization/cataloging rules.
Internal cataloging, public prompt packs, and MCP prompts should import from
this module instead of maintaining separate long prompt copies.
"""
from __future__ import annotations

import json

from app.modules.continuity.domain.candidate_contract import candidate_contract_examples

from .prompt_source import get_naming_resolution_rules, get_time_tracking_rules


def get_project_binding_rules() -> str:
    return """【项目绑定硬规则】
1. 所有会读取或写入某本作品资料的工具调用，都必须绑定同一个 project_id。
2. 如果刚刚通过 import_file_as_project 或 create_project 创建作品，立刻记录返回的 data.id，并把它作为后续全部工具调用的 project_id。
3. 不要依赖空的 current_project_id。list_projects 返回 current_project_id 为空时，只能说明当前 MCP 会话没有默认作品，不代表可以省略 project_id。
4. save_external_cataloging_facts、save_external_cataloging_candidates、apply_pending_cataloging、verify_external_cataloging_progress、get_project_archive_status 都必须指向同一本作品。
5. 每章写入后必须 verify_external_cataloging_progress；全部完成后必须 get_project_archive_status。只有确认 characters_count、outline_nodes_count、worldbuilding_count、chapter_summaries_count 等数据属于目标 project_id，才可以向用户说“已完成”。
6. 工具返回 status 不是 ok（包括 skipped、error、denied）时，不要继续下一章，也不要汇报成功；应先说明失败工具、detail、下一步修复方式。"""


def get_language_rules() -> str:
    return """【语言规则】
1. 中文小说必须用中文建档。角色名、别名、章节标题、摘要、大纲节点、世界观条目、证据、关系说明都保留原文语言。
2. 不要因为一次工具错误、终端编码显示异常或 MCP 返回转义文本，就把中文改成英文或拼音；不要改成英文或拼音。
3. 只有用户明确要求翻译时，才允许把中文档案翻译为其他语言。
4. 保存前如果看到中文显示成乱码，应停止并报告编码问题，不要自行改成英文档案。"""


def get_outline_granularity_rules() -> str:
    return """【大纲粒度统一规则】
1. 每章必须至少输出 1 条章级大纲候选，node_type 为 "chapter"，表示本章整体节点。章节已有绑定的大纲时，标题必须沿用该节点，系统会更新它的实际摘要，禁止另造同义章节点。
2. 本章存在多个重要场景、连续行动段、视角切换、冲突阶段或明显转折时，必须额外输出 2-6 条 node_type="section" 的 outline_create。
3. section 节点必须使用 parent_title 指向本章 chapter 节点；不要把 section 当成独立章节。
   不得把章节标题写进 parent_id，也不得自行猜测任何数据库 UUID；新节点只用 parent_title 表达父级，真实 ID 由司命解析。
4. chapter 节点 summary 写整章目标、冲突、转折、结果和结尾钩子；section 节点 summary 写该场景的地点、参与角色、行动目标、冲突推进、信息揭示和场景结果。
5. 如果章节非常短且只有单一场景，可以只输出 chapter 节点，但必须在 summary 中说明这是单场景章节。
6. section 节点必须由模型明确填写 scene_number 正整数，并补充 purpose、location、timeline、pov_character、characters、entry_state、exit_state、emotional_residue、unresolved_actions。编号对应 chapter_overview.scenes 的顺序，总数须等于该数组长度；同一场景内的多个事件合并进同一 section，不按事件条数重新分场。系统不按标题或输出次序猜测场景编号。
7. scene_number 是同一章节内的稳定场景键。重新建档时，同一逻辑场景沿用原编号；正文已删除的场景不要继续输出，系统会退役旧的建档场景节点。
8. 内部建档、外部 MCP 建档、本机 CLI 建档都必须遵守同一套大纲粒度规则；不要因为调用方式不同降低粒度。"""


def get_fact_extraction_rules() -> str:
    return """【事实抽取统一规则】
1. 只裸读当前章节正文，不读取旧角色卡、旧世界观和旧大纲。
2. 只抽取会影响大纲、角色、关系、世界观或后续写作连续性的事实，不复述普通动作流水账。
3. 只输出 JSONL；每一行是一个完整 JSON 对象；不要输出 Markdown、解释、代码块或 JSON 数组。
4. 字符串里的换行、引号、反斜杠必须正确转义。
5. 不做最终写入决策，不输出 character_create、worldbuilding_create、outline_create 等候选类型。
6. 只根据本章正文抽取事实；不确定的信息写入 uncertainty 字段，不要强行定论。
7. “处于同一流程”或“指向同一查询方向”只说明程序框架一致，不等于材料互相印证。除非正文明确说明两个独立来源分别确认同一事实，否则不得升级为“互相印证”“相互验证”或“形成闭环”；正文写明来源独立、互不背书或尚未校验时，chapter_overview 和 outline_fact 必须保留该限制。

允许的 fact_type：
- chapter_overview：本章整体摘要、关键事件、场景列表。
- character_fact：人物/称呼/身份/状态/行动/心理/物品/关系线索。
- relationship_fact：两个角色之间的互动或关系变化。
- worldbuilding_fact：地点、势力、修炼规则、道具、历史、种族、制度等设定事实。
- outline_fact：本章可拆成的大纲节点或场景节点。
- identity_hint：疑似同一角色、马甲、称呼变化、隐藏身份线索。

每行格式：
{"fact_type":"...","confidence":0.9,"evidence":"原文依据或概述","payload":{...}}

字段要求：
1. chapter_overview 必须且只能输出 1 条。payload.scenes 必须按叙事地点、时间连续性和行动目标合并为 1-6 个故事场景；同一地点和连续行动中的短步骤、电话、群聊或编辑修改不能各拆成独立场景。超过 6 个时合并相邻片段，保证后续每个 scene 恰好对应一个 section 大纲节点。
2. character_fact.payload 必须包含 archive_identity（stable_character|anonymous_role|mention_only）和 stable_profile_change（true|false），并尽量包含 names、primary_name、aliases、role_hint、age、actions、state_changes、appearance_clues、background_clues、location、realm_or_level、physical_state、mental_state、goals、items_or_assets、keywords。正文能唯一识别、后文可继续指向的具名人物必须标 stable_character，即使本章只有提及、电话、消息或回忆而没有现场出场；“提及”属于后续 chapter_link.appearance_type，不得因此把稳定人物降为 mention_only。未具名但参与事件的岗位或临时称谓标 anonymous_role；群体、泛指和无法形成稳定身份的文字才标 mention_only，不得为了建卡把岗位当姓名。每个身份只输出一条 character_fact，不得按场景重复。只有本章确实新增或改变稳定人设时 stable_profile_change=true 并写 profile_clues，其中可含 core_motivation、inner_lack、core_belief、public_persona、hidden_persona、reveal_chapter、moral_taboo、voice、action_habit、trauma_trigger。不要为了填字段推测。电话或消息参与者的实时地点只有在正文明确交代时才写 location，不得从通话另一端所在场景推断；未交代时省略 location，并可在 uncertainty 说明。actions、items_or_assets 必须归属于该 character_fact 的人物；涉及地点或物件归属时，evidence 必须提供能直接确认人物与地点、拿取、递交、持有、归还或使用关系的短原文摘录，不能把同场其他人物经手的物件转写给当前人物。
3. worldbuilding_fact.payload 必须包含 archive_identity（stable_setting|mention_only）和 stable_setting_change（true|false），并尽量包含 canonical_title_hint、title_hint、dimension_hint、keywords、content_points、rules、limits、affected_characters。只有会持续影响后文、需要设定卡或章节关联的规则、地点、组织、文书、物件或历史事实才标 stable_setting；数字片段、字段名、一次性措辞、尚未定位的泛称和仅作为证据引用的文本标 mention_only。事实阶段不能读取旧档案，因此 canonical_title_hint 只写正文能支持的稳定称呼，不猜数据库 ID；候选阶段再与 active 设定的精确标题和 ID 对齐。只有本章新增、确认或改变稳定设定时 stable_setting_change=true；普通提及写 false。
4. identity_hint.payload 必须包含 names、reason、evidence_points、confidence_reason。疑似同一人但未实锤也要输出，供下一阶段读取相关卡片。
5. outline_fact.payload 包含 title_hint、node_type、summary、characters、hook。
6. outline_fact 要覆盖整章节点和重要场景节点；有多个场景时要分别抽取 outline_fact，供候选阶段生成 section 节点。
7. 正文明示亲属、师徒、盟友、敌对、主从、合作或情感关系，或既有关系发生变化时，必须另输出 relationship_fact，不得只塞进 character_fact。relationship_fact.payload 必须包含 source_name、target_name、relationship_type、description；两个端点都必须各有 archive_identity=stable_character 的 character_fact，并列入 chapter_overview.cataloging_characters。端点不能是地点、功法、组织、事件、anonymous_role 或 mention_only。同一有向角色对只输出一条关系事实，relationship_type 是该边的当前类型；后续章节应更新该边，不得用“协作／搭档／合作伙伴”等近义类型为同一方向重复建边。
8. chapter_overview.payload 除 summary、key_events、scenes 外，必须分别列出 cataloging_characters（只含 stable_character 的稳定主名）与 anonymous_participants（所有 anonymous_role 和 mention_only 的主称呼），并分别列出 cataloging_worldbuilding_titles（只含 stable_setting 的稳定称呼）与 incidental_worldbuilding_mentions（所有 mention_only 的一次性片段）；没有时写 []。四个数组必须与其余事实逐项一致：不能漏项、额外添加、重复，也不能让同一身份同时出现在两个范围。characters 和 worldbuilding_titles 可作为阅读盘点保留，但不能替代这四个权威范围数组。
9. evidence 写短依据，payload 用短语和数组表达，不要复制大段原文。"""


def get_cataloging_candidate_schema() -> str:
    return (
        """【允许的候选 type 与 payload】
首次生成回合的首个响应对象必须同时包含两个必填对象：
{"chapter_summary":{"summary_text":"...","coverage_manifest":{"scene_count":1,"characters":[],"worldbuilding":[],"relationships":[],"character_profiles":[]},"narrative_state":{"events":[],"timeline_events":[],"foreshadowing_planted":[],"foreshadowing_resolved":[],"storyline_progress":[],"new_storylines":[],"reader_known_facts":[],"character_known_facts":[],"unresolved_actions":[]},"narrative_review":{"source":"provided","outcome":"assessed"}},"chapter_outline":{"title":"当前章节原题","summary":"...","node_type":"chapter","status":"completed"}}
系统会把这两个必填对象拆成 chapter_summary 与章级 outline_create。增量修复回合不重复这个骨架，只输出校验明确指出的缺失或失败候选；chapter_summary 或 chapter_outline 只有在明确缺失时才补。没有角色、新设定或关系时，coverage_manifest 对应项必须是 []，不得虚构补卡。
除首次生成回合的首个必填骨架对象外，每一行顶层都必须包含标准字段 type，例如 {"type":"worldbuilding_create", ...}。type 决定候选类别；不要把候选类别写进 node_type。
node_type 只用于 outline_create/outline_update 的层级，而且只能是 chapter、section 或 volume；世界观、角色等候选不得输出 node_type。所有大纲候选必须显式提供 character_ids 数组，已有角色从目录复制真实 ID，新角色引用其 character_create.client_id，无已建档人物写 []；characters 只供场景描述，不用于绑定，不再输出 related_characters。
- chapter_summary: {"summary_text":"...", "key_events":["..."], "characters":["..."], "worldbuilding":["..."], "coverage_manifest":{"scene_count":1,"characters":["..."],"worldbuilding":["..."],"relationships":[{"source_name":"...","target_name":"...","relationship_type":"..."}],"character_profiles":["本章新建或稳定档案发生变化的角色名"]}, "outline_hint":"...", "narrative_state":{"events":[...], "timeline_events":[...], "foreshadowing_planted":[...], "foreshadowing_resolved":[...], "storyline_progress":[...], "new_storylines":[...], "reader_known_facts":[...], "character_known_facts":[...], "unresolved_actions":[...]}, "narrative_review":{"source":"provided", "outcome":"assessed", "evidence":"本章叙事治理检查依据"}}
- outline_create / outline_update: {"title":"...", "summary":"...", "actual_summary":"...", "planned_summary":"...", "node_type":"chapter", "parent_title":"...", "status":"completed", "character_ids":["从角色目录复制真实ID"], "scene_number":1, "purpose":"...", "location":"...", "timeline":"...", "pov_character":"...", "characters":["..."], "entry_state":"...", "exit_state":"...", "emotional_residue":"...", "unresolved_actions":[...]}
- character_create: {"client_id":"新建角色的唯一UUID，供同批大纲引用", "name":"...", "aliases":["..."], "role_type":"supporting", "age":"...", "appearance":"...", "personality":"...", "background":"正文确认的稳定身份和经历", "abilities":["..."], "profile":{"core_motivation":"...","inner_lack":"...","core_belief":"...","public_persona":"...","hidden_persona":"...","reveal_chapter":3,"moral_taboo":"...","voice":"...","action_habit":"...","trauma_trigger":"..."}, "tone_style":"...", "catchphrases":["..."], "verbosity":"moderate", "emotion_tendency":"...", "custom_system_prompt":"..."}。仅用于新角色，禁止传入已有角色 id。新角色 client_id 必须是未使用的规范 UUID；同批大纲使用该 UUID。
"""
        '- character_update: {"id":"从 relevant_characters、character_name_index 或 '
        'character_alias_index 逐字复制的真实角色 ID，必填", "name":"已有稳定主名", '
        '"background_before":"修改 background 时逐字复制当前完整值", '
        '"background":"逐字保留旧背景并追加正文确认的稳定信息", '
        '"profile":{"本章变化的档案字段":"新值"}}。其余可修改字段与 character_create 相同，'
        '只提交本章确有变化的字段；不修改 background 就同时省略 background 与 background_before，'
        '不能照抄示例占位内容。\n'
        """- character_state_update: {"name":"...", "aliases":["..."], "appearance_before":"修改外貌时逐字复制当前值", "appearance_evidence":"本章正文逐字摘录", "appearance":"...", "age_before":"修改年龄时逐字复制当前值", "age_evidence":"本章正文逐字摘录", "age":"...", "life_status":"alive", "current_location":"...", "realm_or_level":"...", "physical_state":"...", "mental_state":"...", "current_goal":"...", "active_conflict":"...", "abilities_state":"...", "items_or_assets_before":"修改物品时逐字复制当前完整值", "items_or_assets":"逐字保留旧值并追加本章变化后的完整状态"}
- character_timeline: {"name":"...", "event_description":"...", "event_type":"appearance|decision|injury|breakthrough|relationship_change|conflict|death|status_change|key_event", "emotional_state_change":"..."}
- character_relationship: {"source_name":"...", "target_name":"...", "relationship_type":"...", "description":"..."}
- character_merge_candidate: {"primary_name":"...", "secondary_name":"...", "canonical_name":"...", "aliases":["..."], "confidence_reason":"...", "evidence_points":["..."], "background_append":"..."}
- worldbuilding_create: {"dimension":"power_system", "title":"...", "content":"...", "status":"active", "source_fact_titles":["该设定对应的原事实称呼；无称呼差异可省略此字段"], "identity_resolution":{"decision":"create", "reviewed_existing_ids":["逐字复制 worldbuilding_identity_review_required 中的全部 ID；列表为空时至少复制完整标题索引中最接近的一个 ID"], "reason":"逐项说明为何不是这些旧条目的更新"}}
- worldbuilding_update: {"id":"从 worldbuilding_title_index 或 relevant_worldbuilding 逐字复制的已有条目ID", "dimension":"power_system", "title":"沿用已有稳定标题", "content":"...", "status":"active", "source_fact_titles":["归入该卡的原事实称呼"]}
- worldbuilding_timeline: {"id":"已有设定时复制其ID；新设定可省略", "title":"...", "dimension":"...", "event_description":"...", "event_type":"introduced|confirmed|changed|damaged|used|limited", "evidence":"...", "source_fact_titles":["归入该卡的原事实称呼"]}
- chapter_link: {"characters":[{"name":"...","appearance_type":"出场"}], "worldbuilding_titles":["..."], "outline_title":"...", "description":"...", "locations":["..."], "items":["..."], "events":["..."], "importance":"normal", "appearance_order":1}"""
    )


def get_cataloging_candidate_rules() -> str:
    return """【候选写入规则】
1. 每章必须至少生成 1 条 chapter_summary 和 1 条 chapter 级 outline_create。
   首次生成回合的第一行必须使用上述 chapter_summary + chapter_outline 必填响应对象；不能只返回其中一个，也不能先只返回摘要再提前结束。增量修复回合只补校验明确指出的缺失或失败候选，不得重复已通过候选。
   chapter_summary 必须包含非空 summary_text，用一段话概括本章已经发生的主要事件；同时显式包含完整 narrative_state，没有发现时也要保留所有数组并填写 []，并提供 narrative_review，不能用“字段缺失”表示“没有问题”。
   foreshadowing_planted、storyline_progress、unresolved_actions 中每个治理条目的 evidence 必须填写当前章节中可逐字检索的 6-120 字原文摘录，禁止用概述替代；找不到原文摘录时不要生成该条目。foreshadowing_resolved 等解决项必须携带已有治理项的 resolves_item_id 或 resolves_dedupe_key；找不到稳定引用时只报告待复核，不得按标题猜测并关闭旧记录。
   coverage_manifest 必须显式包含 scene_count、characters、worldbuilding、relationships、character_profiles 五项；空项也写 []。relationships 列出本章明确出现、确认或改变且影响后续连续性的角色关系，character_profiles 列出本章需要新建或更新稳定档案的角色。
   大纲粒度必须遵守【大纲粒度统一规则】：有多个重要场景时，除了 chapter 节点，还要输出 2-6 条 node_type="section" 的 outline_create，并用 parent_title 指向本章 chapter 节点。

2. 每个出场角色必须输出 character_state_update；稳定档案有新信息时才另输出 character_update，全新角色先用 character_create 建卡。
   当前状态与稳定档案是两个不同的候选类型：

   character_state_update — 当前状态（按传入字段更新）：
   可选字段：appearance、age、life_status、current_location、realm_or_level、physical_state、mental_state、current_goal、active_conflict、abilities_state、items_or_assets。
   先读取当前完整角色卡，只提交本章有依据的状态；未变化或未交代的字段必须省略，司命保留原值。不要为满足出场覆盖而重新概括年龄、外观或物品，也不要用“不详”等占位值覆盖已有信息。
   每个出场角色仍须有同身份状态候选。若没有任何已知状态变化，可以只逐字沿用已读取的 life_status 等一项已知状态，不要重写整张卡。
   appearance、age 只有正文确认外观变化或时间推进时才提交；修改已有值时分别用 appearance_before、age_before 逐字复制当前值，并用 appearance_evidence、age_evidence 提交本章正文中的逐字摘录。正文没有明确证据时省略这些字段；空字符串不表示清除旧状态。
   电话或消息直接参与只决定 chapter_link 的出场类型，不能证明参与者身处通话另一端的场景；正文未明确其实时地点时省略 current_location，保留旧值，不得把场景地点写给远端参与者。
   items_or_assets 是整字段替换，不是自动追加。已有非空值且本章确需更新时，必须同时提交 items_or_assets_before，逐字复制当前完整值；items_or_assets 新值也必须逐字包含该完整旧值，再追加取得、转交、归还、遗失或销毁状态。自动建档禁止删除旧记录；确需删除由作者在角色编辑中复核。不得用本章的短物品列表覆盖此前仍有效的资产。每件物品必须确由该角色持有、控制或经手；同场另一人物拿取或归还的物件不能记到当前角色名下。

   character_update — 角色档案（有新信息就输出）：
   包含：name、aliases、role_type、personality、background、abilities、profile、tone_style、catchphrases、verbosity、emotion_tendency、custom_system_prompt。
   profile 是角色卡“稳定写作锁”，只依据正文和已有档案合并已知信息：core_motivation、inner_lack、core_belief、public_persona、hidden_persona、reveal_chapter、moral_taboo、voice、action_habit、trauma_trigger。新角色必须尽量补齐；已有角色在本章揭示或改变这些信息时必须更新。不得为了填满字段编造正文不存在的事实。
   ⚠️ personality、background 和 custom_system_prompt 只要提交，就必须是合并后的完整字段值，系统会直接替换该字段：
   - 已有角色修改 background 时必须提交 background_before，逐字复制当前完整背景；新 background 必须逐字包含该旧值，只追加正文确认、会长期影响后文的稳定身份或经历。自动建档禁止改写、缩短或删除旧背景；确需重写由作者在角色编辑中复核。
   - 不要只写”本章新增：xxx”，要写”角色名，身份xxx，曾经历xxx，本章又xxx”。
   - personality 与 custom_system_prompt 也要输出可直接替换旧字段的完整版本，不要输出增量片段。
   - aliases 要包含所有已知称呼（本章新发现的 + 之前已有的）。
   如果本章没有任何新的角色信息（只是出场但没揭示新内容），可以不输出 character_update。

3. 未具名岗位、临时称谓和泛指人物不是稳定角色身份。例如正文只写“排期编辑”“保管员”“门卫”“护士”“路人”，且没有给出姓名、可持续识别信息或与现有角色相同的明确证据时：
   - 只把其行动写入章节摘要、section 场景、地点或事件；不得创建角色卡、状态卡、角色关系、角色档案或角色章节关联。
   - 不得因为两个章节都出现相同岗位称谓，就把他们合并为同一个既有角色；只有读取到现有角色的精确 id 且正文明确确认是同一人时，才能更新该角色。
   - coverage_manifest.characters 和 character_profiles 只列稳定、可持续识别的角色；匿名岗位不列入。空数组是正确结果，不得为满足覆盖数量虚构永久角色。

4. age 是描述性文本，不是精确数字。示例：”3岁”、”约16岁”、”外表约16岁，实际经历约200年”、”年龄不详”。

5. character_create 用于新角色，尽量包含 name、aliases、role_type、appearance、personality、background、abilities、profile、tone_style、catchphrases、verbosity、emotion_tendency、custom_system_prompt；role_type 只能填写 protagonist、supporting、antagonist、mentor、other 中的一个，身份、年龄等描述必须放在其他字段，不得拼进 role_type；并把该角色写入 coverage_manifest.character_profiles。

6. 角色有多个称呼时，name 放最稳定主名，aliases 放亲属称呼、尊称、昵称、身份名、化名。发现两个卡片其实是同一人时，输出 character_merge_candidate。

7. 世界观 dimension 必须使用 geography、history、factions、power_system、races、culture。修炼体系、阵法、病毒、封印优先 power_system；宗门/家族/组织优先 factions；地点优先 geography，不要全塞进 culture。

8. 新设定写 worldbuilding_create；只要当前作品已有世界观，create 就必须带 identity_resolution。reviewed_existing_ids 必须逐字覆盖 worldbuilding_identity_review_required 中已交付的全部 ID；该列表为空时，至少从完整 worldbuilding_title_index 选择一个最接近的真实旧条目 ID。由你逐项说明为何不是这些旧条目的更新。已有设定发生变化写 worldbuilding_update，并必须从 worldbuilding_title_index 或 relevant_worldbuilding 逐字复制该条目的精确 id。已有设定被验证、破坏、限制或使用时，worldbuilding_timeline 也应携带同一 id。不得编造 ID，不得把已有设定改成近义标题后另建新卡；无法确认对应条目时停止并要求补充上下文。
   worldbuilding_create 只用于具有独立身份、独立生命周期或状态、且未来可脱离现有条目单独变化的实体。既有流程的一步、操作视角、字段、校验方法或细化规则，必须更新该流程的规范卡或写其时间线，不能另建卡。把多张现有卡重新归组形成的“证据链”、集合、章节结论或阶段汇总，应写入章节摘要、叙事账本、章节关联或各规范卡的时间线，不得把该汇总本身创建为世界观实体。如果新信息可以在不改变既有条目身份和稳定标题的前提下追加到一张旧卡，就必须 update/timeline；仅声称“层级不同”不是有效的新建理由。identity_resolution.reason 必须说明该实体为何需要独立持续存在，以及合并到逐项审阅的旧卡为何会损害其真实身份。

9. 章节涉及的角色、世界观、大纲必须用 chapter_link 或对应摘要字段建立关联。chapter_link.characters 中每个人物都必须由你按正文明确标注 appearance_type：人物在当前叙事场景中行动或通过电话、消息直接参与写“出场”，只被他人谈到或只出现在档案、名单、函件收件人中写“提及”，仅在回忆段落中出现写“回忆”；聚合 chapter_link 中每个角色只出现一次，由你选择一个 appearance_type；应用不会根据人物名或自然语言替你猜测。

10. 角色关系不能只在自然语言摘要里一带而过。亲属、师徒、盟友、敌对、主从、利益合作、情感关系等，只要正文明确确认、首次出现或发生变化且会影响后续写作，就必须同时：
    - 写入 coverage_manifest.relationships（source_name、target_name、relationship_type）；
    - 输出一张同身份的 character_relationship 候选，description 写清依据和本章表现；
    - 关系双方都列入 coverage_manifest.characters，并已有角色档案或在本章先输出 character_create/update。
    同一有向角色对只能保留一个当前 relationship_type，不得同时声明近义类型；首次清单误列多个时用 coverage_manifest_mode="replace" 纠正。
    不得用地点、功法、组织、事件充当关系端点，也不得靠 character_relationship 顺带创建空白角色卡。

11. 每次建档都是当前已保存章节版本的完整投影，不是向旧投影追加一份副本：
    - 同名角色、设定、关系、章级大纲和同 scene_number 场景表示更新；确实不存在时才创建。
    - 章节摘要、实际大纲摘要、章节关联和时间线写当前版本的完整值；不要保留正文已经删掉的旧事件。
    - 不得为了表达“正文有修改”而给实体或场景改一个近义标题；稳定主名、设定标题和场景编号必须沿用。"""


def get_incremental_cataloging_repair_rules() -> str:
    return """【候选缺项自动修复】
1. 当用户消息包含“上一轮校验未通过”，或工具返回 validation_errors、candidate_errors、missing_required_items 时，这是增量修复回合，本节规则优先于首次生成规则。读取 recovery_context.accepted_candidates 核对检查点，必要时按 read_full_candidates 分页读取完整候选。系统已经保留上一轮通过的候选；只输出错误信息明确指出的缺失候选，或解析失败、身份不一致、结构错误候选的修正版。数组与对象须直接传入，type、role_type、dimension 须直接使用标准枚举，程序不会猜测替换。
2. 不要重发完整候选集，不得重复、删除、缩减或改写已有正确候选。chapter_outline 只有在缺失时输出；chapter_summary 在缺失或明确纠正错误覆盖清单时输出。
3. 增量修复不得减少 scene_count。先核对已保留候选与事实，缺项就补齐候选；若 coverage_manifest 误列了同一身份的不同称呼，或把 stable_profile_change=false 且无稳定档案变化的已有角色误列为档案更新对象，可以输出一条 chapter_summary，设置 coverage_manifest_mode="replace"，提供完整纠正清单。不得为补齐错误清单而虚构档案变化或新建近义卡；也不能删掉事实中确实存在的角色、设定、关系或稳定档案变化来绕过校验。已有事实归入精确 ID 的世界观卡时，摘要清单只列规范卡稳定标题；另行输出该世界观候选，在其 payload.source_fact_titles 字符串数组中声明原事实标签。source_fact_titles 禁止放进 chapter_summary、coverage_manifest 或 chapter_link，禁止写成 {"worldbuilding":[...]} 对象；摘要修复和世界观来源映射是两类候选，分别输出。若返回 coverage_repairs，按其中 candidate_id、field 和 required_mode 修正摘要清单或章节关联，使用模型已声明的规范标题并保留其他内容；mapping_candidate_id 指向的世界观候选已经保存，仅重发它不能修复摘要或关联。
4. 错误若列出缺失场景编号，逐个输出对应 scene_number 的 section outline_create，并填写 purpose、location、timeline、pov_character、characters、entry_state、exit_state、emotional_residue、unresolved_actions；不要用重写摘要代替场景卡。
5. 若 scene_repair 显示越界、重复或错位场景，必须对照 source_scenes 完整重排全部场景，不能只删末条或换编号覆盖其他场景。单独输出 {"type":"scene_outline_replace","expected_candidate_ids":["当前全部section候选ID"],"sections":[全部N条完整的outline_create/section候选]}；sections 必须唯一覆盖1..N并保留全部源场景事件及状态。系统在全部修正版通过后原子替换当前场景候选集，失败则全部回滚，旧候选保留审计记录。只能替换本次运行未被作者编辑的pending场景，不能改动章级大纲、其他章节或已应用候选。
5. 错误若列出缺失角色、设定、关系或章节关联，逐个输出相同稳定主名/标题/关系端点的对应候选。别名只放 aliases，不得在主名与别名之间切换。
6. 输出完成后立即结束，不要附带解释。"""


def get_candidate_resolution_rules() -> str:
    return "\n\n".join([
        """【候选生成统一规则】
1. 你会收到当前章节事实 JSONL，以及系统按事实检索出的相关角色、世界观、大纲、关系和索引。
2. 任务是把“新事实 + 相关旧资料”合并成可写入数据库的候选项，不要重新写读后感。
3. 只输出 JSONL；每一行是一个完整 JSON 对象；不要输出 Markdown、解释、代码块或 JSON 数组。
4. 首次生成回合的第一行必须按【允许的候选 type 与 payload】一次性输出 chapter_summary + chapter_outline 必填骨架；其余候选单独成行。增量修复回合只输出校验明确指出的缺失或失败候选。
   除首次生成回合的首个必填骨架外，禁止输出包含 character_state_updates、worldbuilding_entries、outline_creates、chapter_links 等列表的聚合对象。
5. 首次生成回合必须输出 1 条 chapter_summary，并包含非空 summary_text；不得只返回摘要后结束。增量修复时，已通过的 chapter_summary 不得重复输出。
6. 根据事实和相关卡片判断是创建、更新、关联还是提出角色合并候选。
7. payload 要足够写库但不冗长；不要重复粘贴旧资料，不要输出无变化字段。""",
        get_outline_granularity_rules(),
        get_cataloging_candidate_rules(),
        get_incremental_cataloging_repair_rules(),
    ])


def get_external_no_api_rules() -> str:
    from .prompt_source import get_api_free_mode_rules
    return get_api_free_mode_rules() + """

【编目专用补充规则】
1. 使用与内部建档一致的质量工具链：facts -> candidates -> apply -> verify。
2. facts 阶段只读当前章节正文并调用 save_external_cataloging_facts；不得读取旧档案或提前做创建、更新决策。
3. candidates 阶段调用 list_cataloging_facts，has_more=true 时按 next_arguments 读完各页；结合当前档案镜像生成候选，调用 save_external_cataloging_candidates。
4. 准备 candidates 时保持 JSONL 颗粒度：一条候选对应一个对象；不要把整章合成一个大对象。
5. 世界观镜像中 status 不是 active 的条目只用于历史审计，不得作为当前设定、候选更新目标或后续创作上下文；以工具返回的 worldbuilding_title_index 精确 ID 为准。

【顺序规则】
- 建档必须逐章串行：phase="facts" → save_external_cataloging_facts → phase="candidates" → list_cataloging_facts → save_external_cataloging_candidates → apply_pending_cataloging → verify_external_cataloging_progress。
- 禁止并行处理后续章节；前一章创建/更新的角色、世界观和大纲会影响后一章应使用 create 还是 update。
- 每章必须完成 apply_pending_cataloging 后才能处理下一章。
- 候选只是暂存，不应用就不会出现在角色、大纲、世界观、章节摘要里。

推荐工作流：
1. 调用 start_external_cataloging_job 创建任务。
2. 调用 get_next_external_cataloging_chapter(phase="facts")，裸读返回的最早未完成章节，保存规范事实。
3. 调用 get_next_external_cataloging_chapter(phase="candidates") 和 list_cataloging_facts，读取与事实有关的档案镜像，生成完整候选并保存。
4. apply_pending_cataloging 后立刻 verify_external_cataloging_progress；验证完成后再处理下一章。
5. 最终 verify_external_cataloging_progress + get_project_archive_status 验证。"""


def get_internal_cataloging_system_prompt() -> str:
    return "\n\n".join([
        "你是“作品建档”初始化抽取器。目标不是写读后感，而是把单章正文拆成可长期用于写作助手的结构化资料：章节摘要、大纲节点、角色档案、角色状态、角色关系、世界观设定和时间线。",
        "硬性输出规则：只输出 JSONL；每一行必须是一个完整 JSON 对象；不要输出 Markdown、解释、代码块或 JSON 数组。每条信息一行，不要为了省行数合并重要信息。",
        get_language_rules(),
        get_outline_granularity_rules(),
        get_cataloging_candidate_rules(),
        get_incremental_cataloging_repair_rules(),
        get_time_tracking_rules(),
        get_naming_resolution_rules(),
        get_cataloging_candidate_schema(),
    ])


def get_external_cataloging_system_prompt() -> str:
    return "\n\n".join([
        "你是一个外部编目 Agent。你的任务是在不调用司命内部模型 API 的情况下，对导入的小说项目进行编目：提取角色、世界观、大纲和章节摘要，并通过司命工具保存到正确作品。",
        get_project_binding_rules(),
        get_language_rules(),
        get_external_no_api_rules(),
        get_fact_extraction_rules(),
        get_outline_granularity_rules(),
        get_cataloging_candidate_rules(),
        get_incremental_cataloging_repair_rules(),
        get_time_tracking_rules(),
        get_naming_resolution_rules(),
        get_cataloging_candidate_schema(),
        get_candidate_format_examples(),
        get_merge_rules(),
        get_completion_criteria(),
    ])


def get_candidate_format_examples() -> str:
    return (
        "【候选类型格式】\n"
        "以下为原生 JSON 结构示例；占位名称必须由模型替换成已读取的真实数据。\n"
        "候选的 type 和字段位于同一层，不能把数组或对象编码成字符串。\n"
        "摘要与章级大纲属于首次骨架；已有候选时只补缺项。chapter_link 为全章一条聚合关联，"
        "characters 内每个角色只出现一次，appearance_type 必须从出场、提及、回忆中选一个。\n"
        + "\n".join(json.dumps(row, ensure_ascii=False) for row in candidate_contract_examples())
    )


def get_merge_rules() -> str:
    return """【合并规则】
- 角色别名：如果同一角色有多个名字，使用主名字作为规范名
- 角色当前状态字段：覆盖旧状态
- 角色背景：自动建档必须逐字保留旧背景并追加稳定信息；需要改写或删除时由作者编辑复核
- 角色外貌、custom_system_prompt：合并后输出可直接替换旧字段的完整版本
- 世界观：新卡只用于上下文中不存在的新设定；更新已有卡必须使用上下文提供的精确 ID，并沿用其稳定标题
- 大纲：每章创建一个新节点，除非明确对应现有节点"""


def get_completion_criteria() -> str:
    return """【工具返回契约】
每次工具调用后必须读取返回 JSON 的 status：
- status == “ok”：继续下一步。
- status != “ok”：立即停止，报告失败工具、status、detail，不要继续下一章，不要说完成。
写入后必须用新的查询验证，不要用缓存结果代替验证。

【完成标准】
最终调用 get_project_archive_status，且确认数据属于目标 project_id。通常应满足：
- chapters_count > 0
- chapter_summaries_count > 0
- outline_nodes_count > 0
- characters_count > 0
- worldbuilding_count > 0（类型小说通常应有）
- warnings 为空或已解释并处理
不满足时只能说”尚未完成”，并给出下一步。"""


def get_external_cataloging_workflow() -> list[dict[str, object]]:
    return [
        {"step": 1, "name": "select_project", "description": "导入或选择作品，记录 project_id"},
        {"step": 2, "name": "start_job", "description": "使用 project_id 创建外部无 API 建档任务"},
        {"step": 3, "name": "extract_facts", "description": "领取 phase='facts'：只读当前章 → save_external_cataloging_facts", "parallel": False},
        {"step": 4, "name": "resolve_candidates", "description": "领取 phase='candidates'：读取已保存事实与当前档案 → save_external_cataloging_candidates", "parallel": False},
        {"step": 5, "name": "apply_and_verify", "description": "apply_pending_cataloging → verify_external_cataloging_progress → 再处理下一章", "parallel": False},
        {"step": 6, "name": "final_verify", "description": "verify_external_cataloging_progress + get_project_archive_status 验证作品档案计数"},
    ]


def get_external_cataloging_forbidden_patterns() -> list[str]:
    return [
        "不要把中文小说档案改成英文或拼音",
        "不要调用需要司命 API 的内部 LLM 工具",
        "不要在工具 status != ok 后继续处理下一章",
        "不要报告完成除非 get_project_archive_status 验证通过",
        "不要跳过 apply_pending_cataloging",
        "不要跳过读写验证",
        "不要把角色当前状态字段拼接旧章节状态",
    ]
