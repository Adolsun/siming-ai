"""Deterministic safety checks for de-AI chapter revision candidates."""

from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from typing import Any

from ..prompts.anti_ai_prompts import analyze_de_ai_fingerprints

_VISIBLE_CHAR_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")

# Optional structural regeneration is expensive and can create fresh factual
# drift.  Two independently audited branches are enough to find an improvement
# while keeping API/CLI preview latency bounded.
DE_AI_STRUCTURAL_REPAIR_ATTEMPTS = 2
DE_AI_STRUCTURAL_OUTPUT_ATTEMPTS = 2
_NUMBER_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)?(?:%|％|年|月|日|天|点|时|分|秒|岁|章|层|楼|号|"
    r"公里|千米|米|厘米|元|块|万|千|百|次|个|人|页|封|把|枚|颗|瓶|杯)?"
)
_CHINESE_NUMBER_TOKEN_RE = re.compile(
    r"[零〇一二两三四五六七八九十百千万]+(?:年|月|日|天|点|时|分|秒|岁|章|层|楼|号|"
    r"公里|千米|米|厘米)"
)
_IDENTIFIER_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9_-]{1,}(?![A-Za-z0-9])")
_DIALOGUE_OPEN_RE = re.compile(r"[“「『\"]")
_OUTPUT_WRAPPER_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:以下是|改写后|修订后|去除AI味后|去除 AI 味后|修改后的正文|修订正文)"
)
_AGENT_CHATTER_RE = re.compile(
    r"(?:I\s+(?:cannot|can't)\s+read\s+the\s+task\s+file|"
    r"I(?:'ll|\s+will)\s+read\s+the\s+task\s+file|"
    r"permission\s+restrictions|outside\s+the\s+allowed\s+directories|"
    r"(?:无法|不能)读取(?:该|这个)?任务文件|请(?:检查|提供)任务文件)",
    re.IGNORECASE,
)
_CHUNK_TARGET_RE = re.compile(r"本段目标为\s*(\d+)\s*至\s*(\d+)\s*个可见字符")


def count_de_ai_visible_characters(value: str) -> int:
    """Count the same CJK/alphanumeric characters used by revision guards."""

    return len(_VISIBLE_CHAR_RE.findall(value or ""))


def is_de_ai_structural_branch_repairable(
    audit: dict[str, Any],
    *,
    missing_protected_tokens: list[str] | tuple[str, ...] = (),
    max_fact_issues: int = 3,
) -> bool:
    """Reject a style-repair branch that drifted too far from the story.

    Structural regeneration is optional: the caller already owns a faithful
    baseline candidate.  A branch with many fresh fact errors should be
    discarded and regenerated from that baseline, not consume several model
    turns trying to rescue prose whose story state has broadly diverged.
    """

    if not isinstance(audit, dict) or not audit.get("valid"):
        return False
    issues = [item for item in audit.get("issues", []) if isinstance(item, dict)]
    if not audit.get("passed") and not issues:
        return False
    identities = {
        (
            int(item.get("chunk") or 0),
            str(item.get("kind") or ""),
            str(item.get("detail") or "").strip(),
        )
        for item in issues
    }
    missing = {
        str(token).strip()
        for token in missing_protected_tokens
        if str(token).strip()
    }
    return len(identities) + len(missing) <= max(0, int(max_fact_issues))


def parse_de_ai_chunk_target(value: str) -> tuple[int, int] | None:
    """Read the bounded visible-character target embedded in a chunk prompt."""

    match = _CHUNK_TARGET_RE.search(str(value or ""))
    if not match:
        return None
    minimum, maximum = (int(match.group(1)), int(match.group(2)))
    if minimum <= 0 or maximum < minimum:
        return None
    return minimum, maximum


def de_ai_chunk_length_rank(
    visible_length: int,
    target: tuple[int, int] | None,
) -> tuple[int, int, int]:
    """Rank generated spans without letting a worse retry replace a better one.

    A value inside the requested interval wins. Otherwise the closest value
    wins, with a longer span breaking equal-distance ties because long-form
    de-AI rewrites are much more likely to fail by shrinking than expanding.
    """

    length = max(0, int(visible_length or 0))
    if target is None:
        return (0, 0, -length)
    minimum, maximum = target
    if minimum <= length <= maximum:
        return (0, 0, -length)
    distance = minimum - length if length < minimum else length - maximum
    return (1, distance, -length)


def de_ai_style_issue_novelty(
    issues: list[dict[str, Any]],
    historical_issues: list[dict[str, Any]],
) -> tuple[int, int]:
    """Measure structural regressions against issues already targeted.

    A repair that clears the named problem but creates a new problem elsewhere
    must not tie with the original rejected branch merely because both contain
    the same number of findings.
    """

    historical_kinds = {
        str(item.get("kind") or "").strip().lower().removeprefix("style:")
        for item in historical_issues
        if isinstance(item, dict)
    }
    historical_pairs = {
        (
            int(item.get("chunk") or 0),
            str(item.get("kind") or "").strip().lower().removeprefix("style:"),
        )
        for item in historical_issues
        if isinstance(item, dict)
    }
    novel_pairs = 0
    novel_kinds = 0
    for item in issues:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower().removeprefix("style:")
        try:
            chunk = int(item.get("chunk") or 0)
        except (TypeError, ValueError):
            chunk = 0
        if (chunk, kind) not in historical_pairs:
            novel_pairs += 1
        if kind not in historical_kinds:
            novel_kinds += 1
    return novel_kinds, novel_pairs


_DE_AI_STYLE_ISSUE_WEIGHTS = {
    "recap": 3,
    "exposition": 3,
    "preamble": 3,
    "staged": 3,
    "uniform": 3,
    "camera": 2,
    "stock": 2,
    "checklist": 1,
}


def de_ai_style_issue_rank(
    issues: list[dict[str, Any]],
    historical_issues: list[dict[str, Any]],
) -> tuple[int, int, int, int]:
    """Rank remaining structural defects before penalising issue migration.

    A repair with one newly surfaced defect is still materially better than a
    branch retaining three familiar defects.  Novelty is therefore a tie-break
    after issue count and severity, not a reason to preserve known machine-like
    structure merely because the auditor has already named it.
    """

    normalized = [item for item in issues if isinstance(item, dict)]
    novel_kinds, novel_pairs = de_ai_style_issue_novelty(
        normalized,
        historical_issues,
    )
    severity = sum(
        _DE_AI_STYLE_ISSUE_WEIGHTS.get(
            str(item.get("kind") or "").strip().lower().removeprefix("style:"),
            2,
        )
        for item in normalized
    )
    return len(normalized), severity, novel_kinds, novel_pairs


def _protected_tokens(value: str) -> list[str]:
    tokens = _NUMBER_TOKEN_RE.findall(value or "")
    tokens.extend(_CHINESE_NUMBER_TOKEN_RE.findall(value or ""))
    tokens.extend(_IDENTIFIER_RE.findall(value or ""))
    # Stable order makes API diagnostics and tests reproducible.
    return list(dict.fromkeys(tokens))


def assess_de_ai_revision(
    source: str,
    rewritten: str,
    *,
    min_length_ratio: float = 0.9,
    require_substantial_revision: bool = True,
) -> dict[str, Any]:
    """Assess obvious truncation, expansion, wrapper, and fact-token loss.

    This is a guardrail, not a semantic judge.  Ambiguous literary decisions
    stay with the model and the author's preview; only high-confidence damage
    causes rejection.
    """

    original = str(source or "")
    candidate = str(rewritten or "").strip()
    original_length = count_de_ai_visible_characters(original)
    rewritten_length = count_de_ai_visible_characters(candidate)
    original_platform_characters = len(re.sub(r"\s", "", original))
    rewritten_platform_characters = len(re.sub(r"\s", "", candidate))
    length_ratio = rewritten_length / max(1, original_length)
    source_similarity = SequenceMatcher(
        None,
        original,
        candidate,
        autojunk=False,
    ).ratio()

    issues: list[dict[str, Any]] = []
    bounded_min_ratio = max(0.5, min(float(min_length_ratio), 1.0))
    if length_ratio < bounded_min_ratio:
        issues.append({
            "code": "excessive_shrinkage",
            "detail": f"候选稿仅保留原文约{round(length_ratio * 100)}%的篇幅",
        })
    if original_length >= 100 and length_ratio > 1.35:
        issues.append({
            "code": "excessive_expansion",
            "detail": f"候选稿扩展到原文约{round(length_ratio * 100)}%，可能新增了内容",
        })
    minimum_platform_characters = 0
    if original_platform_characters >= 2_000:
        minimum_platform_characters = max(
            2_000,
            round(original_platform_characters * 0.95),
        )
        if rewritten_platform_characters < minimum_platform_characters:
            issues.append({
                "code": "chapter_word_count_floor",
                "detail": (
                    f"候选稿只有{rewritten_platform_characters}字，低于本章保留门槛"
                    f"{minimum_platform_characters}字"
                ),
            })
    if (
        require_substantial_revision
        and original_length >= 500
        and source_similarity > 0.9
    ):
        issues.append({
            "code": "insufficient_revision",
            "detail": (
                f"候选稿与原文仍有约{round(source_similarity * 100)}%的逐字结构重合，"
                "尚未完成整章表达重写"
            ),
        })

    protected_tokens = _protected_tokens(original)
    missing_tokens = [token for token in protected_tokens if token not in candidate]
    if missing_tokens:
        issues.append({
            "code": "missing_fact_tokens",
            "detail": "候选稿遗漏了数字或专有标记：" + "、".join(missing_tokens[:8]),
            "tokens": missing_tokens,
        })

    source_dialogue_count = len(_DIALOGUE_OPEN_RE.findall(original))
    candidate_dialogue_count = len(_DIALOGUE_OPEN_RE.findall(candidate))
    minimum_dialogue_count = math.ceil(source_dialogue_count * 0.5)
    if source_dialogue_count >= 2 and candidate_dialogue_count < minimum_dialogue_count:
        issues.append({
            "code": "dialogue_loss",
            "detail": "候选稿丢失了大段对白结构",
        })

    first_line = candidate.splitlines()[0].strip() if candidate else ""
    if _OUTPUT_WRAPPER_RE.match(first_line):
        issues.append({
            "code": "output_wrapper",
            "detail": "候选稿包含模型说明而不是纯正文",
        })
    if _AGENT_CHATTER_RE.search(candidate):
        issues.append({
            "code": "agent_chatter",
            "detail": "候选稿混入了本机 Agent 的工具或权限提示",
        })

    source_report = analyze_de_ai_fingerprints(original)
    candidate_report = analyze_de_ai_fingerprints(candidate)
    source_signal_count = sum(item["count"] for item in source_report["phrase_groups"])
    candidate_signal_count = sum(item["count"] for item in candidate_report["phrase_groups"])
    return {
        "accepted": not issues,
        "issues": issues,
        "original_visible_characters": original_length,
        "rewritten_visible_characters": rewritten_length,
        "original_platform_characters": original_platform_characters,
        "rewritten_platform_characters": rewritten_platform_characters,
        "minimum_platform_characters": minimum_platform_characters,
        "length_ratio": round(length_ratio, 3),
        "source_similarity": round(source_similarity, 3),
        "protected_token_count": len(protected_tokens),
        "missing_protected_tokens": missing_tokens,
        "source_fingerprint_hits": source_signal_count,
        "rewritten_fingerprint_hits": candidate_signal_count,
    }


def revision_rejection_message(assessment: dict[str, Any]) -> str:
    details = [str(item.get("detail") or "") for item in assessment.get("issues", [])]
    summary = "；".join(item for item in details if item)
    return (
        "候选稿未通过全部系统审核，必须保留原文且不得自动采用；"
        "候选稿仍应交给用户对照预览："
        f"{summary or '候选稿未通过保真检查'}"
    )


def _parse_de_ai_audit(
    value: Any,
    *,
    chunk_count: int,
    allowed_kinds: set[str],
    audit_label: str,
) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {
            "valid": False,
            "passed": False,
            "issues": [{
                "chunk": 0,
                "kind": "audit",
                "detail": f"{audit_label}没有返回有效 JSON",
            }],
        }
    if not isinstance(payload, dict):
        return {
            "valid": False,
            "passed": False,
            "issues": [{
                "chunk": 0,
                "kind": "audit",
                "detail": f"{audit_label}返回的不是 JSON 对象",
            }],
        }

    if not isinstance(payload.get("passed"), bool) or not isinstance(
        payload.get("issues"),
        list,
    ):
        return {
            "valid": False,
            "passed": False,
            "issues": [{
                "chunk": 0,
                "kind": "audit",
                "detail": f"{audit_label}缺少布尔 passed 或数组 issues 字段",
            }],
        }

    normalized_issues: list[dict[str, Any]] = []
    raw_issues = payload.get("issues")
    malformed_issue = False
    for item in raw_issues:
        if not isinstance(item, dict):
            malformed_issue = True
            continue
        try:
            chunk = int(item.get("chunk") or 0)
        except (TypeError, ValueError):
            chunk = 0
        kind = str(item.get("kind") or "").strip().lower()
        detail = str(item.get("detail") or "").strip()
        if (
            not 1 <= chunk <= max(1, chunk_count)
            or kind not in allowed_kinds
            or not detail
        ):
            malformed_issue = True
            continue
        normalized_issues.append({
            "chunk": chunk,
            "kind": kind,
            "detail": detail,
        })

    if malformed_issue:
        return {
            "valid": False,
            "passed": False,
            "issues": [{
                "chunk": 0,
                "kind": "audit",
                "detail": f"{audit_label}包含无法定位的问题项",
            }],
        }

    passed = payload.get("passed") is True and not normalized_issues
    if payload.get("passed") != (not normalized_issues):
        return {
            "valid": False,
            "passed": False,
            "issues": [{
                "chunk": 0,
                "kind": "audit",
                "detail": f"{audit_label}的 passed 与 issues 相互矛盾",
            }],
        }
    return {
        "valid": True,
        "passed": passed,
        "issues": normalized_issues,
    }


def parse_de_ai_fidelity_audit(value: Any, *, chunk_count: int) -> dict[str, Any]:
    """Parse and normalize the model's bounded semantic-audit JSON."""

    return _parse_de_ai_audit(
        value,
        chunk_count=chunk_count,
        allowed_kinds={"missing", "contradiction", "added", "role", "order"},
        audit_label="语义保真审计",
    )


def parse_de_ai_style_audit(value: Any, *, chunk_count: int) -> dict[str, Any]:
    """Parse and normalize the model's bounded expression-structure audit."""

    return _parse_de_ai_audit(
        value,
        chunk_count=chunk_count,
        allowed_kinds={
            "recap",
            "checklist",
            "preamble",
            "staged",
            "camera",
            "exposition",
            "uniform",
            "stock",
        },
        audit_label="表达结构审计",
    )
