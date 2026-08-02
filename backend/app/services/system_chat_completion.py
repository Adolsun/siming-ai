"""Open-ended system conversation independent from creation tool registration."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.services.deepseek_system_chat import stream_deepseek_system_chat

_logger = logging.getLogger(__name__)


def _system_context(context: dict[str, Any]) -> str:
    parts: list[str] = []
    blueprints = context.get("blueprints")
    if isinstance(blueprints, list) and blueprints:
        titles = [item.get("title", "未知") for item in blueprints[:3] if isinstance(item, dict)]
        parts.append(f"当前有{len(blueprints)}个新书方案：{'、'.join(titles)}")
    if context.get("sessionId"):
        parts.append("有一个活跃的创作会话")
    brief = context.get("brief")
    if brief:
        parts.append(f"用户的创作设想：{str(brief)[:200]}")
    imported = context.get("importedFiles")
    if not isinstance(imported, list):
        legacy = context.get("importedFile")
        imported = [legacy] if isinstance(legacy, dict) else []
    descriptions = [
        f"{item.get('name', '未知')}（{item.get('length', 0)}字）"
        for item in imported[:3]
        if isinstance(item, dict)
    ]
    if descriptions:
        parts.append(f"用户刚导入了文件：{'、'.join(descriptions)}")
    return "\n".join(parts) if parts else "当前没有任何特殊上下文。"


def _system_prompt(model_identity: str, context_desc: str, history_text: str) -> str:
    return (
        f"你是司命，一个专业的中文小说创作助手。你正在和用户进行系统级对话（没有绑定具体作品）。\n"
        f"当前执行模型：{model_identity}。\n\n"
        f"## 当前上下文\n{context_desc}\n\n"
        f"## 近期对话\n{history_text}\n\n"
        "## 你的能力\n"
        "1. 帮用户创建新小说项目（通过新书立项流程）\n"
        "2. 管理已有作品列表\n"
        "3. 导入文件为新作品\n"
        "4. 基于参考文件写新书\n"
        "5. 回答关于小说创作的问题\n\n"
        "## 回复原则\n"
        "- 你在司命内部工作，不要把自己介绍成 OpenCode、代码助手或软件工程 Agent\n"
        "- 默认始终使用中文；除非用户明确要求，否则不要用英文回复\n"
        "- 不要自行寻找 requirements.md、代码仓库任务或编程配置，也不要讨论当前工作目录\n"
        "- 用户问当前模型时，直接依据“当前执行模型”回答，不要回避\n"
        "- 根据上下文理解用户的真实意图，不要死板地匹配关键词\n"
        "- 如果用户在表达不满或困惑，理解他们的情绪并给出有帮助的回应\n"
        "- 如果用户问了一个问题，直接回答\n"
        "- 如果用户想做某件事，告诉他们怎么操作（或直接帮他们做）\n"
        "- 回复简洁自然，不要用机器人式的固定格式\n"
        "- 如果不确定用户意图，可以反问确认\n\n"
        "## 输出格式\n"
        "直接回复用户的消息，不要JSON，不要Markdown代码块。"
    )


async def complete_system_chat(
    *,
    message: str,
    context: dict[str, Any],
    model: str | None,
    gateway: Any,
    generic_completion: Callable[..., Awaitable[str]],
    extra_body: dict[str, Any] | None,
) -> dict[str, Any]:
    history = context.get("history")
    recent = history[-6:] if isinstance(history, list) else []
    history_text = "\n".join([
        f"{'用户' if item.get('role') == 'user' else '司命'}：{str(item.get('content', ''))[:200]}"
        for item in recent
        if isinstance(item, dict)
    ])
    try:
        provider, model_name = gateway.model_identity(model)
        model_identity = f"{provider}:{model_name}"
    except Exception:
        provider = (model or "").split(":", 1)[0].lower()
        model_identity = "司命系统设置中的默认模型"
    messages = [
        {"role": "system", "content": _system_prompt(model_identity, _system_context(context), history_text)},
        {"role": "user", "content": message},
    ]
    try:
        diagnostics: dict[str, Any] = {}
        if provider == "deepseek":
            reply, diagnostics = await stream_deepseek_system_chat(
                messages=messages, model=model, extra_body=extra_body,
            )
        else:
            reply = (await generic_completion(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=800,
                retry=0,
                activity_message="司命正在组织回复",
            )).strip()
        if not reply:
            raise RuntimeError("没有收到模型的文字回复")
    except Exception as exc:
        _logger.warning("System chat failed: %s", exc, exc_info=True)
        detail = str(exc).strip() or f"({type(exc).__name__})"
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise RuntimeError(
            f"当前选择的模型 {model_identity} 调用失败：{detail}"
            "。请在系统设置中点击“测试本机 CLI”查看登录、模型或额度状态。"
        ) from exc
    return {"reply": reply, "diagnostics": diagnostics}
