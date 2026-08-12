"""Regression tests for input-aware de-AI revision prompts."""

from app.prompts.anti_ai_prompts import (
    build_de_ai_candidate_preserving_expansion_prompt,
    analyze_de_ai_fingerprints,
    build_de_ai_chunk_repair_prompt,
    build_de_ai_chunked_rewrite_prompts,
    build_de_ai_detector_feedback_repair_prompt,
    build_de_ai_detector_ledger_compression_prompt,
    build_de_ai_fidelity_audit_prompt,
    build_de_ai_rewrite_from_ledger_prompt,
    build_de_ai_rewrite_prompt,
    build_de_ai_story_ledger_prompt,
    build_de_ai_style_audit_prompt,
    build_de_ai_style_repair_prompt,
)
from app.services.de_ai_validation import (
    assess_de_ai_revision,
    count_de_ai_visible_characters,
    de_ai_chunk_length_rank,
    parse_de_ai_chunk_target,
    parse_de_ai_fidelity_audit,
    parse_de_ai_style_audit,
)


def test_chunk_length_rank_keeps_best_attempt_instead_of_last_attempt():
    target = (400, 500)

    assert de_ai_chunk_length_rank(430, target) < de_ai_chunk_length_rank(250, target)
    assert de_ai_chunk_length_rank(390, target) < de_ai_chunk_length_rank(360, target)
    assert de_ai_chunk_length_rank(510, target) < de_ai_chunk_length_rank(540, target)


def test_fingerprint_report_targets_phrases_that_are_actually_present():
    source = (
        "林照站在门边，不由得深吸一口气。仿佛只要推开这扇门，命运就会改变。\n\n"
        "然而他没有动。值得注意的是，这一切都说明那封信比他想的更危险。"
    )

    report = analyze_de_ai_fingerprints(source)

    groups = {item["label"]: item for item in report["phrase_groups"]}
    assert groups["模糊比拟"]["examples"] == ["仿佛"]
    assert groups["自动心理反应"]["examples"] == ["不由得"]
    assert groups["神态动作套件"]["examples"] == ["深吸一口气"]
    assert groups["解释与总结"]["count"] == 2
    assert report["character_count"] > 40
    assert report["sentence_count"] == 4


def test_rewrite_prompt_is_targeted_and_does_not_prime_absent_cliches():
    source = "老周把找零推回来。\n\n“少两块。”他说。柜台后的人重新数了一遍。"

    prompt = build_de_ai_rewrite_prompt(source)

    assert source in prompt
    assert "故事保真合同" in prompt
    assert "逐段事实账本" in prompt
    assert "不新增原文没有的动作、感官、回忆、动机、关系或世界设定" in prompt
    assert "不是禁词替换题" in prompt
    assert "嘴角勾起" not in prompt
    assert "瞳孔微缩" not in prompt
    assert "前所未有" not in prompt
    assert "加感官细节" not in prompt


def test_repeated_revision_reaudits_residual_text_instead_of_replaying_same_targets():
    first = "他不由得皱眉，眼中闪过一丝疑惑。然而，这意味着对方早有准备。"
    later = "他看完第二页，把纸翻回第一面。对方早有准备。"

    first_prompt = build_de_ai_rewrite_prompt(first)
    later_prompt = build_de_ai_rewrite_prompt(later)

    assert "不由得" in first_prompt
    assert "眼中闪过" in first_prompt
    assert "这意味着" in first_prompt
    assert "不由得" not in later_prompt
    assert "眼中闪过" not in later_prompt
    assert "这意味着" not in later_prompt
    assert "未命中明显套话" in later_prompt


def test_long_chapter_diagnostics_stay_compact():
    paragraph = "陈禾核对门牌，把钥匙塞回口袋。他敲了两次门，屋里没人答应。"
    source = "\n\n".join(paragraph for _ in range(90))

    prompt = build_de_ai_rewrite_prompt(source)

    # The source is included once. Diagnostics must remain a small constant
    # overhead even for a 2,000-3,000-character chapter.
    assert prompt.count(source) == 1
    assert len(prompt) - len(source) < 2_200
    assert "段落体量过于齐整" in prompt
    assert "句首锚点重复" in prompt


def test_two_stage_prompts_isolate_source_prose_from_final_redraft():
    source = "周砚在7月12日把三封信送到A17仓库。陈禾发现第三封的封口被换过。"
    ledger = "叙事约束：第三人称限知，周砚视角。\n01 周砚；7月12日；三封信→A17仓库。\n02 陈禾检查→第三封封口换过。"

    extraction_prompt = build_de_ai_story_ledger_prompt(source)
    redraft_prompt = build_de_ai_rewrite_from_ledger_prompt(source, ledger)

    assert source in extraction_prompt
    assert ledger in redraft_prompt
    assert source not in redraft_prompt
    assert "原稿措辞已被隔离" in redraft_prompt


def test_story_ledger_prompt_compresses_micro_actions_without_dropping_core_facts():
    source = "周砚看向门，又摸了摸钥匙。三天内没有消息，就投进三号信箱。"

    prompt = build_de_ai_story_ledger_prompt(source)

    assert "核心故事账本" in prompt
    assert "18至32个编号拍点" in prompt
    assert "相邻微动作合并" in prompt
    assert "绝不能因为原文写得具体就全部标成[硬]" in prompt


def test_chunked_redraft_prompts_cover_ordered_ledger_without_source_prose():
    source = (
        "周砚在7月12日带3封信到A17仓库。陈禾检查第三封信。"
        "停电后，周砚用收音机看见门外有2个人。两人从南门离开。"
        "回家后，他发现A17-07钥匙，而此前只见过01到06号柜。"
    )
    ledger = "\n".join([
        "叙事约束：第三人称限知；周砚视角；过去时。",
        "【开场】",
        "01 [硬] 7月12日；周砚；3封信→A17仓库。",
        "02 [硬] 陈禾检查第三封信。",
        "【停电】",
        "03 [硬] 停电；周砚用收音机确认门外有2个人。",
        "04 [硬] 两人从南门离开。",
        "【结尾锁定】",
        "05 [硬] 周砚回家→发现A17-07钥匙；此前只见过01到06号柜。",
    ])

    prompts = build_de_ai_chunked_rewrite_prompts(source, ledger, chunk_count=3)

    assert len(prompts) == 3
    assert all(source not in prompt for prompt in prompts)
    assert all("只输出本段正文" in prompt for prompt in prompts)
    assert all("避免流水账与镜头链" in prompt for prompt in prompts)
    assert all("不能把账本每个箭头扩成一条完整句" in prompt for prompt in prompts)
    assert all("叙事约束：第三人称限知" in prompt for prompt in prompts)
    combined = "\n".join(prompts)
    assert combined.index("周砚；3封信") < combined.index("停电；周砚")
    assert combined.index("停电；周砚") < combined.index("A17-07钥匙")
    # Ledger event number 03 is formatting, not a source literal requirement.
    third_required = prompts[1].split("【本段必须原字出现的源文标记】", 1)[1].split("【本段账本拍点】", 1)[0]
    assert "03" not in third_required


def test_follow_up_chunk_prompts_take_diagnostics_from_candidate_but_literals_from_original():
    original = "7月12日，周砚把A17钥匙交给陈禾。" * 30
    previous_candidate = original.replace("把", "将") + "模型误加B99。"
    ledger = "\n".join([
        "叙事约束：第三人称限知；周砚视角。",
        "01 [硬] 7月12日；周砚；A17钥匙→陈禾。",
    ])

    prompts = build_de_ai_chunked_rewrite_prompts(
        previous_candidate,
        ledger,
        chunk_count=1,
        fidelity_source=original,
    )

    assert len(prompts) == 1
    required = prompts[0].split("【本段必须原字出现的源文标记】", 1)[1].split(
        "【本段账本拍点】",
        1,
    )[0]
    assert "7月" in required
    assert "12日" in required
    assert "A17" in required
    assert "B99" not in required


def test_fidelity_audit_prompt_maps_semantic_errors_to_candidate_chunks():
    source = "三天内若陈禾没有联系，周砚就把账页投进城南邮局三号信箱。"
    chunks = [
        "周砚收好账页。",
        "三天内若陈禾主动联系，他就把账页投进三号信箱。",
    ]

    prompt = build_de_ai_fidelity_audit_prompt(source, chunks)

    assert source in prompt
    assert "【候选片段 1】" in prompt
    assert "【候选片段 2】" in prompt
    assert "把条件正反" in prompt
    assert '"chunk":1' in prompt
    assert "不评价文风" in prompt
    assert "不得把省略重复复盘判为 missing" in prompt
    assert "总数与分项关系" in prompt
    assert "造成总量增加" in prompt
    assert "事件先后不能只核对‘两件事都出现了’" in prompt
    assert "原文 A 后 B" in prompt
    assert "必须以 order 判失败" in prompt


def test_chunk_repair_prompt_regenerates_whole_scene_from_ledger():
    chunk_prompt = "【本段账本拍点】\n01 [硬] 没有联系→把账页投进三号信箱。"
    issues = [{
        "chunk": 1,
        "kind": "contradiction",
        "detail": "候选把‘没有联系’写成了‘主动联系’。",
    }]

    prompt = build_de_ai_chunk_repair_prompt(chunk_prompt, issues)

    assert chunk_prompt in prompt
    assert issues[0]["detail"] in prompt
    assert "重新依据本段账本写出完整片段" in prompt
    assert "不要对上一稿打补丁" in prompt
    assert "省略不等于事实上的否定" in prompt


def test_chunk_repair_prompt_preserves_valid_prose_when_candidate_is_available():
    prompt = build_de_ai_chunk_repair_prompt(
        "【本段账本拍点】\n01 [硬] 周砚取出钥匙。",
        [{"detail": "取钥匙的人被写成了陈禾。"}],
        previous_candidate="陈禾取出钥匙，递给周砚。其余现场叙述保持完整。",
    )

    assert "【待校正候选】" in prompt
    assert "陈禾取出钥匙" in prompt
    assert "只修正上面列出的事实错误" in prompt
    assert "其余已正确的叙述" in prompt
    assert "不能只给补丁" in prompt


def test_fidelity_audit_parser_accepts_fenced_json_and_rejects_inconsistent_shape():
    passed = parse_de_ai_fidelity_audit(
        '```json\n{"passed":true,"issues":[]}\n```',
        chunk_count=2,
    )
    failed = parse_de_ai_fidelity_audit(
        '{"passed":false,"issues":[{"chunk":2,"kind":"contradiction",'
        '"detail":"条件写反"}]}',
        chunk_count=2,
    )
    inconsistent = parse_de_ai_fidelity_audit(
        '{"passed":true,"issues":[{"chunk":3,"kind":"other","detail":"x"}]}',
        chunk_count=2,
    )

    assert passed == {"valid": True, "passed": True, "issues": []}
    assert failed["valid"] is True
    assert failed["passed"] is False
    assert failed["issues"][0]["chunk"] == 2
    assert inconsistent["valid"] is False


def test_style_audit_targets_structural_signals_and_maps_them_to_chunks():
    chunks = [
        "周砚开门、上楼、检查窗户，再逐项核对架上的货物。",
        "陈禾说过三天，北门外有两个人，第三封信又是饵。线索都对上了。",
    ]

    prompt = build_de_ai_style_audit_prompt(chunks)
    repair = build_de_ai_style_repair_prompt(
        "【本段账本拍点】\n05 [硬] 周砚发现A17-07钥匙。",
        [{"chunk": 2, "kind": "recap", "detail": "结尾成组复盘线索。"}],
    )

    assert "【候选片段 1】" in prompt
    assert "线索、条件或意义成组复盘" in prompt
    assert "执行日志" in prompt
    assert "场景坐标" in prompt
    assert "完整镜头链" in prompt
    assert "事实账本逐条翻成一句或一段" in prompt
    assert '"kind":"recap"' in prompt
    assert "结尾成组复盘线索" in repair
    assert "末尾停在账本最后一个现场动作" in repair


def test_detector_feedback_repair_uses_ledger_and_verified_boundaries_only():
    source = "7月12日20点41分，周砚带3封信走向A17仓库。"
    ledger = "01 [硬] 7月12日20点41分；周砚；3封信；A17仓库。"

    prompt = build_de_ai_detector_feedback_repair_prompt(
        source,
        ledger,
        left_context="陈禾收。",
        right_context="陈禾接过信。",
        verdict="suspected",
        pass_number=3,
        minimum_visible_characters=120,
    )

    assert source not in prompt
    assert ledger in prompt
    assert "第3次检测反馈修复" in prompt
    assert "场景坐标" in prompt
    assert "完整镜头脚本" in prompt
    assert "左侧已保留正文" in prompt
    assert "右侧已保留正文" in prompt
    assert "局部节奏参考" in prompt
    assert "7月12日" in prompt
    assert "本段目标为154至194个可见字符" in prompt
    assert "同一事实、动作或等待状态在本区段只落笔一次" in prompt


def test_detector_ledger_compression_drops_optional_and_ending_recap_lines():
    source = "周砚回家发现A17-07钥匙，此前只见过01至06号柜。"
    ledger = (
        "人物表：周砚。\n"
        "01 [可选] 屋内灯光昏暗。\n"
        "02 [硬] 周砚已知信息：三天内投三号信箱。\n"
        "03 [硬] 周砚发现A17-07钥匙。\n"
        "04 [硬] 此前只见过01至06号柜。\n"
        "结尾锁定：A17-07。"
    )

    prompt = build_de_ai_detector_ledger_compression_prompt(
        source,
        ledger,
        is_ending=True,
        preserved_context="三天内投三号信箱。",
    )

    assert "灯光昏暗" not in prompt
    assert "三天内投三号信箱" not in prompt
    assert "结尾锁定：A17-07" not in prompt
    assert "周砚发现A17-07钥匙" in prompt
    assert "只见过01至06号柜" in prompt
    required = prompt.split("【必须原字保留的标记】", 1)[1].split(
        "【待压缩详细账本】",
        1,
    )[0]
    assert "三天" not in required
    assert "三号" not in required
    assert "不写小说正文" in prompt


def test_detector_ledger_compression_promotes_consequential_repeated_observation():
    prompt = build_de_ai_detector_ledger_compression_prompt(
        "两人等了几分钟，陈禾数次查看北门和窗户，随后仓库断电。",
        (
            "01 [可选] 几分钟内两人沉默；陈禾数次看向北门，并反复查看窗户。\n"
            "02 [硬] 随后仓库断电。"
        ),
    )

    assert "01 [硬] 几分钟内两人沉默" in prompt
    assert "数次看向北门" in prompt
    assert "反复查看窗户" in prompt


def test_style_repair_filters_recap_only_ledger_beats_but_keeps_final_discovery():
    chunk_prompt = (
        "本段目标为395至463个可见字符；只写结尾。\n\n"
        "【本段必须原字出现的源文标记】\nA17、三天、三号、A17-07、01、06\n\n"
        "【本段账本拍点】\n"
        "30 [硬] 周砚回顾已知线索：三天、三号信箱、门外两人。\n"
        "31 [硬] 周砚举起钥匙，发现刻痕A17-07。\n"
        "结尾锁定：[硬] 周砚确认A17-07；悬念依赖：此前只见01至06。"
    )

    repair = build_de_ai_style_repair_prompt(
        chunk_prompt,
        [{"chunk": 1, "kind": "style:recap", "detail": "集中复盘线索"}],
    )

    assert "30 [硬]" not in repair
    assert "三号信箱" not in repair
    assert "31 [硬] 周砚举起钥匙" in repair
    assert "结尾锁定" not in repair
    assert "悬念依赖" not in repair
    assert "A17、A17-07" in repair
    assert "A17、三天、三号" not in repair
    assert "本段目标为257至347个可见字符" in repair
    assert "系统已从本段输入中过滤2条纯复盘账本行" in repair


def test_detector_staged_repair_compensates_writer_undershoot_without_shrinking():
    repair = build_de_ai_style_repair_prompt(
        "本段目标为1000至1100个可见字符；只输出正文。\n"
        "【本段事实账本】\n01 [硬] 周砚关灯后听见门响。",
        [{"chunk": 1, "kind": "staged", "detail": "悬念被铺成完整分镜。"}],
        allow_target_shrink=False,
    )

    assert "本段目标为1180至1298个可见字符" in repair
    assert "仅用于抵消模型常见的篇幅不足" in repair
    assert "不能靠复盘、重复步骤、解释或新增事实凑字" in repair
    assert "账本只是核对表，不是句子或段落大纲" in repair
    assert "短对白不要单独成段" in repair


def test_detector_feedback_repair_treats_ledger_as_audit_not_storyboard():
    prompt = build_de_ai_detector_feedback_repair_prompt(
        "周砚关灯后听见门响。",
        "01 [硬] 周砚关灯。\n02 [硬] 门外响了一声。",
        verdict="warning",
    )

    assert "事实账本只用于核对，不是逐条展开的句子或段落大纲" in prompt
    assert "不得一条[硬]对应一句或一段" in prompt
    assert "同一个现场动作或一轮被打断的对白" in prompt
    assert "本区段最多使用3个自然段" in prompt
    assert "段落数必须明显少于账本拍点数" in prompt


def test_detector_feedback_paragraph_cap_scales_but_stays_bounded():
    short_prompt = build_de_ai_detector_feedback_repair_prompt(
        "甲" * 450,
        "01 [硬] 甲。",
    )
    long_prompt = build_de_ai_detector_feedback_repair_prompt(
        "乙" * 1800,
        "01 [硬] 乙。",
    )

    assert "本区段最多使用3个自然段" in short_prompt
    assert "本区段最多使用7个自然段" in long_prompt


def test_style_audit_parser_rejects_unknown_kinds_and_accepts_bounded_issue():
    failed = parse_de_ai_style_audit(
        '{"passed":false,"issues":[{"chunk":2,"kind":"recap",'
        '"detail":"结尾重复解释已经出现的线索"}]}',
        chunk_count=2,
    )
    malformed = parse_de_ai_style_audit(
        '{"passed":false,"issues":[{"chunk":1,"kind":"adjective",'
        '"detail":"形容词较多"}]}',
        chunk_count=2,
    )
    staged = parse_de_ai_style_audit(
        '{"passed":false,"issues":[{"chunk":1,"kind":"staged",'
        '"detail":"悬念被铺成完整分镜"}]}',
        chunk_count=2,
    )

    assert failed["valid"] is True
    assert failed["passed"] is False
    assert failed["issues"][0]["kind"] == "recap"
    assert staged["valid"] is True
    assert staged["issues"][0]["kind"] == "staged"
    assert malformed["valid"] is False


def test_chunk_target_parser_and_visible_character_counter_share_revision_units():
    prompt = "本段目标为 320 至 410 个可见字符；只输出正文。"

    assert parse_de_ai_chunk_target(prompt) == (320, 410)
    assert parse_de_ai_chunk_target("没有篇幅目标") is None
    assert count_de_ai_visible_characters("A17 仓库，三号。\n") == 7


def test_candidate_preserving_length_repair_expands_only_ledger_backed_detail():
    prompt = build_de_ai_chunk_repair_prompt(
        "本段目标为280至340个可见字符。\n【本段账本拍点】\n01 [硬] 周砚拧动钥匙。",
        [{"kind": "length", "detail": "本段须至少达到304个可见字符。"}],
        repair_attempt=4,
        previous_candidate="周砚把钥匙插进去，拧了一下。",
    )

    assert "已通过故事事实审计，但篇幅略短" in prompt
    assert "【待补足候选】" in prompt
    assert "周砚把钥匙插进去，拧了一下。" in prompt
    assert "不得新增事件、解释、感官或背景" in prompt


def test_insertion_only_expansion_prompt_locks_existing_candidate_characters():
    prompt = build_de_ai_candidate_preserving_expansion_prompt(
        "周砚把钥匙插进去，拧了一下。",
        "01 [硬] 钥匙插入点火孔；首次点火失败。",
        minimum_visible_characters=32,
        maximum_visible_characters=56,
        required_insertions=["7月", "12日"],
    )

    assert "达到32至56个可见字符" in prompt
    assert "每一个非空白字符都必须原样、同序保留" in prompt
    assert "【不可删除候选】\n周砚把钥匙插进去，拧了一下。" in prompt
    assert "必须补回这些源文事实标记：7月、12日" in prompt


def test_detector_feedback_prompt_forbids_ledger_state_narration():
    prompt = build_de_ai_detector_feedback_repair_prompt(
        "周砚接过纸卷，去配电箱后取钥匙。",
        "01 [硬] 纸卷由陈禾递给周砚。\n02 [硬] 周砚取出叉车钥匙。",
        verdict="suspected",
    )

    assert "物件归属只通过拿取、递交、使用或随身动作自然呈现" in prompt
    assert "仍由某人拿着" in prompt
    assert "尚未取出" in prompt
    assert "不以日期、钟点和剩余分钟组成开场报时" in prompt
    assert "不得把日期、钟点、倒计时、地点、信封属性和敲门节奏连续塞进一两句" in prompt
    assert "无署名、无邮票和收件字样" in prompt


def test_revision_guard_accepts_structural_rewrite_that_preserves_story_facts():
    source = (
        "周砚在7月12日抵达A17仓库。他带着3封信，约定21点前交给陈禾。\n\n"
        "“少一封都不行。”陈禾说。\n\n"
        "周砚点头，把信压在外套里面。他们从仓库北门离开。"
    )
    rewritten = (
        "7月12日，周砚到了A17仓库。3封信压在外套里，21点前必须交到陈禾手上。\n\n"
        "“少一封都不行。”陈禾说。\n\n"
        "周砚点了头。两个人随后从仓库北门出去。"
    )

    result = assess_de_ai_revision(source, rewritten)

    assert result["accepted"] is True
    assert result["missing_protected_tokens"] == []
    assert 0.68 <= result["length_ratio"] <= 1.35


def test_revision_guard_rejects_truncation_and_missing_fact_tokens():
    source = (
        "周砚在7月12日抵达A17仓库。他带着3封信，约定21点前交给陈禾。"
        "门外停着一辆旧车，陈禾让他从北门离开。" * 6
    )
    rewritten = "周砚到了仓库，很快又离开了。"

    result = assess_de_ai_revision(source, rewritten)

    assert result["accepted"] is False
    assert {item["code"] for item in result["issues"]} >= {
        "excessive_shrinkage",
        "missing_fact_tokens",
    }
    assert {"7月", "12日", "A17", "3封", "21点"}.issubset(
        set(result["missing_protected_tokens"])
    )


def test_revision_guard_supports_feedback_specific_shrinkage_floor():
    source = "甲" * 100
    rewritten = "乙" * 89

    standard = assess_de_ai_revision(source, rewritten)
    feedback = assess_de_ai_revision(
        source,
        rewritten,
        min_length_ratio=0.88,
    )

    assert standard["accepted"] is False
    assert feedback["accepted"] is True


def test_revision_guard_allows_detector_feedback_to_lock_human_spans():
    source = "甲" * 900 + "原始警告段" * 20
    rewritten = "甲" * 900 + "定向重写段" * 20

    standard = assess_de_ai_revision(source, rewritten)
    feedback = assess_de_ai_revision(
        source,
        rewritten,
        require_substantial_revision=False,
    )

    assert standard["accepted"] is False
    assert "insufficient_revision" in {
        item["code"] for item in standard["issues"]
    }
    assert feedback["accepted"] is True


def test_revision_guard_keeps_full_chapter_near_two_thousand_characters():
    source = "甲" * 2_100
    too_short = "乙" * 1_999
    long_enough = "乙" * 2_000

    rejected = assess_de_ai_revision(source, too_short)
    accepted = assess_de_ai_revision(source, long_enough)

    assert "chapter_word_count_floor" in {
        item["code"] for item in rejected["issues"]
    }
    assert rejected["minimum_platform_characters"] == 2_000
    assert accepted["accepted"] is True


def test_revision_guard_protects_chinese_number_facts():
    source = (
        "陈禾说，三天内若没有消息，就把账页交到城南邮局三号信箱。"
        "周砚把这句话重复了一遍，随后收起账页。"
    )
    rewritten = (
        "陈禾让周砚把账页收好；要是一直没有消息，就交到城南邮局。"
        "周砚复述过要求，才把账页收起来。"
    )

    result = assess_de_ai_revision(source, rewritten)

    assert result["accepted"] is False
    assert {"三天", "三号"}.issubset(set(result["missing_protected_tokens"]))


def test_revision_guard_rejects_model_wrapper_and_large_dialogue_loss():
    source = "“钥匙呢？”老周问。\n\n“桌上。”小米说。\n\n“没有。”\n\n“那就在你口袋里。”"
    rewritten = "以下是修改后的正文：老周和小米谈起钥匙，最后发现钥匙可能在口袋里。"

    result = assess_de_ai_revision(source, rewritten)

    codes = {item["code"] for item in result["issues"]}
    assert "output_wrapper" in codes
    assert "dialogue_loss" in codes


def test_revision_guard_rejects_agent_tool_chatter_inside_prose():
    source = "周砚进了仓库。陈禾把账页交给他。两人从南门离开。" * 8
    rewritten = (
        "周砚进了仓库。陈禾正要把账页交给他。"
        "I cannot read the task file due to permission restrictions."
        "两个人随后从南门离开。"
    ) * 5

    result = assess_de_ai_revision(source, rewritten)

    assert "agent_chatter" in {item["code"] for item in result["issues"]}


def test_revision_guard_rejects_long_near_copy_that_only_changes_one_adverb():
    source = ("周砚沿着仓库北墙往前走，听见卷帘门后有人说话。" * 35)
    rewritten = source.replace("往前走", "走过去", 1)

    result = assess_de_ai_revision(source, rewritten)

    assert result["accepted"] is False
    assert result["source_similarity"] > 0.9
    assert "insufficient_revision" in {
        item["code"] for item in result["issues"]
    }
