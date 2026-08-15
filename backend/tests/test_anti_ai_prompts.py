"""Regression tests for input-aware de-AI revision prompts."""

from app.prompts.anti_ai_prompts import (
    apply_de_ai_macro_ledger,
    build_de_ai_candidate_preserving_expansion_prompt,
    analyze_de_ai_fingerprints,
    build_de_ai_chunk_repair_prompt,
    build_de_ai_chunked_rewrite_prompts,
    build_de_ai_detector_feedback_repair_prompt,
    build_de_ai_detector_ledger_compression_prompt,
    build_de_ai_fidelity_audit_prompt,
    build_de_ai_macro_ledger_compression_prompt,
    build_de_ai_macro_ledger_fidelity_audit_prompt,
    build_de_ai_macro_ledger_retry_feedback,
    build_de_ai_macro_ledger_structure_audit_prompt,
    build_de_ai_rewrite_from_ledger_prompt,
    build_de_ai_rewrite_prompt,
    build_de_ai_story_ledger_prompt,
    build_de_ai_style_audit_prompt,
    build_de_ai_style_repair_prompt,
    normalize_de_ai_macro_ledger,
    validate_de_ai_macro_ledger,
)
from app.services.de_ai_validation import (
    assess_de_ai_revision,
    count_de_ai_visible_characters,
    de_ai_chunk_length_rank,
    de_ai_style_issue_rank,
    de_ai_style_issue_novelty,
    parse_de_ai_chunk_target,
    parse_de_ai_fidelity_audit,
    parse_de_ai_style_audit,
)


def test_chunk_length_rank_keeps_best_attempt_instead_of_last_attempt():
    target = (400, 500)

    assert de_ai_chunk_length_rank(430, target) < de_ai_chunk_length_rank(250, target)
    assert de_ai_chunk_length_rank(390, target) < de_ai_chunk_length_rank(360, target)
    assert de_ai_chunk_length_rank(510, target) < de_ai_chunk_length_rank(540, target)


def test_style_issue_novelty_penalizes_problem_migration():
    history = [
        {"chunk": 2, "kind": "staged"},
        {"chunk": 4, "kind": "checklist"},
    ]

    assert de_ai_style_issue_novelty(
        [{"chunk": 2, "kind": "staged"}],
        history,
    ) == (0, 0)
    assert de_ai_style_issue_novelty(
        [{"chunk": 5, "kind": "recap"}],
        history,
    ) == (1, 1)


def test_style_issue_rank_prefers_fewer_defects_before_problem_novelty():
    history = [
        {"chunk": 1, "kind": "staged"},
        {"chunk": 2, "kind": "staged"},
        {"chunk": 2, "kind": "checklist"},
    ]

    retained = de_ai_style_issue_rank(history, history)
    migrated = de_ai_style_issue_rank(
        [{"chunk": 1, "kind": "recap"}],
        history,
    )

    assert migrated < retained
    assert retained == (3, 7, 0, 0)
    assert migrated == (1, 3, 1, 1)


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


def test_default_chunking_uses_macro_scenes_without_contrived_cadence():
    source = "周砚把仓库记录逐页核完，陈禾在门边等他。" * 105
    ledger = "\n".join(
        ["叙事约束：周砚视角；过去时。"]
        + [f"{index:02d} [硬] 第{index}项事实推动下一步行动。" for index in range(1, 13)]
    )

    prompts = build_de_ai_chunked_rewrite_prompts(source, ledger)

    assert len(prompts) in {2, 3}
    assert all("突然留一行短句" not in prompt for prompt in prompts)
    assert all("两个不等长的段" not in prompt for prompt in prompts)
    assert "不为制造长短反差而单独留一句" in "\n".join(prompts)
    assert "不要先集中报时间、坐标和背景" in prompts[0]
    assert "不要在结尾回顾过程" in prompts[-1]


def test_long_scene_ledger_is_compressed_before_prose_generation():
    detailed = (
        "本段目标为1000至1100个可见字符；只输出正文。\n\n"
        "【不可变】\n"
        "- [硬]事实、人物、物件归属、对白意图、因果和先后全部写入，"
        "不新增账本没有的动作、感官、解释或背景。\n"
        "按拍点自然换段：有时一拍独立，有时三四拍连在一个段里，不固定每片段的段数。\n\n"
        "【本段必须原字出现的源文标记】\nA17、三天、A17-07\n\n"
        "【本段账本拍点】\n"
        "01 [硬] 周砚进入A17。\n"
        "02 [硬] 陈禾检查信封。\n"
        "03 [硬] 陈禾要求周砚若三天内未收到联系就投递账页。\n"
        "04 [硬] 灯灭后门外出现两人。\n"
        "05 [硬] 两人撤离，周砚回家发现A17-07钥匙。"
    )

    compression = build_de_ai_macro_ledger_compression_prompt(detailed)
    compact_ledger = (
        "01 [硬] 局面：周砚进入A17，陈禾发现信封异常并设下三天投递条件。\n"
        "02 [硬] 转折：灯灭后门外出现两人。\n"
        "03 [硬] 结果：两人撤离，周砚回家发现A17-07钥匙。"
    )
    compacted = apply_de_ai_macro_ledger(detailed, compact_ledger)
    compacted_with_appendix = apply_de_ai_macro_ledger(
        detailed,
        compact_ledger,
        include_fact_appendix=True,
    )

    assert "不得多于3个" in compression
    assert "不超过260个可见字符" in compression
    assert "一条事实对应一句或一段" in compression
    assert "单个单元不得连续罗列三个以上" in compression
    assert "每行只写一次核心变化，不用分号堆步骤" in compression
    assert "不得省略唯一促成关键结果的因果方法或出口" in compression
    assert "不得省略承载后续条件的纸条、信件等物件交接" in compression
    assert "A17、三天、A17-07" in compression
    assert "【本段宏观叙事单元（只定事实边界，不是逐句大纲）】" in compacted
    assert "【后置事实校对附录（不决定正文取舍）】" not in compacted
    assert "02 [硬] 陈禾检查信封。" not in compacted
    assert "宏观单元只定事实边界，不对应句子或段落" in compacted
    assert "生成后会另行依据不可变原文做事实审计" in compacted
    assert "[硬]事实、人物、物件归属、对白意图、因果和先后全部写入" not in compacted
    assert "不得自行补回压缩掉的过门、完整分镜链或执行清单" in compacted
    assert "【后置事实校对附录（不决定正文取舍）】" in compacted_with_appendix
    assert "02 [硬] 陈禾检查信封。" in compacted_with_appendix
    assert "后置事实附录只用于校对主体" in compacted_with_appendix
    assert (
        "不得为了覆盖附录而补回过门、完整分镜链或执行清单"
        in compacted_with_appendix
    )
    assert "本段目标为1000至1100个可见字符" in compacted
    assert validate_de_ai_macro_ledger(detailed, compact_ledger)[0] is True
    assert validate_de_ai_macro_ledger(
        detailed,
        "01 [硬] 周砚进入A17，陈禾检查信封。",
    ) == (False, ["三天", "A17-07"])
    assert validate_de_ai_macro_ledger(
        detailed,
        "01 [硬] 局面：周砚进入A17，陈禾检查信封；约定期限为三天。\n"
        "02 [硬] 结果：她回家发现A17-07钥匙。",
    )[0] is False
    assert validate_de_ai_macro_ledger(
        detailed,
        "01 [硬] 周砚按暗号进入A17，陈禾检查信封并安排他戒备；三天内投递。\n"
        "02 [硬] 门外伏击者撤离，周砚回家发现A17-07钥匙。",
    )[0] is False
    assert validate_de_ai_macro_ledger(
        detailed,
        "01 [硬] 周砚进入A17；陈禾检查信封；三天内投递。\n"
        "02 [硬] 门外出现两人；两人撤离；周砚发现A17-07钥匙。",
    )[0] is False
    assert validate_de_ai_macro_ledger(
        detailed,
        "01 [硬] 周砚锁车、敲门、扫视、看向A17后检查门窗。\n"
        "02 [硬] 陈禾调角度反光后上楼开门，三天后发现A17-07钥匙。",
    )[0] is False
    overlong = (
        "01 [硬] A17、三天、A17-07；" + "周砚核对账页。" * 70
    )
    assert validate_de_ai_macro_ledger(detailed, overlong)[0] is False


def test_macro_ledger_normalizes_punctuation_and_retries_bad_gender_pronouns():
    prompt = (
        "【本段必须原字出现的源文标记】\nA17\n"
        "【本段账本拍点】\n"
        "01 [硬] 陈禾把纸卷交给周砚。\n"
        "02 [硬] 周砚与陈禾从南门离开A17。"
    )
    raw = (
        "01 [硬] 陈禾把纸卷交给周砚；两人决定离开A17。\n"
        "02 [硬] 她与周砚从南门撤离。"
    )

    normalized = normalize_de_ai_macro_ledger(raw)
    _, missing = validate_de_ai_macro_ledger(prompt, normalized)
    feedback = build_de_ai_macro_ledger_retry_feedback(
        prompt,
        normalized,
        missing,
    )

    assert "；" not in normalized
    assert ";" not in normalized
    assert "删除详细账本没有的人称代词：她" in feedback
    assert "重复人物姓名，不推断性别" in feedback
    assert "只修正这些问题" in feedback


def test_macro_ledger_fidelity_audit_targets_role_order_and_epistemic_drift():
    detailed = (
        "本段目标为1000至1100个可见字符；只输出正文。\n\n"
        "【本段账本拍点】\n"
        "01 [硬] 陈禾只让周砚发动叉车。\n"
        "02 [硬] 周砚自行踩油门盖过北门动静。\n"
        "03 [硬] 陈禾问门外是否还有人，周砚没有回答。"
    )
    compact = (
        "01 [硬] 陈禾命令周砚发动叉车并踩油门掩护撤离；"
        "两人确认门外还有人。"
    )

    prompt = build_de_ai_macro_ledger_fidelity_audit_prompt(detailed, compact)

    assert "把人物自行采取的动作压成他人的命令" in prompt
    assert "疑问、猜测、可能" in prompt
    assert "具体方法或路线被省略" in prompt
    assert "促成关键结果的唯一方法或指定出口" in prompt
    assert "纸条、信件、账页等承载条件的交接" in prompt
    assert "把‘只见过’升级成‘确定不存在’" in prompt
    assert "宏观账本仍明确写出的事实须核对主体" in prompt
    assert "陈禾只让周砚发动叉车" in prompt
    assert "周砚自行踩油门" in prompt
    assert compact in prompt
    assert '"kind":"role|order|contradiction|added|missing"' in prompt


def test_macro_ledger_structure_audit_detects_cross_line_shot_lists():
    compact = (
        "01 [硬] 灯灭后传来异响，卷帘门被抬起。\n"
        "02 [硬] 周砚寻找反光物并调整角度，看见两个人。\n"
        "03 [硬] 周砚报告人数，陈禾解释假信。"
    )

    prompt = build_de_ai_macro_ledger_structure_audit_prompt(compact)

    assert "五个及以上相邻小拍即判失败" in prompt
    assert "四项及以上即判失败" in prompt
    assert "要看跨行累计的微步骤" in prompt
    assert "唯一促成关键结果的因果方法" in prompt
    assert "属于核心事实，不按微步骤计数" in prompt
    assert compact in prompt
    assert '"kind":"staged|checklist"' in prompt


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


def test_follow_up_chunking_keeps_original_macro_scene_count():
    original = "周砚把仓库记录逐页核完，陈禾在门边等他。" * 90
    expanded_candidate = original + ("两人继续核对已有记录。" * 80)
    ledger = "\n".join(
        ["叙事约束：周砚视角；过去时。"]
        + [f"{index:02d} [硬] 第{index}项事实推动下一步行动。" for index in range(1, 13)]
    )

    first_round = build_de_ai_chunked_rewrite_prompts(original, ledger)
    follow_up = build_de_ai_chunked_rewrite_prompts(
        expanded_candidate,
        ledger,
        fidelity_source=original,
    )

    assert len(first_round) == 2
    assert len(follow_up) == len(first_round)


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
    assert "今晚不急着走吧" in prompt
    assert "今晚急着离开吗" in prompt
    assert "只有回答分支" in prompt
    assert "给我信的人" in prompt
    assert "保留该称谓不等于切换叙事人称" in prompt


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
    assert "未解释跳变" in prompt
    assert "不得为消除表面矛盾擅自补写交接" in prompt


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


def test_style_repair_uses_actual_chapter_shortfall_instead_of_blanket_growth():
    prompt = build_de_ai_style_repair_prompt(
        "本段目标为900至1050个可见字符。\n【本段事实账本】\n01 [硬] 灯灭。",
        [{"chunk": 1, "kind": "staged", "detail": "逐拍分镜"}],
        allow_target_shrink=False,
        minimum_target_characters=960,
    )

    assert "本段目标为960至1050个可见字符" in prompt
    assert "按整章实际缺口校准" in prompt
    assert "增加到1062" not in prompt

    no_shortfall = build_de_ai_style_repair_prompt(
        "本段目标为900至1050个可见字符。\n【本段事实账本】\n01 [硬] 灯灭。",
        [{"chunk": 1, "kind": "staged", "detail": "逐拍分镜"}],
        allow_target_shrink=False,
        minimum_target_characters=0,
    )

    assert "本段目标为900至1050个可见字符" in no_shortfall
    assert "按整章实际缺口校准" in no_shortfall


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
    assert "从触发到结果合计最多两句" in repair
    assert "至多一个不可替代的因果方法" in repair


def test_detector_checklist_repair_compensates_writer_undershoot_without_shrinking():
    repair = build_de_ai_style_repair_prompt(
        "本段目标为1000至1100个可见字符；只输出正文。\n"
        "【本段事实账本】\n01 [硬] 周砚关灯后听见门响。",
        [{"chunk": 1, "kind": "checklist", "detail": "动作被写成逐项执行清单。"}],
        allow_target_shrink=False,
    )

    assert "本段目标为1180至1298个可见字符" in repair
    assert "不能靠复盘、重复步骤、解释或新增事实凑字" in repair
    assert "只允许保留直接造成新局面的至多一个因果动作" in repair
    assert "其余步骤不得在正文出现" in repair


def test_style_repair_withholds_rejected_candidate_to_break_structure_anchoring():
    repair = build_de_ai_style_repair_prompt(
        "本段目标为400至480个可见字符。\n【本段事实账本】\n01 [硬] 灯灭。",
        [{"chunk": 1, "kind": "staged", "detail": "逐拍铺开。"}],
        previous_candidate="灯先闪了两下。接着彻底熄灭。",
    )

    assert "【结构重生输入隔离】" in repair
    assert "灯先闪了两下。接着彻底熄灭。" not in repair
    assert "只依据上方事实账本和审计问题重新落笔" in repair
    assert "不得猜回被移除的常规步骤" in repair
    assert "从触发到结果合计最多两句" in repair


def test_style_repair_hides_detailed_ledger_until_a_fact_issue_requires_it():
    macro_prompt = (
        "本段目标为900至1050个可见字符。\n"
        "【本段宏观叙事单元（只定事实边界，不是逐句大纲）】\n"
        "01 [硬] 周砚制造声响，两人从南门撤离。"
    )
    detailed_prompt = (
        "本段目标为900至1050个可见字符。\n"
        "【本段账本拍点】\n"
        "01 [硬] 叉车钥匙藏在配电箱后，由周砚取出。\n"
        "02 [硬] 南门由液压杆支撑，陈禾压手柄使门升起。\n"
        "03 [可选] 仓库里有一股旧机油味。"
    )

    style_repair = build_de_ai_style_repair_prompt(
        macro_prompt,
        [{"chunk": 1, "kind": "staged", "detail": "撤离过程逐拍铺陈。"}],
        previous_candidate="周砚一步一步走向配电箱。",
        fidelity_chunk_prompt=detailed_prompt,
    )

    assert "【后置事实校对附录（不得逐条展开）】" not in style_repair
    assert "叉车钥匙藏在配电箱后，由周砚取出" not in style_repair
    assert "南门由液压杆支撑" not in style_repair
    assert "周砚一步一步走向配电箱" not in style_repair

    fact_repair = build_de_ai_style_repair_prompt(
        macro_prompt,
        [{"chunk": 1, "kind": "missing", "detail": "遗漏叉车钥匙的归属。"}],
        fidelity_chunk_prompt=detailed_prompt,
    )

    assert "【后置事实校对附录（不得逐条展开）】" in fact_repair
    assert "宏观叙事单元决定正文的取舍和颗粒度" in fact_repair
    assert "叉车钥匙藏在配电箱后，由周砚取出" in fact_repair
    assert "南门由液压杆支撑" in fact_repair
    assert "旧机油味" not in fact_repair
    assert "严禁按附录编号逐句、逐段展开" in fact_repair


def test_style_repair_does_not_duplicate_existing_fact_appendix():
    macro_prompt = (
        "本段目标为900至1050个可见字符。\n"
        "【本段宏观叙事单元（只定事实边界，不是逐句大纲）】\n"
        "01 [硬] 两人离开A17。\n\n"
        "【后置事实校对附录（不决定正文取舍）】\n"
        "02 [硬] 周砚用叉车声掩护，陈禾开南门。"
    )
    detailed_prompt = (
        "【本段账本拍点】\n"
        "02 [硬] 周砚用叉车声掩护，陈禾开南门。"
    )

    repair = build_de_ai_style_repair_prompt(
        macro_prompt,
        [{"chunk": 1, "kind": "checklist", "detail": "撤离步骤逐项写完。"}],
        fidelity_chunk_prompt=detailed_prompt,
    )

    assert repair.count("【后置事实校对附录（不决定正文取舍）】") == 1
    assert "【后置事实校对附录（不得逐条展开）】" not in repair


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
