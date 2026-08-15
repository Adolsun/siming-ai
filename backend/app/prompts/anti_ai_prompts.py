"""Systematic AI-flavor detection and removal.

The public constants in this module are also used by project style settings, so
the rewrite prompt deliberately treats them as *diagnostic signals* instead of
blind replacement rules.  Mechanical synonym swaps tend to make long-form
fiction more uniform, which is both worse prose and a strong machine-writing
signal in its own right.
"""

from __future__ import annotations

import re
from collections import Counter
from statistics import mean, pstdev
from typing import Any

# ---------------------------------------------------------------------------
# TIER 1 BANNED WORDS — replace immediately when found
# ---------------------------------------------------------------------------
TIER1_BANNED_WORDS = {
    "modal":     ["仿佛", "犹如", "宛若", "一丝", "一抹", "些许", "几分", "隐约"],
    "action":    ["深吸一口气", "缓缓", "不禁", "微微", "轻轻", "淡淡"],
    "expression": ["眼中闪过", "嘴角勾起", "眉头微皱", "眉眼低垂", "瞳孔微缩"],
    "psych":     ["心中一动", "心头一震", "心下了然", "心中暗道", "心底泛起", "不由得"],
    "judgment":  ["不容置疑", "不易察觉", "显而易见", "毫无疑问", "不可否认"],
    "describe":  ["坚定", "闪烁着光芒", "狡黠", "深邃", "凛冽"],
    "transition": ["不由自主", "情不自禁", "自然而然"],
    "vague":     ["命运", "宿命", "注定", "潮水般", "如闪电般", "仿佛春风"],
}

# ---------------------------------------------------------------------------
# TIER 2 CONTEXT-SENSITIVE — replace only when overused
# ---------------------------------------------------------------------------
TIER2_THRESHOLD_WORDS = [
    "突然", "好像", "瞬间", "于是乎", "与此同时", "从而", "因而", "诚然",
]

# ---------------------------------------------------------------------------
# FORBIDDEN SENTENCE TEMPLATES
# ---------------------------------------------------------------------------
FORBIDDEN_SENTENCE_TEMPLATES = [
    ("「…，带着…」万能状语", "他说，带着一丝无奈"),
    ("陈词滥调/万能比喻", "像刀子一样锋利"),
    ("过度文艺声音描写", "他的声音很轻，却像…"),
    ("文言腔残留", "仿佛能…一般"),
    ("公式化对话标签", "好的，他说道（高频时）"),
    ("「他/她感到…」告知句式", "她感到一丝失落"),
    ("「他/她意识到…」直接告知", "他意识到事情不对"),
    ("「眼中闪过一丝XX」模板", "眼中闪过一丝悲伤"),
    ("「嘴角勾起一抹XX」模板", "嘴角勾起一抹冷笑"),
    ("「心中涌起一股XX」模板", "心中涌起一股暖流"),
]

# ---------------------------------------------------------------------------
# TIER 3 SENTENCE-LEVEL STRUCTURAL PATTERNS — ban the pattern, not the words
# ---------------------------------------------------------------------------
TIER3_SENTENCE_PATTERNS = [
    "不是……是……",
    "不是……而是……",
    "不是……却是……",
    "与其说……不如说……",
    "在……中……",
    "在……时……",
    "随着……",
    "只见……",
    "只听得……",
    "忍不住……",
    "这一切都说明……",
    "从那天起……",
    "此后……",
    "另一方面……",
    "显得很……",
    "他的眼中……",
    "她的心里……",
    "一种……的感觉",
    "令人……",
    "让人……",
    "充满了",
    "充斥着",
    "默默地",
    "静静地",
    "其实",
    "总之",
    "无论如何",
    "毋庸置疑",
    "某种程度上",
    "某种意义上",
    "由此可见",
    "总而言之",
    "值得注意的是",
    "不难发现",
]

# ---------------------------------------------------------------------------
# CHAPTER-END SUMMARY DETECTION — AI fingerprint patterns
# ---------------------------------------------------------------------------
CHAPTER_END_BAN_PATTERNS = [
    # Summary insight
    "他终于明白了", "她终于懂了", "他终于意识到", "她这才明白",
    "这一刻，他终于", "那一刻，她终于",
    # Grandeur升华
    "这一夜，注定无人入眠", "这一天，改变了一切",
    "从此，一切都不同了", "他的人生翻开了新的一页",
    # Philosophical
    "人生就是这样", "命运总是如此", "或许这就是",
    "生活教会了他", "时间会让你明白",
    # Preview预告
    "他不知道的是，更大的", "他不知道，等待他的将是",
    "他不知道，这一切才刚刚开始",
    "他不知道，更大的风暴即将来临",
]

# ---------------------------------------------------------------------------
# STACKED-WRITING DETECTION (堆叠式写作)
# ---------------------------------------------------------------------------
STACKED_WRITING_RULE = (
    "【堆叠式写作检测 — 同一瞬间被拆成三段】\n"
    "AI最常见的写作痕迹：先写概括动作 -> 再写感知细节 -> 再写身体反应，"
    "三段说的是同一个瞬间的事。\n"
    "检测特征：\n"
    "- 「发生层→感知层→反应层」按顺序分段出现\n"
    "- 同一动作被掰开写了三遍\n"
    "- 每一维度独立成段，而不是织入同一段正文\n\n"
    "正确做法：发生、感知、反应三个维度织入同一段连续正文：\n"
    "> 林父左手压着文书，右手拿笔往纸上落——笔尖一触纸面就偏了，"
    "从肘到腕止不住地抖，那一横斜着拖出去。\n"
    "处理原则：合并同一瞬间的重复描写，而非删除情绪细节。"
)

# ---------------------------------------------------------------------------
# 7 AI WRITING PATTERNS
# ---------------------------------------------------------------------------
AI_PATTERN_1_HIGH_FREQ_WORDS = (
    "【模式1：AI高频词】\n"
    "禁用词：不禁、仿佛/宛如、映入眼帘、心中暗道、沉声道/淡淡地说、"
    "脸色一变、嘴角微扬、不由自主、只见/此时此刻、目光如炬\n"
    "替换原则：\n"
    "- 「不禁」-> 删掉\n"
    "- 「仿佛/宛如」-> 删掉或用具体描写\n"
    "- 「心中暗道」-> 用动作展示思考\n"
    "- 「沉声道/淡淡地说」-> 换成动作标签\n"
    "- 「脸色一变」-> 用具体表情/动作\n"
    "- 「嘴角微扬」-> 他笑了/他翘了下嘴\n"
    "- 「只见/此时此刻」-> 删掉\n"
)

AI_PATTERN_2_WEAK_ADVERBS = (
    "【模式2：弱化副词泛滥】\n"
    "阈值：每1000字超过3个 = AI签名\n"
    "重点监控：微微、淡淡、缓缓、轻轻\n"
    "替换：将副词修饰改为具体的身体动作或状态描写。\n"
)

AI_PATTERN_3_MEANING_INFLATION = (
    "【模式3：意义膨胀】\n"
    "- 「意义深远」-> 写具体后果\n"
    "- 「前所未有」-> 给出对比参照\n"
    "- 「可谓」-> 删掉\n"
    "- 「令人震惊」-> 写围观者的具体反应\n"
)

AI_PATTERN_4_UNIVERSAL_CONCLUSION = (
    "【模式4：万能结论】\n"
    "- 「未来可期」-> 用未解决的紧张感结尾\n"
    "- 「前途无量」-> 删\n"
    "- 「充满希望」-> 写具体的下一步动作\n"
    "- 「一切尽在不言中」-> 删，用沉默和动作替代\n"
)

AI_PATTERN_5_ESSAY_STRUCTURE = (
    "【模式5：论文体段落结构】\n"
    "小说中出现以下开头句 = AI入侵：\n"
    "「不难看出」「由此可见」「事实上」「综上所述」\n"
    "替换：直接叙事，不要对叙事内容做分析总结。\n"
)

AI_PATTERN_6_FORMAL_CONJUNCTIONS = (
    "【模式6：书面语连词泛滥】\n"
    "叙事中频繁出现「于是乎」「与此同时」「从而」「因而」「诚然」\n"
    "-> 口语化替代或直接删除。\n"
)

AI_PATTERN_7_TRIPLE_PARALLEL = (
    "【模式7：三连排比癖】\n"
    "AI喜欢把事情凑成三个——「有的…有的…有的…」「一边…一边…一边…」\n"
    "-> 砍到只剩最有力的一条。\n"
)

ALL_AI_PATTERNS = "\n\n".join([
    AI_PATTERN_1_HIGH_FREQ_WORDS,
    AI_PATTERN_2_WEAK_ADVERBS,
    AI_PATTERN_3_MEANING_INFLATION,
    AI_PATTERN_4_UNIVERSAL_CONCLUSION,
    AI_PATTERN_5_ESSAY_STRUCTURE,
    AI_PATTERN_6_FORMAL_CONJUNCTIONS,
    AI_PATTERN_7_TRIPLE_PARALLEL,
])

# ---------------------------------------------------------------------------
# SYSTEMATIC 3-PASS DE-AI METHOD
# ---------------------------------------------------------------------------
DE_AI_PASS_1 = (
    "【Pass 1：去泛化（Strip Generic）— 去掉80%的AI味】\n"
    "1. 抽象情绪总结句 -> 删或替换为具体动作\n"
    "2. 假深度句 -> 删\n"
    "3. 意义膨胀 -> 缩小到具体影响\n"
    "4. 空洞结论 -> 删\n"
    "5. 工整对比句式 -> 打散重写\n"
    "6. 装饰性形容词堆砌 -> 白描\n"
    "7. 过度使用「于是」「然而」「此刻」-> 删掉一半\n"
    "8. 所有角色说话方式一样 -> 区分语气\n"
    "原则：能删就删，不能删就用具体细节替换。"
)

DE_AI_PASS_2 = (
    "【Pass 2：去书面化（Cut Professional Diction）】\n"
    "1. 分析性用词（「机制」「结构」「逻辑」「体系」出现在小说中）-> 换成日常表达\n"
    "2. 抽象名词滥用 -> 直接说事\n"
    "3. 体制内用语（「进一步」「深入」「推进」「落实」）-> 删\n"
    "4. 专业术语堆砌 -> 只保留必要的，用白话解释\n"
    "例外：历史题材正式用语、文学向刻意密度、喜剧夸张修辞可保留。"
)

DE_AI_PASS_3 = (
    "【Pass 3：回自然感（Restore Natural Presence）】\n"
    "1. 具体的感官细节（气味、温度、触感）\n"
    "2. 角色说话方式的区分（不同人不同语气）\n"
    "3. 节奏变化（长短句交错）\n"
    "4. 社会位置感的对话（上级和下属说话方式不同）\n"
    "5. 场景特有的记忆点\n"
    "6. 项目特有的语言习惯（角色的口头禅）\n"
    "原则：少即是多。每段加1-2个具体细节就够了。"
)

DE_AI_3_PASS_METHOD = "\n\n".join([
    "【系统性去AI三遍法】\n",
    DE_AI_PASS_1,
    "",
    DE_AI_PASS_2,
    "",
    DE_AI_PASS_3,
    "",
    "【升级策略】\n"
    "- 轻度AI味：只做Pass 1\n"
    "- 中度AI味：Pass 1 + Pass 2\n"
    "- 重度AI味：完整三遍 + 重点段落重写",
])

# ---------------------------------------------------------------------------
# SHOW-DON'T-TELL REPLACEMENT TABLE
# ---------------------------------------------------------------------------
EMOTION_REPLACEMENT_TABLE = (
    "【情绪外化 — Show Don't Tell 替换表】\n"
    "紧张：\n"
    "  ❌「他感到一阵紧张，心跳不由自主地加快了」\n"
    "  ✅「他攥紧了手里的纸杯，水洒出来一些」\n"
    "愤怒：\n"
    "  ❌「愤怒在他心中燃烧，他不由得握紧了拳头」\n"
    "  ✅「他把筷子往桌上一拍，碗里的汤溅了出来」\n"
    "悲伤：\n"
    "  ❌「一丝悲伤涌上心头，她的眼中闪过泪光」\n"
    "  ✅「她低头搅着咖啡，搅了很久」\n"
    "害怕：\n"
    "  ❌「恐惧瞬间笼罩了他，他感到一阵战栗」\n"
    "  ✅「他的背贴在墙上，不敢动」\n"
    "失望：\n"
    "  ❌「她感到一丝失落，心仿佛被什么东西揪住了」\n"
    "  ✅「『哦。』她把手机锁了屏」\n"
    "惊讶：\n"
    "  ❌「他的瞳孔微微收缩，显然没有想到会听到这样的话」\n"
    "  ✅「他张了张嘴，什么都没说出来」\n"
    "心痛：\n"
    "  ❌「一阵心痛袭来」\n"
    "  ✅「手指掐进肉里自己不知道疼」\n"
    "绝望：\n"
    "  ❌「他陷入了深深的绝望」\n"
    "  ✅「他坐在那里，烟灰掉了一裤腿也没有弹」\n"
    "心如死灰：\n"
    "  ❌「她心如死灰」\n"
    "  ✅「她把手机翻过来扣在桌上，再没拿起来过」\n"
)

# ---------------------------------------------------------------------------
# SCENE / ENDING REWRITE EXAMPLES
# ---------------------------------------------------------------------------
SCENE_REWRITE_EXAMPLES = (
    "【场景改写示例】\n"
    "AI风场景：\n"
    "  ❌「阳光透过窗帘的缝隙洒进来，在地板上投下斑驳的光影。"
    "空气中弥漫着淡淡的花香，仿佛整个世界都沉浸在一片宁静祥和的氛围中。」\n"
    "  ✅「下午三点，客厅里只有钟在走。」\n\n"
    "AI风打斗：\n"
    "  ❌「他的拳头犹如疾风骤雨般猛烈，每一击都蕴含着不容置疑的力量。"
    "对手的瞳孔微微收缩，显然没有预料到如此凌厉的攻势。」\n"
    "  ✅「他一拳怼过去，对方没躲开，嘴角破了。」\n\n"
    "结尾改写：\n"
    "  升华式 ❌「他站在窗前，望着远方的天际线，终于明白了生活的真谛」\n"
    "        ✅「他把烟掐了，回屋睡觉。」\n"
    "  总结式 ❌「这一刻，一切都变了。她知道，从今以后，她的人生将翻开崭新的一页。」\n"
    "        ✅「她关上了那扇门。没回头。」\n"
    "  感慨式 ❌「岁月如流水般悄然流逝……」\n"
    "        ✅ 直接删掉这种段落。\n"
)

# ---------------------------------------------------------------------------
# QUICK SELF-CHECK MNEMONIC
# ---------------------------------------------------------------------------
QUICK_SELF_CHECK = "\n".join([
    "一段不过三句话。",
    "对话要像人说话。",
    "心情不写心里话。",
    "结尾不搞大升华。",
    "打斗不写流水账。",
    "日常要埋伏笔桩。",
])

# ---------------------------------------------------------------------------
# INPUT-AWARE REVISION DIAGNOSTICS
# ---------------------------------------------------------------------------

# Only phrases that actually occur in the source are echoed into the rewrite
# prompt.  This avoids priming the model with pages of stock expressions that
# were not present in the chapter in the first place.
DE_AI_FINGERPRINT_GROUPS: dict[str, tuple[str, ...]] = {
    "模糊比拟": (
        "仿佛", "犹如", "宛若", "好像", "似乎", "如同",
    ),
    "弱化副词": (
        "微微", "轻轻", "缓缓", "淡淡", "隐隐", "些许", "几分", "一丝", "一抹",
    ),
    "自动心理反应": (
        "不由得", "不禁", "忍不住", "情不自禁", "心中一动", "心头一震", "心下一沉",
    ),
    "解释与总结": (
        "值得注意的是", "不难发现", "由此可见", "总而言之", "这意味着", "这说明",
        "这一切都说明", "他终于明白", "她终于明白", "他意识到", "她意识到",
    ),
    "书面连接": (
        "与此同时", "于是乎", "从而", "因而", "诚然", "然而", "因此", "随之",
        "在此之前", "在此之后", "另一方面",
    ),
    "顺滑推进副词": (
        "随即", "随后", "很快", "立刻", "立即", "逐渐", "慢慢", "忽然", "突然",
        "终于", "始终", "一直", "反复", "来回", "片刻", "几秒后",
    ),
    "神态动作套件": (
        "深吸一口气", "眼中闪过", "嘴角勾起", "眉头微皱", "瞳孔微缩", "脸色一变",
        "目光坚定", "不容置疑", "若有所思", "余光", "视线", "指腹", "愣住",
        "冷笑了一声", "屏住呼吸", "呼吸顿了一下",
    ),
    "空泛宏大词": (
        "命运", "宿命", "注定", "崭新的一页", "一切都变了", "意义深远",
        "前所未有", "无法言喻", "难以形容",
    ),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])|(?<=……)")
_LEADING_PUNCTUATION_RE = re.compile(r"^[\s\"'“”‘’《》【】（）()，、；：—…]+")
_TEXT_CHAR_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_SYMMETRIC_TEMPLATE_RES = (
    re.compile(r"不是[^。！？\n]{0,36}(?:而是|却是)"),
    re.compile(r"与其[^。！？\n]{0,36}不如"),
    re.compile(r"一边[^。！？\n]{0,28}一边[^。！？\n]{0,28}一边"),
    re.compile(r"有的[^。！？\n]{0,28}有的[^。！？\n]{0,28}有的"),
)
_LITERAL_FIDELITY_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_-]{1,}|\d+(?:[.,]\d+)?(?:%|％|年|月|日|天|点|时|分|秒|岁|章|层|楼|号|"
    r"公里|千米|米|厘米|元|块|万|千|百|次|个|人|页|封|把|枚|颗|瓶|杯)?|"
    r"[零〇一二两三四五六七八九十百千万]+(?:年|月|日|天|点|时|分|秒|岁|章|层|楼|号|"
    r"公里|千米|米|厘米)"
)


def _visible_length(value: str) -> int:
    return sum(1 for char in value if _TEXT_CHAR_RE.match(char))


def _sentences(value: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(value) if part.strip()]


def _variation(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    return (pstdev(values) / average) if average else 0.0


def _literal_fidelity_tokens(value: str) -> list[str]:
    return list(dict.fromkeys(_LITERAL_FIDELITY_TOKEN_RE.findall(value or "")))


def analyze_de_ai_fingerprints(original_text: str) -> dict[str, Any]:
    """Return compact, deterministic signals used to target a rewrite.

    The report is intentionally heuristic.  It does not pretend to predict a
    third-party detector score; it simply prevents every chapter from receiving
    the same generic rewrite instructions.
    """

    source = str(original_text or "")
    paragraphs = [line.strip() for line in source.splitlines() if line.strip()]
    sentences = _sentences(source)
    sentence_lengths = [_visible_length(item) for item in sentences if _visible_length(item)]
    paragraph_lengths = [_visible_length(item) for item in paragraphs if _visible_length(item)]

    phrase_groups: list[dict[str, Any]] = []
    for label, phrases in DE_AI_FINGERPRINT_GROUPS.items():
        hits = [(phrase, source.count(phrase)) for phrase in phrases if phrase in source]
        if hits:
            phrase_groups.append({
                "label": label,
                "count": sum(count for _, count in hits),
                "examples": [phrase for phrase, _ in hits[:4]],
            })

    symmetric_count = sum(len(pattern.findall(source)) for pattern in _SYMMETRIC_TEMPLATE_RES)

    opening_counter: Counter[str] = Counter()
    for sentence in sentences:
        clean = _LEADING_PUNCTUATION_RE.sub("", sentence)
        opening = "".join(_TEXT_CHAR_RE.findall(clean))[:2]
        if len(opening) == 2:
            opening_counter[opening] += 1
    repeated_openings = [
        {"opening": opening, "count": count}
        for opening, count in opening_counter.most_common(4)
        if count >= 3
    ]

    comma_count = source.count("，") + source.count(",")
    terminal_count = sum(source.count(mark) for mark in "。！？!?")
    return {
        "character_count": _visible_length(source),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentence_lengths),
        "average_sentence_length": round(mean(sentence_lengths), 1) if sentence_lengths else 0.0,
        "sentence_length_variation": round(_variation(sentence_lengths), 2),
        "paragraph_length_variation": round(_variation(paragraph_lengths), 2),
        "comma_terminal_ratio": round(comma_count / max(1, terminal_count), 2),
        "phrase_groups": phrase_groups,
        "symmetric_template_count": symmetric_count,
        "repeated_openings": repeated_openings,
    }


def _render_revision_diagnostics(report: dict[str, Any]) -> str:
    targets: list[str] = []
    for group in report["phrase_groups"][:5]:
        examples = "、".join(group["examples"])
        targets.append(f"- {group['label']}：{group['count']}处（原文命中：{examples}）")

    if report["symmetric_template_count"]:
        targets.append(f"- 工整对称模板：{report['symmetric_template_count']}处；拆掉论证式骨架")

    repeated = report["repeated_openings"]
    if repeated:
        detail = "、".join(f"“{item['opening']}”×{item['count']}" for item in repeated)
        targets.append(f"- 句首锚点重复：{detail}；只在确有指代需要时保留")

    sentence_count = report["sentence_count"]
    sentence_variation = report["sentence_length_variation"]
    if sentence_count >= 8 and sentence_variation < 0.38:
        targets.append("- 句长起伏偏小；按动作压力和人物语气自然形成长短差，不要机械轮换")
    if report["paragraph_count"] >= 4 and report["paragraph_length_variation"] < 0.28:
        targets.append("- 段落体量过于齐整；按场景拍点分段，不要固定每段相同句数")
    if report["comma_terminal_ratio"] > 2.8:
        targets.append("- 逗号链偏多；在动作或判断真正落地处收句，避免连续从句")

    if not targets:
        targets.append("- 未命中明显套话；重点检查解释过满、节奏过齐和人物说话同声同气")
    return "\n".join(targets)


DE_AI_FIDELITY_CONTRACT = "\n".join([
    "【故事保真合同 — 优先级最高】",
    "- 在心里先列出逐段事实账本；账本不输出。",
    "- 人名、称谓、地点、时间、数字、物件、伤势、线索、因果、事件先后全部保留。",
    "- 叙事人称、视角角色、时态、对白说话人及对白意图不得改变。",
    "- 不新增原文没有的动作、感官、回忆、动机、关系或世界设定；不能为追求画面感编细节。",
    "- 可删的只有同义复述、旁白解释和空泛判断；承载情节的信息句不能删。",
    "- 正文总体长度保持在原文约95%至108%；精简套话后用原有事件的节奏、对白和视角承接维持篇幅，不能新增剧情。",
])


DE_AI_RECONSTRUCTION_METHOD = "\n".join([
    "【先取事实，再离开原句重写】",
    "1. 取事实：在心里把每个场景拆成不可丢失的事件、物件、对白意图和因果；完成后不要沿着原句逐行修改。",
    "2. 关掉原句：按事实账本重新落笔，整章每一段都要重新组织。除人名、编号、必要原话外，不照抄完整句子，"
    "也不保留原文连续十六字以上的措辞。只删几个副词或替换近义词不算完成。",
    "3. 重写句法，不重排事件：同一拍可从物件、动作、对白或人物当下判断切入；允许省略已经明白的主语和因果，"
    "但场景顺序、行为结果和线索归属保持不动。",
    "4. 留下人的口气：对白允许停顿、追问、改口和短答，前提是原有意图不变；叙述可以有克制的个人判断，"
    "判断必须来自原文已有事实，不补背景，不替人物讲道理。",
    "5. 打散机器节拍：短句、普通句和少量长句由现场压力自然交错；对话、突然动作和关键发现可以独立成段。"
    "避免连续用人名开句，避免每段都按环境—动作—心理—解释收齐。",
    "6. 去掉讲解：读者从动作或对白已经知道的内容，不再由旁白复述；章末仍停在原文最后的动作、对白或悬念。",
    "7. 冷读：逐项核对事实账本；发现新事实、漏线索、人物意图偏移或因果倒置，就在输出前修回。",
    "这不是禁词替换题。不要故意写错字、制造病句、滥用破折号或把全文切成整齐的短句。"
    "自然的不齐整来自人物和场面，不来自随机噪声。",
])


def build_de_ai_story_ledger_prompt(original_text: str) -> str:
    """Build the isolation-stage prompt used before prose reconstruction.

    The ledger deliberately converts prose into terse ordered facts.  The
    second model call receives this ledger instead of the source chapter, which
    prevents a conservative model from returning a near-verbatim copy while
    still giving it the information needed to preserve the story.
    """

    literal_tokens = "、".join(_literal_fidelity_tokens(original_text)) or "无"
    return "\n\n".join([
        "把下面的小说正文拆成一份核心故事账本，供另一名编辑在看不到原文的情况下重写。"
        "你只做事实抽取，不润色、不评价、不推断、不补充。",
        "【账本必须包含】\n"
        "- 叙事人称、视角角色、时态、基调。\n"
        "- 人物表：逐人记录原文姓名/称谓及原文明确使用的代词（他、她、它等）；"
        "原文未明示时标为未知，禁止猜测。\n"
        "- 逐场景的时间、地点、在场人物和严格事件顺序。\n"
        "- 每一个推动情节或制造悬念的动作、物件、状态、因果与人物已知信息；相邻微动作合并成一个拍点。\n"
        "- 所有人名、称谓、数字、日期、时刻、数量、编号、专名和物件归属，按原字保留。\n"
        "- 每段对白的说话人、核心意图及必须保留的关键信息；无需照抄寒暄或对白标签。\n"
        "- 结尾最后一个发现、动作或悬念，以及它依赖的前置信息。\n"
        "- 原文若在场面展示后又集中回顾线索，只把各事实记在它们首次发生的位置；"
        "除非回顾直接引发新的决定、动作或发现，否则不要另立复盘拍点，也不要标为[硬]。",
        "【账本格式】\n"
        "先写一行叙事约束，再写人物表，然后按 01、02、03……列出事件拍点，最后写‘结尾锁定’。"
        "两三千字章节通常压成18至32个编号拍点，不要把一句话里的每个姿势拆成独立事件。"
        "推动剧情、人物选择、线索或因果的内容标为[硬]；只负责现场质感且删去不改变故事的灯光、气味、"
        "外貌、视线、神态和重复检查动作标为[可选]，绝不能因为原文写得具体就全部标成[硬]。"
        "账本只记录各位置直接发生的动作和状态，不评论原文是否含混、自相矛盾或前后表述有差异；"
        "遇到未解释的去向或跳跃，只在对应位置记录表面事实，不另写分析性备注。"
        "使用短语、分号和箭头，禁止写成连贯小说段落；不得复制原文完整句子；不要 Markdown 代码块。",
        f"【必须原字记录的标记】\n{literal_tokens}",
        f"【待抽取正文】\n{original_text}",
    ])


_LEDGER_EVENT_RE = re.compile(
    r"^\s*\d{1,3}\s*(?=\[|[.、:：)）-]|\s)",
    re.MULTILINE,
)
_LEDGER_HEADING_RE = re.compile(r"^\s*【[^】]+】\s*$")
_MACRO_SCENE_NOTES = (
    "从正在改变局面的动作或一句已经发生的对白落笔。期限、地点和人物关系只在它们影响下一步时穿插，"
    "不要先集中报时间、坐标和背景。",
    "让相邻事实依附于同一场正在进行的行动、核对或交锋；跳过不改变状态的过门。"
    "换段只因为说话人、压力来源或现场状态真的改变，不为制造长短反差而单独留一句。",
    "让对白、动作和已有物件承担发现，写到最后一个实际结果就停。"
    "不要在结尾回顾过程、重排线索或替读者说明意义。",
)

# A compressed ledger is allowed to omit non-consequential micro-actions, but
# it must not *interpret* the remaining actions.  These terms have repeatedly
# turned an observation into an instruction/plan (for example, "看向北门"
# becoming "戒备北门") or an unexplained gesture into a prior agreement.  If
# the detailed ledger did not use the term, falling back to the detailed ledger
# is safer than giving the prose model a newly invented causal frame.
_MACRO_LEDGER_HIGH_RISK_INFERENCES = (
    "暗号",
    "约定",
    "戒备",
    "留守",
    "监视",
    "盯梢",
    "伏击",
    "埋伏",
    "圈套",
    "预谋",
    "事先安排",
    "早有准备",
)

# A macro ledger that keeps too many of these operations still acts as a shot
# list even when it has only two or three numbered lines.  The prose model may
# mention a few indispensable mechanics, but the compressed steering layer
# must primarily describe changed state, choice, threat, and discovery.
_MACRO_LEDGER_PROCEDURE_MARKERS = (
    "锁车",
    "敲门",
    "扫视",
    "看向",
    "调整角度",
    "调角度",
    "反光",
    "摸索",
    "取钥匙",
    "启动叉车",
    "踩油门",
    "开南门",
    "绕过",
    "穿过",
    "停车",
    "上楼",
    "下楼",
    "开门",
    "关门",
    "换鞋",
    "倒水",
    "检查门窗",
    "低声报告",
)


def _ledger_preamble_and_records(story_ledger: str) -> tuple[str, list[str]]:
    """Separate global narrative constraints from ordered ledger events."""

    preamble: list[str] = []
    pending: list[str] = []
    current: list[str] = []
    records: list[str] = []
    seen_event = False

    for raw_line in str(story_ledger or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _LEDGER_EVENT_RE.match(line):
            if current:
                records.append("\n".join(current))
            current = [*pending, line]
            pending = []
            seen_event = True
            continue
        if _LEDGER_HEADING_RE.match(line):
            if current:
                records.append("\n".join(current))
                current = []
            pending = [line]
            continue
        if current:
            current.append(line)
        elif pending:
            pending.append(line)
        elif not seen_event:
            preamble.append(line)
        else:
            pending.append(line)

    if current:
        records.append("\n".join(current))
    if pending:
        records.append("\n".join(pending))
    if not records:
        records = [
            part.strip()
            for part in re.split(r"\n\s*\n|(?<=。)\s*", str(story_ledger or ""))
            if part.strip()
        ]
        preamble = []
    return "\n".join(preamble).strip(), records


def _balanced_ledger_groups(records: list[str], group_count: int) -> list[list[str]]:
    """Partition ordered ledger records without splitting an event record."""

    if not records:
        return []
    count = max(1, min(group_count, len(records)))
    if count == 1:
        return [records]

    weights = [max(1, _visible_length(record)) for record in records]
    total_weight = sum(weights)
    groups: list[list[str]] = []
    current: list[str] = []
    cumulative = 0
    for index, (record, weight) in enumerate(zip(records, weights, strict=True)):
        current.append(record)
        cumulative += weight
        remaining_records = len(records) - index - 1
        remaining_groups = count - len(groups) - 1
        boundary = total_weight * (len(groups) + 1) / count
        if (
            remaining_groups > 0
            and remaining_records >= remaining_groups
            and (
                cumulative >= boundary
                or remaining_records == remaining_groups
            )
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build_de_ai_chunked_rewrite_prompts(
    original_text: str,
    story_ledger: str,
    *,
    chunk_count: int | None = None,
    fidelity_source: str | None = None,
) -> list[str]:
    """Build compact, ordered scene prompts for a long-form reconstruction.

    Generating two or three event-driven macro scenes keeps a 2,000-3,000
    character chapter manageable without imposing the same short-span opening,
    turn, and closing cadence every few hundred characters.  The returned scenes
    are joined verbatim in the same order; no prose-level post-processing is
    required.
    """

    report = analyze_de_ai_fingerprints(original_text)
    authority_text = str(
        original_text if fidelity_source is None else fidelity_source
    )
    narrative_context, records = _ledger_preamble_and_records(story_ledger)
    # Keep the event scale stable across all three user-visible rounds.  A
    # slightly expanded prior candidate must not make round two suddenly gain
    # another artificial scene boundary; the immutable first-round source owns
    # both fidelity and default partitioning.
    authority_character_count = _visible_length(authority_text)
    desired_count = (
        chunk_count
        if chunk_count is not None
        else max(
            1,
            min(3, (max(1, authority_character_count) + 999) // 1000),
        )
    )
    groups = _balanced_ledger_groups(records, desired_count)
    if not groups:
        return []

    group_texts = ["\n".join(group) for group in groups]
    group_weights = [max(1, _visible_length(value)) for value in group_texts]
    total_weight = sum(group_weights)
    # Current long-form providers tend to land about 15-25% below a requested
    # Chinese visible-character target.  The bounded headroom keeps the joined
    # chapter near its input length instead of shrinking on every user pass;
    # the deterministic 1.35 expansion ceiling remains the final guardrail.
    target_total = max(20, round(authority_character_count * 1.30))
    targets = [
        max(60, round(target_total * weight / total_weight))
        for weight in group_weights
    ]
    source_tokens = _literal_fidelity_tokens(authority_text)
    residue_terms = list(dict.fromkeys(
        phrase
        for group in report["phrase_groups"]
        for phrase in group["examples"]
    ))
    residue_line = "、".join(residue_terms) or "无"
    prompts: list[str] = []
    for index, (ledger_chunk, target) in enumerate(zip(group_texts, targets, strict=True)):
        # Event indices belong to the ledger format, not the story. Remove
        # them before deciding which source literals this span must reproduce.
        facts_without_indices = _LEDGER_EVENT_RE.sub("", ledger_chunk)
        required_tokens = [token for token in source_tokens if token in facts_without_indices]
        literal_line = "、".join(required_tokens) or "无"
        target_min = max(50, round(target * 0.92))
        target_max = max(target_min + 20, round(target * 1.08))
        if len(group_texts) == 1 or index == 0:
            scene_note = _MACRO_SCENE_NOTES[0]
        elif index == len(group_texts) - 1:
            scene_note = _MACRO_SCENE_NOTES[2]
        else:
            scene_note = _MACRO_SCENE_NOTES[1]
        position_rule = (
            "这是开篇片段，直接进入第一个拍点，不写全章导语。"
            if index == 0
            else "这是中间片段，不回顾前文，不另起故事，不为本段做收束。"
        )
        if index == len(group_texts) - 1:
            position_rule = (
                "这是末尾片段，只停在账本最后的动作或发现，不总结、不升华、不预告；"
                "结尾悬念依赖的前置信息已经在前文出现，不必在这里成组复述。"
            )
        prompts.append("\n\n".join([
            f"把下面账本拍点写成连续长章的第{index + 1}/{len(group_texts)}个小说片段。"
            f"本段目标为{target_min}至{target_max}个可见字符；只输出本段正文。",
            "【不可变】\n"
            "- [硬]事实、人物、物件归属、对白意图、因果和先后全部写入，不新增账本没有的动作、感官、解释或背景。\n"
            "- [可选]气氛只取会影响人物当下行动的少数项目，不连续盘点灯光、气味、陈设和外貌。\n"
            "- 只写本段拍点，不挪用后续事件；账本编号、[硬]/[可选]标签、字段名和清单句法不得进入正文。\n"
            "- 对白可重新组织口气，但说话人、信息和意图不变；不要用旁白再复述对白已经说清的内容。\n"
            "- 若原文/账本明确写出同一物件前后持有人或位置不同，却没有交代中间转移，"
            "原样保留前后两个状态，不得自行补写归还、递交、放回、取走等连接动作。\n"
            "- 账本若仍误把‘回顾已知线索’列成拍点，不重列前文事实；只写回顾当下真正新增的动作、"
            "选择或发现。事实已在首次发生处保留，不等于还要保留复盘形式。\n"
            f"- {position_rule}",
            "【本段落笔】\n"
            f"{scene_note}\n"
            "按拍点自然换段：有时一拍独立，有时三四拍连在一个段里，不固定每片段的段数。"
            "长短句由动作自然形成，不为制造长短反差而单独留一句；不要机械轮换句式，"
            "不故意写错字，不靠随机口语词制造所谓人味。",
            "【避免流水账与镜头链】\n"
            "- 进门、上楼、检查、转身、看向某处等常规步骤若不改变局面，可并入一句或直接越过；"
            "不能把账本每个箭头扩成一条完整句。\n"
            "- 优先落在会改变现场状态的操作、阻碍、选择、对白和结果。人物没有回答时，可直接写其下一动作，"
            "不必反复写‘没有回答、沉默片刻、声音变沉’。\n"
            "- 线索通过人物当下碰到、核对或说出的物件呈现；不要在段尾把已有线索重新排列成总结清单，"
            "也不要替读者写‘这些仍无法解释……’。",
            "【去掉成品腔】\n"
            "- 一个动作或一句对白已经交代清楚，就立即往下走；不要追加心理解释、气氛总结或意义判断。\n"
            "- 每约150字最多留一句静态环境，且必须影响眼前动作；不要把每个拍点都写成完整精致镜头。\n"
            "- 具体名词和普通动词优先。主语明确后可以省略；少用代词链、程度副词和时间副词替代真实动作。\n"
            "- 除账本硬事实确实需要外，不另加余光、目光、眉头、呼吸等感知标签，也不用书面过渡把事件抹得过分顺滑。\n"
            f"- 原稿实际命中的残留表达为：{residue_line}。重写时不要照搬这些措辞。",
            f"【整章叙事约束】\n{narrative_context or '服从账本已有的人称、视角、时态和基调。'}",
            f"【本段必须原字出现的源文标记】\n{literal_line}",
            f"【本段账本拍点】\n{ledger_chunk}",
        ]))
    return prompts


def build_de_ai_macro_ledger_compression_prompt(chunk_prompt: str) -> str:
    """Collapse a detailed scene ledger before it reaches the prose model."""

    prompt = str(chunk_prompt or "")
    ledger_marker = next(
        (
            marker
            for marker in ("【本段账本拍点】", "【本段事实账本】")
            if marker in prompt
        ),
        "",
    )
    detailed_ledger = prompt.partition(ledger_marker)[2].strip() if ledger_marker else prompt
    required_match = re.search(
        r"【本段必须原字出现的源文标记】\n([^\n]*)",
        prompt,
    )
    required_tokens = required_match.group(1).strip() if required_match else "无"
    target_units = max(2, min(3, round(max(1, _visible_length(detailed_ledger)) / 300)))
    return "\n\n".join([
        "把下面的详细事实账本压成宏观叙事单元。你只整理事实，不写小说正文。",
        "【目的】\n"
        "详细账本是校对材料，不是分镜脚本。正文模型只能看到你输出的少量宏观单元，"
        "因此要保留故事，却不能继续沿用一条事实对应一句或一段的粒度。",
        "【硬性规则】\n"
        f"- 输出{target_units}个宏观单元，不得多于3个；每个单元只写同一压力下的核心转折或结果。\n"
        "- 全部宏观单元合计不超过260个可见字符。宏观账本不是详尽摘要，只保留会改变人物决定、"
        "威胁、物件归属、后续条件、关键信息揭示或结尾悬念的事实。\n"
        "- 不得用长分号句把详细账本换一种格式重新列完；单个单元不得连续罗列三个以上"
        "声响、观察、走位、检查、开关门或物件操作。把过程压成它造成的局面变化。\n"
        "- 对被保留的事实，人物、物件归属、数字、条件、因果、对白信息、人物已知信息、"
        "关键状态变化和事件先后必须准确。\n"
        "- 每个动作、观察、发现、问话、回答、命令和判断的主体必须原样归属；不能把甲观察乙的动作压成乙要求甲行动，"
        "也不能把甲看到或听到某事写成乙已经知道该事。\n"
        "- 严格保留认识状态和语气强度：可能、像、猜测、未说明、没有回答、只见过等不能升级为确定、知情、同意或既定计划。\n"
        "- 只写详细账本明示的关系和用途。机械敲门顺序不能命名为‘暗号’或‘约定’；反复看门窗不能命名为‘戒备’、"
        "‘监视’或‘伏击’，除非这些词本来就在详细账本中。\n"
        "- 同一事件内部也要保留先后：先取出或交付物件、后解释用途，不得压成先解释后取物；先发现异常、后检查门窗，"
        "不得因合并而倒置。\n"
        "- 不得省略唯一促成关键结果的因果方法或出口，例如制造声响掩护撤离、从指定出入口脱身；"
        "把方法与结果压成同一因果短句，不展开机械步骤或沿途路线。不得省略承载后续条件的纸条、信件等"
        "物件交接，也不得模糊结尾线索出现的准确位置、门窗状态或人物只是‘见过’而非确认不存在的认识边界。\n"
        "- 人名和人称代词必须沿用详细账本；不得把他、她、它互换，也不得为姓名推断性别。\n"
        "- 若详细账本明确记录同一物件前后持有人或位置不同，却没有交代转移过程，"
        "两个端点都保留，但不得自行补出归还、递交、放回或取走。\n"
        "- 锁车、走路、上下楼、开关门、逐次声响、视线转移、反光角度调整、摸索、停顿和重复核对"
        "若不改变局面，直接省略；不要把它们压进同一长句继续列完。\n"
        "- 同一发现只出现一次。结尾编号或物件异常直接落在发现上，不列取物、排除、检查门窗、"
        "回忆和二次确认组成的验明链。\n"
        "- 不新增详细账本没有的动作、感官、解释、动机或背景；不输出人物表、总结、评价或写作建议。",
        f"【必须原字保留的标记】\n{required_tokens}",
        f"【待压缩详细账本】\n{detailed_ledger}",
        "输出格式：每行一个“01 [硬] 局面/转折/结果：……”宏观单元。"
        "每行只写一次核心变化，不用分号堆步骤；除此之外不要输出任何内容。",
    ])


def normalize_de_ai_macro_ledger(compact_ledger: str) -> str:
    """Normalize punctuation-only format drift without rewriting facts."""

    return re.sub(r"[；;]+", "，", str(compact_ledger or "")).strip()


def build_de_ai_macro_ledger_retry_feedback(
    chunk_prompt: str,
    compact_ledger: str,
    missing_tokens: list[str] | tuple[str, ...] = (),
) -> str:
    """Explain deterministic macro-ledger failures for one bounded retry."""

    prompt = str(chunk_prompt or "")
    compact = str(compact_ledger or "").strip()
    ledger_marker = next(
        (
            marker
            for marker in ("【本段账本拍点】", "【本段事实账本】")
            if marker in prompt
        ),
        "",
    )
    detailed_ledger = prompt.partition(ledger_marker)[2] if ledger_marker else prompt
    introduced_pronouns = [
        pronoun
        for pronoun in ("他", "她", "它")
        if pronoun in compact and pronoun not in detailed_ledger
    ]
    failures: list[str] = []
    missing = [str(token).strip() for token in missing_tokens if str(token).strip()]
    if missing:
        failures.append("补回必须原字保留的标记：" + "、".join(missing))
    if introduced_pronouns:
        failures.append(
            "删除详细账本没有的人称代词：" + "、".join(introduced_pronouns)
            + "；重复人物姓名，不推断性别"
        )
    visible = _visible_length(compact)
    if visible < 40 or visible > 260:
        failures.append(f"总可见字符当前为{visible}，必须控制在40至260之间")
    event_count = len(_LEDGER_EVENT_RE.findall(compact))
    if not 1 <= event_count <= 4:
        failures.append(f"当前有{event_count}个编号单元，必须为1至4个")
    procedure_count = sum(
        compact.count(marker)
        for marker in _MACRO_LEDGER_PROCEDURE_MARKERS
    )
    if procedure_count > 4:
        failures.append("机械步骤仍过多，只保留导致局面变化的因果方法和结果")
    introduced_inferences = [
        marker
        for marker in _MACRO_LEDGER_HIGH_RISK_INFERENCES
        if marker in compact and marker not in detailed_ledger
    ]
    if introduced_inferences:
        failures.append("删除原账本没有的推断：" + "、".join(introduced_inferences))
    detail = "；".join(failures) or "未满足宏观账本的确定性格式与颗粒度校验"
    return (
        "上一版未通过确定性硬校验："
        + detail
        + "。只修正这些问题，不改变其余人物、事实、物件归属、数字、条件、因果、"
        "认识状态和先后。仍按原格式输出1至3行，不使用中文或英文分号，不输出说明。"
    )


def build_de_ai_macro_ledger_fidelity_audit_prompt(
    chunk_prompt: str,
    compact_ledger: str,
) -> str:
    """Audit semantic compression before the ledger can steer prose."""

    prompt = str(chunk_prompt or "")
    ledger_marker = next(
        (
            marker
            for marker in ("【本段账本拍点】", "【本段事实账本】")
            if marker in prompt
        ),
        "",
    )
    detailed_ledger = (
        prompt.partition(ledger_marker)[2].strip() if ledger_marker else prompt
    )
    return "\n\n".join([
        "核对宏观账本是否忠实于详细事实账本。这里只审计事实压缩，不写小说正文。",
        "【允许】\n"
        "- 合并相邻拍点；省略不改变局面的走位、停顿、重复检查、逐次声响、观察办法、"
        "角度调整、开关门和可选气氛；改写句式。\n"
        "- 省略某个动作的重复机械操作、沿途路线或反复确认，只保留它造成的威胁、选择、发现或结果；"
        "但若该方法是结果成立的唯一因果、指定出入口、物件交接或后续条件的载体，就必须和结果合成一条保留。\n"
        "【必须判失败】\n"
        "- 改变动作、观察、发问、回答、命令、判断或持有关系的主体；改变物件位置或归属。\n"
        "- 把人物自行采取的动作压成他人的命令、指示或既定计划；把疑问、猜测、可能、"
        "未回答或只见过升级成确定事实。\n"
        "- 颠倒仍被保留的关键动作与信息揭示顺序；新增动机、因果、安排、交接或结论。\n"
        "- 漏掉会改变人物决定、威胁、物件归属、后续条件、关键信息揭示或结尾悬念的必要事实。\n"
        "- 漏掉促成关键结果的唯一方法或指定出口；漏掉纸条、信件、账页等承载条件的交接；"
        "漏掉结尾线索出现的准确位置、门窗状态，或把‘只见过’升级成‘确定不存在’。\n"
        "不要因为文字更短、具体方法或路线被省略、微动作被省略或多条事实被合并而判失败。"
        "这里的‘具体方法可省略’不包括结果成立所必需的唯一因果方法、指定出口、物件交接或结尾线索位置。"
        "被允许省略的微动作无需审计其内部先后；宏观账本仍明确写出的事实须核对主体、方式和顺序。",
        "【输出 JSON】\n"
        '{"passed":true,"issues":[]}\n'
        "或\n"
        '{"passed":false,"issues":[{"chunk":1,'
        '"kind":"role|order|contradiction|added|missing",'
        '"detail":"具体差异"}]}\n'
        "只能输出一个 JSON 对象。",
        f"【详细事实账本】\n{detailed_ledger}",
        f"【待审宏观账本】\n{str(compact_ledger or '').strip()}",
    ])


def build_de_ai_macro_ledger_structure_audit_prompt(
    compact_ledger: str,
) -> str:
    """Reject a compact ledger that still behaves like a shot list."""

    return "\n\n".join([
        "审计下面的宏观账本是否真正达到宏观颗粒度。这里只审结构，不核对事实真假，不写正文。",
        "【通过标准】\n"
        "- 每个编号只表达一个会改变局面的威胁、选择、关系、条件、揭示或结果。\n"
        "- 同一紧张场面可以直接从起因落到结果，省略声响、转身、寻找工具、调整角度、"
        "反复确认、报告等中间方法。\n"
        "- 唯一促成关键结果的因果方法、指定出口、物件交接或结尾线索位置若与结果合成一个短句，"
        "属于核心事实，不按微步骤计数；但不得再展开它的机械操作和沿途路线。\n"
        "【必须判失败】\n"
        "- staged：即使拆成两三行，仍按时间顺序保留一条完整分镜链，例如等待→灯灭→异响→"
        "抬门→找反光物→调角度→看见人→报告→解释；五个及以上相邻小拍即判失败。\n"
        "- checklist：仍连续列出取钥匙、启动、开门、绕行、穿过、骑车、停车、上楼、换鞋、"
        "检查等路线或操作步骤；四项及以上即判失败。\n"
        "- 不要因为账本只有三行、总字数短或没有分号就判通过；要看跨行累计的微步骤。\n"
        "人物名、数字、条件和核心对白信息本身不算微步骤。",
        "【输出 JSON】\n"
        '{"passed":true,"issues":[]}\n'
        "或\n"
        '{"passed":false,"issues":[{"chunk":1,'
        '"kind":"staged|checklist","detail":"具体仍被逐项保留的链条"}]}\n'
        "只能输出一个 JSON 对象。",
        f"【待审宏观账本】\n{str(compact_ledger or '').strip()}",
    ])


def validate_de_ai_macro_ledger(
    chunk_prompt: str,
    compact_ledger: str,
) -> tuple[bool, list[str]]:
    """Reject a compressed ledger that drops deterministic source markers."""

    prompt = str(chunk_prompt or "")
    compact = str(compact_ledger or "").strip()
    required_match = re.search(
        r"【本段必须原字出现的源文标记】\n([^\n]*)",
        prompt,
    )
    required_tokens = [
        token.strip()
        for token in (required_match.group(1).split("、") if required_match else [])
        if token.strip() and token.strip() != "无"
    ]
    missing = [token for token in required_tokens if token not in compact]
    ledger_marker = next(
        (
            marker
            for marker in ("【本段账本拍点】", "【本段事实账本】")
            if marker in prompt
        ),
        "",
    )
    detailed_ledger = prompt.partition(ledger_marker)[2] if ledger_marker else prompt
    introduced_pronouns = {
        pronoun
        for pronoun in ("他", "她", "它")
        if pronoun in compact and pronoun not in detailed_ledger
    }
    introduced_inferences = {
        marker
        for marker in _MACRO_LEDGER_HIGH_RISK_INFERENCES
        if marker in compact and marker not in detailed_ledger
    }
    procedure_marker_count = sum(
        compact.count(marker)
        for marker in _MACRO_LEDGER_PROCEDURE_MARKERS
    )
    event_count = len(_LEDGER_EVENT_RE.findall(compact))
    valid = bool(
        len(compact) >= 40
        and _visible_length(compact) <= 260
        and "[硬]" in compact
        and 1 <= event_count <= 4
        and "；" not in compact
        and ";" not in compact
        and procedure_marker_count <= 4
        and not missing
        and not introduced_pronouns
        and not introduced_inferences
    )
    return valid, missing


def apply_de_ai_macro_ledger(
    chunk_prompt: str,
    compact_ledger: str,
    *,
    include_fact_appendix: bool = False,
) -> str:
    """Steer prose with macro turns, keeping detailed facts out of its outline.

    A full numbered fact appendix is useful to an auditor, but giving it to the
    prose model recreates the shot list that macro compression removed.  The
    normal generation path therefore sees only the semantically audited macro
    ledger.  Callers may still request the appendix for a factual repair turn;
    the immutable-source fidelity audit remains the authority either way.
    """

    prompt = str(chunk_prompt or "")
    marker = next(
        (
            value
            for value in (
                "【本段宏观叙事单元（只定事实边界，不是逐句大纲）】",
                "【本段账本拍点】",
                "【本段事实账本】",
            )
            if value in prompt
        ),
        "",
    )
    compact = str(compact_ledger or "").strip()
    if not marker or not compact:
        return prompt
    head, _, detailed_ledger = prompt.partition(marker)
    fact_rule = (
        "- 宏观叙事单元中的[硬]核心事实、人物、物件归属、对白意图、因果和先后全部写入；"
        "后置事实附录只用于校对主体、位置、方式和顺序，不要求逐条落笔。"
        "不新增账本没有的动作、感官、解释或背景。"
        if include_fact_appendix
        else
        "- 宏观叙事单元中的[硬]核心事实、人物、物件归属、对白意图、因果和先后全部写入。"
        "压缩时省略的常规步骤不是隐藏的必写拍点，生成后会另行依据不可变原文做事实审计；"
        "不得猜回逐拍过程，也不新增动作、感官、解释或背景。"
    )
    head = head.rstrip().replace(
        "- [硬]事实、人物、物件归属、对白意图、因果和先后全部写入，"
        "不新增账本没有的动作、感官、解释或背景。",
        fact_rule,
    ).replace(
        "按拍点自然换段：有时一拍独立，有时三四拍连在一个段里，不固定每片段的段数。",
        "宏观单元只定事实边界，不对应句子或段落；可在一个自然段中交叉承载多个单元，"
        "不得按编号顺序逐项展开。",
    )
    recap_markers = (
        "回顾已知",
        "回顾线索",
        "复盘",
        "梳理已知",
        "逐一回想",
        "现有线索无法解释",
        "已有线索无法解释",
        "已知信息",
        "已有线索",
        "当前状态：已有",
    )
    appendix = ""
    if include_fact_appendix:
        appendix_lines = [
            line
            for line in detailed_ledger.splitlines()
            if "[硬]" in line
            and not line.strip().startswith("结尾锁定")
            and not any(value in line for value in recap_markers)
        ]
    else:
        appendix_lines = []
    if appendix_lines:
        appendix = (
            "\n\n【后置事实校对附录（不决定正文取舍）】\n"
            "附录中的常规走位、声响、开关门、观察与检查不是必写拍点；只有宏观单元决定正文"
            "要落下的核心变化。若正文提及对应事实，主体、物件位置与归属、动作方式、认识状态"
            "和先后必须与附录一致。不得按附录编号逐句或逐段展开。\n"
            + "\n".join(appendix_lines)
        )
    priority = (
        "先服从宏观单元的取舍与颗粒度，再用附录校对已经写到的事实。"
        "不得为了覆盖附录而补回过门、完整分镜链或执行清单；只输出小说正文。"
        if appendix
        else
        "只服从宏观单元的取舍与颗粒度；省略项由生成后的原文事实审计处理。"
        "不得自行补回压缩掉的过门、完整分镜链或执行清单；只输出小说正文。"
    )
    return (
        head
        + "\n\n【本段宏观叙事单元（只定事实边界，不是逐句大纲）】\n"
        + compact
        + appendix
        + "\n\n【落笔优先级】\n"
        + priority
    )


def build_de_ai_fidelity_audit_prompt(
    original_text: str,
    candidate_chunks: list[str],
) -> str:
    """Ask a separate model turn to audit story semantics, not prose style."""

    rendered_chunks = "\n\n".join(
        f"【候选片段 {index}】\n{chunk}"
        for index, chunk in enumerate(candidate_chunks, start=1)
    )
    return "\n\n".join([
        "核对下面的小说原文与候选片段。你只做故事保真审计，不评价文风，也不要求照抄原句。",
        "【判定范围】\n"
        "逐项检查人物身份与代词、时间、地点、数量、物件归属、对白说话人和条件、因果、"
        "人物已知信息、事件先后、结尾发现。只有语义相同但措辞不同，不算问题。\n"
        "数量必须同时核对总数与分项关系：原文给出总数 N 时，候选不得先把 N 件写成一组，"
        "随后又用‘连同、另有、其余’追加 M 件而造成总量增加；若 N 本来包含后述分项，"
        "候选措辞也必须让包含关系明确。\n"
        "事件先后不能只核对‘两件事都出现了’：先定位原文中每个会改变人物已知信息、"
        "物件位置或持有人、真假判断、出入口状态的对白与动作，再按出现顺序逐一对照候选。"
        "尤其核对揭示性对白与紧邻的取出、递交、打开、藏入等动作；原文 A 后 B，候选写成"
        "B 后 A，即使 A、B 都保留，也必须以 order 判失败。\n"
        "省去不影响情节的灯光、气味、外貌、视线、神态、走位微动作或同义复述不算遗漏；"
        "对白压缩或改口只要说话人、条件和信息不变也应通过。疑问句只是在询问同一件事时，"
        "‘今晚不急着走吧’与‘今晚急着离开吗’这类正反问法不自动构成条件写反；只有回答分支、"
        "人物选择或已知信息随之改变才算冲突。这个宽容不适用于陈述事实中的‘没有联系’与"
        "‘主动联系’等真正正反变化。\n"
        "原文引号内或作为固定称谓出现的第一人称必须按字面核对，例如‘给我信的人’是一个完整称谓。"
        "候选保留该称谓不等于切换叙事人称，也不等于改变收信人；只有称谓所指、说话人或事件参与者"
        "确实改变时才能报 role。\n"
        "原文若在事件已经展示后集中回顾人物、期限、线索、物件流转，或旁白总结‘这些线索仍无法解释某事’，"
        "候选只要在全章前文已呈现对应事件与悬念，就可以删掉这段复盘；不得把省略重复复盘判为 missing。"
        "物件最后一次出现及其交接已写清、且正文没有擅自给出确定去向时，也不要求再用旁白声明‘去向不明’。\n"
        "下列任一情况必须判失败：遗漏承载情节的事实；把条件正反（这里指陈述条件而非逻辑等价问法）、"
        "真假、主动被动、人物归属或"
        "事件顺序写反；新增会改变读者对故事理解的动作、解释、动机、结论或设定。",
        "【输出 JSON】\n"
        '{"passed":true,"issues":[]}\n'
        "或\n"
        '{"passed":false,"issues":[{"chunk":1,"kind":"contradiction",'
        '"detail":"用一句具体中文说明与原文冲突之处"}]}\n'
        "chunk 必须填写 1 到候选片段总数；若问题跨片段，填写最直接造成问题的片段。"
        "kind 只能是 missing、contradiction、added、role、order。只输出一个 JSON 对象，"
        "不要 Markdown、解释或修订正文。",
        f"【原文】\n{original_text}",
        rendered_chunks,
    ])


def build_de_ai_style_audit_prompt(candidate_chunks: list[str]) -> str:
    """Audit structural machine-writing signals without rewriting prose."""

    rendered_chunks = "\n\n".join(
        f"【候选片段 {index}】\n{chunk}"
        for index, chunk in enumerate(candidate_chunks, start=1)
    )
    return "\n\n".join([
        "检查下面连续小说片段是否仍有明显的成品化机器叙事结构。只做表达结构审计，"
        "不核对故事事实，不重写正文。",
        "【必须判失败的高置信问题】\n"
        "- recap：场面已经展示后，旁白又把人物、线索、条件或意义成组复盘，并替读者下结论。\n"
        "- checklist：把进门、上楼、检查、移动等常规步骤逐项列完，像执行日志。\n"
        "- preamble：用日期、钟点、倒计时、地点和陈设连续定位，像先填写场景坐标再开始叙事。\n"
        "- staged：把悬念按静默、灯灭、声响、观察工具、发现、报告、解释的完整镜头链铺平，"
        "每一步都有过渡和说明，像已经排好的分镜脚本；也包括把事实账本逐条翻成一句或一段，"
        "即使没有使用‘随后’等连接词，读起来仍是一拍一拍验账。\n"
        "- camera：连续依靠‘随后、渐渐、一点点、目光、声音、呼吸、沉默’等镜头标签平滑推进。\n"
        "- exposition：开头或转场集中盘点时间、地点、外貌、灯光、气味、陈设，事件迟迟不动。\n"
        "- uniform：多个段落反复使用同一套环境—动作—对白—解释闭合结构。\n"
        "- stock：关键处用空泛心理、意义判断或漂亮收束代替人物眼前的动作与对白。",
        "【不要误报】\n"
        "必要的时间、编号、路线、物件状态、因果条件和事件顺序不是机器味；单个普通副词也不是问题。"
        "只有整段结构明显符合上面一类时才报告，最多报告三个最影响正文的片段。",
        "【输出 JSON】\n"
        '{"passed":true,"issues":[]}\n'
        "或\n"
        '{"passed":false,"issues":[{"chunk":1,"kind":"recap",'
        '"detail":"用一句具体中文指出该片段哪里在复盘或讲解"}]}\n'
        "chunk 必须为 1 到候选片段总数；kind 只能是 recap、checklist、preamble、staged、"
        "camera、exposition、uniform、stock。只输出一个 JSON 对象，不要 Markdown、解释或修订正文。",
        rendered_chunks,
    ])


def build_de_ai_chunk_repair_prompt(
    chunk_prompt: str,
    audit_issues: list[dict[str, Any]],
    *,
    repair_attempt: int = 1,
    previous_candidate: str = "",
) -> str:
    """Repair a rejected scene from its ledger and concrete audit findings."""

    issue_lines = "\n".join(
        f"- {str(item.get('detail') or '').strip()}"
        for item in audit_issues
        if str(item.get("detail") or "").strip()
    ) or "- 上一稿未通过故事保真审计。"
    repair_heading = (
        "【本次整段重生必须修正】"
        if repair_attempt <= 1
        else f"【第{repair_attempt}次整段重生必须修正】"
    )
    candidate = str(previous_candidate or "").strip()
    issue_kinds = {
        str(item.get("kind") or "").strip().lower()
        for item in audit_issues
    }
    if candidate and "length" in issue_kinds:
        repair_method = (
            "以下候选已通过故事事实审计，但篇幅略短。以它为底稿，只在账本已经明确的现场动作、"
            "物件操作或对白处自然展开；不得新增事件、解释、感官或背景，也不得把一个动作拆成"
            "流水账。其余已正确的叙述、段落节奏和事件顺序尽量保留。输出仍须是完整连续片段，"
            "不能只给补丁。\n\n"
            f"【待补足候选】\n{candidate}\n"
        )
    elif candidate:
        repair_method = (
            "以下候选已完成一次表达重生。以它为底稿，只修正上面列出的事实错误；"
            "其余已正确的叙述、段落节奏、对白和现场细节尽量保留。输出仍须是完整连续片段，"
            "不能只给补丁，也不能通过删掉场面来规避问题。\n\n"
            f"【待校正候选】\n{candidate}\n"
        )
    else:
        repair_method = (
            "不要对上一稿打补丁，也不要提及审计；重新依据本段账本写出完整片段。"
        )
    return "\n\n".join([
        chunk_prompt,
        f"{repair_heading}\n"
        f"{issue_lines}\n"
        f"{repair_method}"
        "绝不把‘原文、账本、表述、指代、归属含混、未明确、无法确认、去向不明’写成正文里的分析说明；"
        "这类账本备注只表示不要擅自补答案。按事件发生位置直接写动作与状态即可。"
        "原文未说明人物是否查看、展开、询问、知情或做过某事时，不得补写‘没有、未、从未、"
        "不可能’等否定状态；省略不等于事实上的否定。"
        "原文若明确出现物件持有人或位置的未解释跳变，只保留前后两个状态，"
        "不得为消除表面矛盾擅自补写交接、归还或取回过程。"
        "不得为了修正问题加入账本没有的解释。若问题清单同时提到复盘、流水账或镜头链，"
        "修正事实时也不得把这些结构重新带回正文。只输出修正后的本段小说正文。",
    ])


def build_de_ai_candidate_preserving_expansion_prompt(
    candidate_text: str,
    story_ledger: str,
    *,
    minimum_visible_characters: int,
    maximum_visible_characters: int,
    required_insertions: list[str] | None = None,
) -> str:
    """Ask the prose model to add only ledger-backed detail to an audited span."""

    minimum = max(1, int(minimum_visible_characters or 0))
    maximum = max(minimum, int(maximum_visible_characters or minimum))
    required = [
        str(value).strip()
        for value in (required_insertions or [])
        if str(value).strip()
    ]
    required_rule = (
        "- 本次还必须补回这些源文事实标记："
        + "、".join(required)
        + "。把它们放回账本对应事件，不要写成校对说明。\n"
        if required
        else ""
    )
    return "\n\n".join([
        "下面的候选小说片段已经通过故事事实审计，只是比整章篇幅下限略短。"
        "不得整段重写；必须以候选为不可删除底稿，做一次极小幅保真扩写。",
        "【硬性输出约束】\n"
        f"- 输出完整片段，达到{minimum}至{maximum}个可见字符。\n"
        "- 候选中的每一个非空白字符都必须原样、同序保留；不能删字、换词、改标点、"
        "调换句子或改变对白。只允许在合适位置插入文字。\n"
        f"{required_rule}"
        "- 只插入一至两处短内容，来源必须是事实账本已经明确的现场动作、物件操作或对白信息。"
        "不得新增事件、人物判断、动机、感官、环境、解释、因果或背景。\n"
        "- 不把一个动作拆成执行清单，不复盘线索，不补意义判断，不在片段最后另加总结。",
        f"【不可删除候选】\n{str(candidate_text or '').strip()}",
        f"【可用事实账本】\n{str(story_ledger or '').strip()}",
        "只输出扩写后的完整小说片段，不要说明、清单、Markdown 或审计报告。",
    ])


def build_de_ai_style_repair_prompt(
    chunk_prompt: str,
    audit_issues: list[dict[str, Any]],
    *,
    repair_attempt: int = 1,
    allow_target_shrink: bool = True,
    minimum_target_characters: int | None = None,
    previous_candidate: str = "",
    fidelity_chunk_prompt: str = "",
) -> str:
    """Regenerate a structurally rejected scene while keeping ledger facts."""

    issue_lines = "\n".join(
        f"- {str(item.get('detail') or '').strip()}"
        for item in audit_issues
        if str(item.get("detail") or "").strip()
    ) or "- 上一稿仍有明显的流水账、镜头链或线索复盘。"
    issue_kinds = {
        str(item.get("kind") or "").strip().lower().removeprefix("style:")
        for item in audit_issues
    }
    repair_chunk_prompt = chunk_prompt
    filtered_recap_lines = 0
    ledger_marker = next(
        (
            value
            for value in (
                "【本段宏观叙事单元（只定事实边界，不是逐句大纲）】",
                "【本段账本拍点】",
                "【本段事实账本】",
            )
            if value in chunk_prompt
        ),
        "",
    )
    if "recap" in issue_kinds and ledger_marker:
        prompt_head, marker, ledger_text = chunk_prompt.partition(ledger_marker)
        kept_lines: list[str] = []
        recap_markers = (
            "回顾已知",
            "回顾线索",
            "复盘",
            "梳理已知",
            "逐一回想",
            "现有线索无法解释",
            "已有线索无法解释",
            "已知信息",
            "已有线索",
            "当前状态：已有",
        )
        for line in ledger_text.splitlines():
            stripped = line.strip()
            is_numbered_beat = bool(re.match(r"^\d+\s+\[(?:硬|可选)\]", stripped))
            if is_numbered_beat and any(value in stripped for value in recap_markers):
                filtered_recap_lines += 1
                continue
            if stripped.startswith("结尾锁定"):
                filtered_recap_lines += 1
                continue
            kept_lines.append(line)
        filtered_ledger = "\n".join(kept_lines)

        def filter_required_tokens(match: re.Match[str]) -> str:
            tokens = [
                token.strip()
                for token in match.group(2).split("、")
                if token.strip() and token.strip() != "无"
            ]
            retained = [token for token in tokens if token in filtered_ledger]
            return match.group(1) + ("、".join(retained) or "无")

        prompt_head = re.sub(
            r"(【本段必须原字出现的源文标记】\n)([^\n]*)",
            filter_required_tokens,
            prompt_head,
            count=1,
        )
        repair_chunk_prompt = prompt_head + marker + filtered_ledger

    fidelity_appendix = ""
    fidelity_prompt = str(fidelity_chunk_prompt or "").strip()
    factual_issue_kinds = {"missing", "contradiction", "added", "role", "order"}
    if (
        fidelity_prompt
        and issue_kinds.intersection(factual_issue_kinds)
        and fidelity_prompt != str(chunk_prompt or "").strip()
        and "【后置事实校对附录（不决定正文取舍）】" not in chunk_prompt
    ):
        fidelity_marker = next(
            (
                value
                for value in ("【本段账本拍点】", "【本段事实账本】")
                if value in fidelity_prompt
            ),
            "",
        )
        detailed_ledger = (
            fidelity_prompt.partition(fidelity_marker)[2].strip()
            if fidelity_marker
            else ""
        )
        recap_markers = (
            "回顾已知",
            "回顾线索",
            "复盘",
            "梳理已知",
            "逐一回想",
            "现有线索无法解释",
            "已有线索无法解释",
            "已知信息",
            "已有线索",
            "当前状态：已有",
        )
        appendix_lines: list[str] = []
        for line in detailed_ledger.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if "[可选]" in stripped:
                continue
            if "recap" in issue_kinds and any(
                marker in stripped for marker in recap_markers
            ):
                continue
            if "[硬]" in stripped or stripped.startswith("结尾锁定"):
                appendix_lines.append(line)
        if appendix_lines:
            fidelity_appendix = (
                "【后置事实校对附录（不得逐条展开）】\n"
                "宏观叙事单元决定正文的取舍和颗粒度；本附录只校对人物主体、物件位置与归属、"
                "动作方式、认识状态和先后。宏观单元省略的常规走位、开关门、检查和停顿不必补写；"
                "但正文一旦写到对应事实，不得与附录冲突。严禁按附录编号逐句、逐段展开。\n"
                + "\n".join(appendix_lines)
            )

    target_note = ""
    target_match = re.search(
        r"本段目标为\s*(\d+)\s*至\s*(\d+)\s*个可见字符",
        repair_chunk_prompt,
    )
    if (
        allow_target_shrink
        and target_match
        and issue_kinds.intersection({"recap", "checklist"})
    ):
        old_min = int(target_match.group(1))
        old_max = int(target_match.group(2))
        if "recap" in issue_kinds:
            target_min = max(40, round(old_min * 0.65))
            target_max = max(target_min + 40, round(old_max * 0.75))
        else:
            target_min = max(40, round(old_min * 0.82))
            target_max = max(target_min + 40, round(old_max * 0.9))
        repair_chunk_prompt = (
            repair_chunk_prompt[:target_match.start()]
            + f"本段目标为{target_min}至{target_max}个可见字符"
            + repair_chunk_prompt[target_match.end():]
        )
        target_note = (
            f"本次局部目标已从{old_min}至{old_max}字校准为{target_min}至{target_max}字；"
            "省下的篇幅来自重复复盘或常规步骤，不能另加解释补齐。"
        )
    elif (
        not allow_target_shrink
        and target_match
        and issue_kinds.intersection({"staged", "checklist"})
    ):
        # Detector-guided structural rewrites must still satisfy the inherited
        # whole-chapter floor.  Long-form CLI writers commonly return about
        # four fifths of an explicit Chinese-character target, which made a
        # factually sound, less-staged branch lose solely because it was a few
        # characters short.  Give the generation target modest headroom; the
        # deterministic whole-story length cap and fidelity audit below remain
        # the actual acceptance boundaries.
        old_min = int(target_match.group(1))
        old_max = int(target_match.group(2))
        required_minimum = (
            None
            if minimum_target_characters is None
            else max(0, int(minimum_target_characters))
        )
        if required_minimum is not None:
            target_min = max(old_min, required_minimum)
            target_max = max(
                target_min + 40,
                old_max,
                round(target_min * 1.08),
            )
            target_note = (
                f"本次生成目标按整章实际缺口校准为{target_min}至{target_max}字，"
                "不是统一放大每个片段；不能靠复盘、重复步骤、解释或新增事实凑字。"
            )
        else:
            # Detector-guided local spans do not have the whole chapter's
            # allocation context.  Keep their measured provider-undershoot
            # allowance; their caller enforces the deterministic story floor.
            target_min = max(old_min, round(old_min * 1.18))
            target_max = max(target_min + 40, round(old_max * 1.18))
            target_note = (
                f"本次生成目标从{old_min}至{old_max}字增加到{target_min}至{target_max}字，"
                "仅用于抵消模型常见的篇幅不足；不能靠复盘、重复步骤、解释或新增事实凑字。"
            )
        repair_chunk_prompt = (
            repair_chunk_prompt[:target_match.start()]
            + f"本段目标为{target_min}至{target_max}个可见字符"
            + repair_chunk_prompt[target_match.end():]
        )
    targeted_rules: list[str] = []
    if "recap" in issue_kinds:
        targeted_rules.append(
            "本次命中 recap：前文已经出现的期限、人物、线索、物件去向和因果一律不在本段重新列举，"
            "也不改写成‘这些事/这些线索仍无法解释……’。即使账本把回顾列为[硬]，也只保留回顾后"
            "真正新增的现场动作、选择或发现；全章事实保真不要求保留重复复盘的叙述形式。"
        )
        if filtered_recap_lines:
            targeted_rules.append(
                f"系统已从本段输入中过滤{filtered_recap_lines}条纯复盘账本行；不得自行猜回或补写被过滤内容。"
            )
    if "checklist" in issue_kinds:
        targeted_rules.append(
            "本次命中 checklist：审计指出的普通赶路、上下楼、开关门、换鞋、倒水和逐项检查中，"
            "只允许保留直接造成新局面的至多一个因果动作，其余步骤不得在正文出现，也不能换成"
            "逗号清单塞进一句。路线直接落成‘离开现场’‘回到住处’等结果；账本记录过步骤不等于正文必写。"
        )
    if "preamble" in issue_kinds:
        targeted_rules.append(
            "本次命中 preamble：从人物正在做的事、被打断的动作或一句现场对白切入。日期、钟点、"
            "倒计时、编号和地点仍须准确保留，但应嵌进动作或人物判断，不能连续排成场景坐标。"
            "开头不另列天气、灯光、气味、货架或全景。"
        )
    if "staged" in issue_kinds:
        targeted_rules.append(
            "本次命中 staged：审计指出的整条悬念链只允许保留触发、结果和至多一个不可替代的因果方法，"
            "从触发到结果合计最多两句。等待、每一种声响、寻找工具、调整角度、反复确认和口头报告"
            "不得逐项出现，也不能换成逗号长句。保留账本硬事实，但不要用"
            "‘先、接着、数秒后、渐渐、一点点、停了一下、这才’把因果缝得过分平整。账本只是"
            "核对表，不是句子或段落大纲：不得一条[硬]对应一句或一段；让同一个正在发生的动作、"
            "同一轮被打断的对白同时承载多个相邻硬事实。能随说话动作并入的短对白不要单独成段。"
            "事件先后仍须准确，但只在真正发生转折处显式过渡，不能逐拍替读者报时和验账。"
            "不得让一句短对白单独占段；触发前后的其他事实另随人物正在进行的交锋落下，不能为"
            "覆盖附录而重建完整镜头链。"
        )
    prior = str(previous_candidate or "").strip()
    isolate_rejected_structure = bool(
        prior
        and issue_kinds.intersection({"staged", "checklist", "recap", "preamble"})
    )
    if isolate_rejected_structure:
        prior_block = (
            "【结构重生输入隔离】\n"
            "系统已移除上一稿正文，避免被拒绝的逐拍顺序、执行日志、复盘段落或开场模板"
            "再次成为续写锚点。只依据上方事实账本和审计问题重新落笔；不得猜回被移除的"
            "常规步骤。故事事实由不可变原文的后置审计复核。"
        )
    else:
        prior_block = (
            "【上一稿，仅用于定位被拒结构】\n"
            f"{prior}\n\n"
            "不得沿用上一稿被审计指出的段落切分、逐拍顺序或总结句；"
            "只保留其与账本一致的故事事实。"
            if prior
            else ""
        )
    if target_note:
        targeted_rules.append(target_note)
    targeted_text = "\n".join(f"- {rule}" for rule in targeted_rules)
    return "\n\n".join([
        repair_chunk_prompt,
        fidelity_appendix,
        f"【第{max(1, repair_attempt)}次表达结构重生】\n{issue_lines}",
        "重新依据账本写出完整片段，不对上一稿修修补补。所有[硬]事实、人物归属、条件、因果、"
        "数字与先后必须保留；若审计意见涉及事实错误，事实修正优先级最高。",
        prior_block,
        "用人物正在操作的物件、遭遇的阻碍、选择和对白推进；常规移动与检查可压进一句。"
        "删去成组线索复盘、意义解释、执行日志和顺滑镜头标签。末尾停在账本最后一个现场动作、"
        "对白或发现，不替读者总结。只输出修正后的小说正文。",
        f"【本次命中项的硬约束】\n{targeted_text}" if targeted_text else "",
    ])


def build_de_ai_detector_feedback_repair_prompt(
    original_segment: str,
    story_ledger: str,
    *,
    left_context: str = "",
    right_context: str = "",
    verdict: str = "suspected",
    pass_number: int = 1,
    minimum_visible_characters: int = 0,
) -> str:
    """Rebuild one externally flagged span from facts, never by hand patching prose."""

    source_length = _visible_length(original_segment)
    paragraph_cap = max(3, min(7, round(source_length / 150)))
    minimum_ratio = 0.82 if str(verdict).lower() == "ai" else 0.86
    fidelity_floor = max(
        80,
        round(source_length * minimum_ratio),
        max(0, int(minimum_visible_characters or 0)),
    )
    # Long-form CLI models commonly undershoot an explicit Chinese character
    # target by roughly 20%.  Put that allowance into the first ledger-based
    # draft so the safety path does not have to preserve a short candidate and
    # insert duplicate facts afterwards.
    target_min = max(fidelity_floor, round(fidelity_floor * 1.28))
    target_max = max(target_min + 40, round(source_length * 1.12))
    preserved_context = f"{left_context}\n{right_context}"
    required_tokens = [
        token
        for token in _literal_fidelity_tokens(original_segment)
        if token not in preserved_context
    ]
    literal_tokens = "、".join(required_tokens) or "无"
    boundary_parts: list[str] = []
    if left_context.strip():
        boundary_parts.append(
            "左侧已保留正文（只用于承接，不得复述）：\n" + left_context.strip()
        )
    if right_context.strip():
        boundary_parts.append(
            "右侧已保留正文（只用于收束，不得抢写）：\n" + right_context.strip()
        )
    boundaries = "\n\n".join(boundary_parts) or "无"
    opening_rule = ""
    if not left_context.strip():
        opening_rule = (
            "- 这是全章开头：首段最多承载一个时间定位动作，不得把日期、钟点、倒计时、"
            "地点、信封属性和敲门节奏连续塞进一两句，写成档案式开场。日期、时刻和剩余时间"
            "仍须准确，但要随看手机、赶路、交接或对白分散落下；无署名、无邮票和收件字样可在"
            "递信、验信时露出，不在赶路句中成组盘点。\n"
        )
    return "\n\n".join([
        f"这是第{max(1, pass_number)}次检测反馈修复。外部检测将这一连续区段判为"
        f"{str(verdict).lower()}；依据事实账本整段重生，不看旧句逐句换词。",
        "【事实与边界】\n"
        "- 账本中的人物、物件、数字、条件、对白意图、因果和先后全部保留。\n"
        "- 不新增动作、感官、背景、解释或线索；不把账本备注写进小说。\n"
        "- 物件归属只通过拿取、递交、使用或随身动作自然呈现；不得用‘仍由某人拿着’、"
        "‘始终攥着没有松开’、‘尚未取出’、‘归属未变’等旁白状态声明替账本验账。"
        "没有发生交接时不必额外证明。\n"
        "- 左右两侧正文已经验收为可保留文本，不能改写、复述或提前消耗其事件；同时把它们"
        "当作本章局部节奏参考，沿用其普通动词、段落松紧和对白密度，不照抄句子。\n"
        f"- 本段目标为{target_min}至{target_max}个可见字符；只输出本段正文。",
        "【这类区段的重生规则】\n"
        f"{opening_rule}"
        "- 事实账本只用于核对，不是逐条展开的句子或段落大纲；不得一条[硬]对应一句或一段。"
        "让同一个现场动作或一轮被打断的对白同时承载多个相邻硬事实，短对白能并入说话动作时"
        "不要独立成段。事件先后必须准确，但只在真正改变局面的转折处显式过渡。\n"
        f"- 本区段最多使用{paragraph_cap}个自然段；段落数必须明显少于账本拍点数。不要把检查、"
        "等待、声响、观察、报告和解释分别写成独立小段，也不要用连续单句对白充当镜头切点。"
        "一个自然段可同时容纳动作、回应和新信息，但不能挤成清单句。\n"
        "- 不用日期、钟点、倒计时、地点、陈设连续填写场景坐标；必要数字嵌入人物动作或判断。\n"
        "- 不把悬念写成静默—灯灭—声响—观察—发现—报告—解释的完整镜头脚本。"
        "合并不改变局面的步骤，让动作或对白产生真实打断。\n"
        "- 一条信息已经由动作或对白交代，就往下走；不追加旁白解释，不在段尾复盘线索。\n"
        "- 同一事实、动作或等待状态在本区段只落笔一次；不得为了篇幅换一种说法重复，"
        "持续动作压进一个句子。\n"
        "- 不以日期、钟点和剩余分钟组成开场报时；必要时间信息放进人物赶路、看表或约定中，"
        "开篇先落在一个正在发生的动作上。\n"
        "- 普通动词和具体物件优先。句段长短服从现场，不机械交替，不靠错字、口癖或乱码伪装。\n"
        "- 结尾停在本区段最后一个新增动作、对白或发现，不能替读者总结意义。",
        f"【必须原字出现的标记】\n{literal_tokens}",
        f"【相邻边界】\n{boundaries}",
        f"【本段账本拍点】\n{story_ledger.strip()}",
        "只输出重生后的小说正文，不要标题、说明、清单、Markdown 或检测报告。",
    ])


def build_de_ai_detector_ledger_compression_prompt(
    original_segment: str,
    detailed_ledger: str,
    *,
    is_ending: bool = False,
    preserved_context: str = "",
) -> str:
    """Compress detector-span facts so a redraft is not forced to replay a shot list."""

    target_beats = max(4, min(7, round(_visible_length(original_segment) / 85)))
    required_tokens = [
        token
        for token in _literal_fidelity_tokens(original_segment)
        if token not in preserved_context
    ]
    literal_tokens = "、".join(required_tokens) or "无"
    filtered_lines: list[str] = []
    for line in str(detailed_ledger or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("结尾锁定"):
            continue
        if "[可选]" in stripped:
            # Repeated observation and explicit waiting often encode suspicion,
            # prior knowledge, or elapsed time even when the detailed extractor
            # conservatively labels them atmosphere.  Promote those facts before
            # optional scenery is removed so compression can preserve them.
            consequential_optional_markers = (
                "反复",
                "多次",
                "数次",
                "持续",
                "一直",
                "等待",
                "分钟",
                "小时",
                "观察",
                "查看",
                "盯",
                "留意",
            )
            if not any(marker in stripped for marker in consequential_optional_markers):
                continue
            line = line.replace("[可选]", "[硬]")
            stripped = line.strip()
        if is_ending and any(
            marker in stripped
            for marker in ("已知信息", "已有线索", "当前状态：已有")
        ):
            continue
        filtered_lines.append(line)
    filtered_ledger = "\n".join(filtered_lines).strip()
    return "\n\n".join([
        "把下面的详细事实账本压缩成真正用于重写的短账本。只压缩账本，不写小说正文。",
        "【压缩规则】\n"
        f"- 最终只留{target_beats}个编号拍点；每个拍点可以合并一串服务于同一结果的动作。\n"
        "- 人物、物件归属、数字、条件、因果、对白信息和先后仍须准确；必须原字标记不得丢。\n"
        "- 锁车、走路、开关门、逐次声响、视线转移、摸索、停顿等微动作不单列为[硬]。"
        "若它们不改变局面，合并进相邻结果或省略。\n"
        "- 若持续观察特定出入口、反复检查或一段等待体现人物已有警觉、知情程度、"
        "时间经过或后续反应依据，必须合并进相邻[硬]拍点，不能按普通视线动作删掉。\n"
        "- 删除灯光、气味、陈设等[可选]气氛，不新增原账本没有的事实。\n"
        "- 删除对前文期限、人物、线索和物件去向的复盘；只保留本区段首次发生的新动作、"
        "对白或发现。不要输出人物表、结尾锁定、解释、评价或写作建议。",
        f"【必须原字保留的标记】\n{literal_tokens}",
        f"【待压缩详细账本】\n{filtered_ledger}",
        "输出格式：每行一个“01 [硬] ……”拍点，除此之外不要输出任何内容。",
    ])


def build_de_ai_rewrite_from_ledger_prompt(
    original_text: str,
    story_ledger: str,
    *,
    fidelity_source: str | None = None,
) -> str:
    """Build a full redraft prompt that never exposes the source prose."""

    report = analyze_de_ai_fingerprints(original_text)
    authority_text = str(
        original_text if fidelity_source is None else fidelity_source
    )
    diagnostics = _render_revision_diagnostics(report)
    literal_tokens = "、".join(_literal_fidelity_tokens(authority_text)) or "无"
    authority_character_count = _visible_length(authority_text)
    target_character_min = max(20, round(authority_character_count * 0.95))
    target_character_max = max(
        target_character_min + 40,
        round(authority_character_count * 1.08),
    )
    target_paragraph_min = max(6, round(report["character_count"] / 105))
    target_paragraph_max = max(target_paragraph_min + 4, round(report["character_count"] / 65))
    return "\n\n".join([
        "依据下面的故事账本写出完整中文小说正文。原稿措辞已被隔离，你不能逐句润色；"
        "必须只凭账本重新组织叙述，同时让全部事实、线索、对白意图和事件先后保持不变。",
        DE_AI_FIDELITY_CONTRACT,
        "【篇幅与残留问题】\n"
        f"原章约{report['character_count']}个可见字符、{report['paragraph_count']}段、"
        f"{report['sentence_count']}句；成稿总字符数必须在{target_character_min}至"
        f"{target_character_max}之间，不能逐轮变短。\n"
        f"{diagnostics}\n"
        f"可按现场节拍形成约{target_paragraph_min}至{target_paragraph_max}个长短不齐的自然段，"
        "不要机械凑数。",
        DE_AI_RECONSTRUCTION_METHOD,
        "【账本使用边界】\n"
        "- 账本中标为[硬]的事实都要落入正文；[可选]气氛细节按人物实际注意力取舍，不要整批搬运。"
        "账本的编号、字段名、分号结构和电报式措辞不得出现在成稿。\n"
        "- 只能把账本事实写具体，不能添加账本没有的背景、回忆、动作、感觉、动机、关系或解释。\n"
        "- 不要为了凑篇幅重复同一事实；用视角选择、句法节奏和对白承接形成篇幅。",
        "【成稿质地】\n"
        "- 写成有个人脾气的小说初稿：清楚、可读，但不替读者把每层因果和情绪都讲圆。\n"
        "- 不用天气或全景介绍作固定开场；优先从人物正在处理的东西、期限或麻烦落笔。\n"
        "- 同一段不要凑齐环境、动作、心理、解释四件套。能由下一句对白显出的意思，上一句旁白就留白。\n"
        "- 对白可单独成段，少用完整对白标签；允许符合人物口气的短答、倒装、省略和自我修正。\n"
        "- 叙述用普通而准确的动词，少做漂亮比喻，少用程度副词；关键处可以突然收成很短的一句。\n"
        "- 让人物持续处理眼前的期限、物件或麻烦。静态环境一次最多带出一个有效信息，随后立刻回到动作或对白；"
        "不要连续盘点灯光、气味、陈设和外貌。\n"
        "- 不要追求句句精致、段段闭合。局部重复只有在人物口气或紧张节拍确实需要时保留。",
        "【节奏示范，只学组织方式，不得复用字句或情节】\n"
        "他绕过去，门还开着。\n\n"
        "“人呢？”\n\n"
        "没人答。桌上那杯水倒是热的。\n\n"
        "他站了几秒，把后半句话咽回去。先办眼前的事。",
        f"【必须在正文中原字出现的标记】\n{literal_tokens}",
        "【输出纪律】\n"
        "只输出完整正文，不要标题、账本、说明、批注、评分、修改清单或 Markdown。",
        f"【故事账本】\n{story_ledger}",
    ])

# ---------------------------------------------------------------------------
# COMPLETE SYSTEM PROMPT ASSEMBLY
# ---------------------------------------------------------------------------

def build_anti_ai_system_prompt() -> str:
    """Build the full de-AI writing guidelines for inclusion in system prompts."""
    tier1_flat = []
    for _cat, words in TIER1_BANNED_WORDS.items():
        tier1_flat.extend(words)
    tier1_str = "、".join(tier1_flat)

    return "\n\n".join([
        "【去AI味写作规范 — 必须严格遵守】",
        f"一级禁用词（出现即替换）：{tier1_str}",
        "",
        ALL_AI_PATTERNS,
        "",
        DE_AI_3_PASS_METHOD,
        "",
        STACKED_WRITING_RULE,
        "",
        "【章末总结体检测 — 禁止以下结尾方式】\n"
        "- 总结性感悟\n- 升华式感叹\n- 哲理式收尾\n- 伏笔式预告\n"
        "正确做法：章尾用动作、对话或悬念收束，让情节本身制造余韵。",
        "",
        EMOTION_REPLACEMENT_TABLE,
        "",
        SCENE_REWRITE_EXAMPLES,
        "",
        QUICK_SELF_CHECK,
    ])


def build_de_ai_rewrite_prompt(original_text: str) -> str:
    """Build an input-aware, fidelity-first de-AI rewrite prompt."""
    report = analyze_de_ai_fingerprints(original_text)
    diagnostics = _render_revision_diagnostics(report)
    target_paragraph_min = max(6, round(report["character_count"] / 105))
    target_paragraph_max = max(target_paragraph_min + 4, round(report["character_count"] / 65))
    return "\n\n".join([
        "把下面的中文小说正文重新写成一篇事实完全相同、措辞与句法重新生成的小说成稿。"
        "这是整章表达重写，不是续写、缩写、扩写或剧情重构；目标是摆脱原稿的句子骨架，而非逐词同义替换。",
        DE_AI_FIDELITY_CONTRACT,
        "【本轮输入诊断】\n"
        f"原文约{report['character_count']}个可见字符，{report['paragraph_count']}段，"
        f"{report['sentence_count']}句，平均句长{report['average_sentence_length']}字。\n"
        f"{diagnostics}\n"
        f"- 本章重写后可按现场节拍形成约{target_paragraph_min}至{target_paragraph_max}个长短不齐的自然段；"
        "这是节奏参照，不要机械凑数。",
        DE_AI_RECONSTRUCTION_METHOD,
        "【交稿前硬检查】\n"
        "- 若多数句子仍能与原文逐句对齐，说明只是润色，必须从事实账本重新写一遍。\n"
        "- 若人物名反复占据句首，改用承接、省略主语、物件或对白切入；不得因此造成指代不清。\n"
        "- 若段落长度、句式或对白标签呈规律轮换，按真实叙事需要重新合并或拆开。",
        "【输出纪律】\n"
        "- 只输出完整修订正文；不要标题、前言、说明、批注、评分、修改清单或Markdown代码块。\n"
        "- 保留原文必要的空行和引号；可按场景拍点调整分段，但不得打乱事件顺序。\n"
        "- 不要复述本提示词，不要声称已经完成检查。",
        f"【原文】\n{original_text}",
    ])


def build_stacked_writing_fix_prompt(original_text: str) -> str:
    """Build a prompt specifically targeting stacked/ layered writing patterns."""
    return "\n\n".join([
        STACKED_WRITING_RULE,
        "",
        "请将以下文本中的堆叠式描写合并为织入式写法："
        "发生、感知、反应三个维度融入同一段连续正文。",
        "不要删除情绪细节，只是合并同一瞬间的重复描写。",
        "",
        f"【原文】\n{original_text}",
    ])
