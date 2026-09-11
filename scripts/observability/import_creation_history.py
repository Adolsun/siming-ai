"""Read saved creation turns without writing to Siming, then import into local Phoenix.

Historical records are NOT full API requests. Child timestamps are zero-duration
ordering markers, not measured latency. This is stated in every child span.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def identity(value, size):
    return hashlib.sha256(value.encode()).digest()[:size]


def unix_ns(value):
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return int(date.timestamp() * 1_000_000_000)


def attribute(key, value):
    if isinstance(value, bool):
        payload = AnyValue(bool_value=value)
    elif isinstance(value, int):
        payload = AnyValue(int_value=value)
    else:
        payload = AnyValue(string_value=str(value))
    return KeyValue(key=key, value=payload)


def read_turn(database, message_id):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        for table in ("system_assistant_messages", "assistant_messages"):
            row = db.execute(
                f"SELECT * FROM {table} WHERE id = ?", (message_id,)
            ).fetchone()
            if row:
                turn = json.loads(row["payload_json"])["creation_agent_turn"]
                return dict(row), turn
    raise ValueError("No recorded creation turn found for the supplied message ID")


def build_trace(row, turn, project):
    trace_id = identity("siming-history:" + row["id"], 16)
    root_id = identity(row["id"] + ":root", 8)
    start, end = unix_ns(row["created_at"]), unix_ns(row["updated_at"])
    messages = turn["messages"]
    metrics = turn.get("prompt_metrics", [])
    user = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
    request = ExportTraceServiceRequest()
    resource = request.resource_spans.add()
    resource.resource.attributes.extend(
        [
            attribute("openinference.project.name", project),
            attribute("service.name", "siming-history-import"),
        ]
    )
    scope = resource.scope_spans.add()
    scope.scope.name = "siming.creation.history"
    failed_tools = []
    common = {
        "session.id": turn.get("session_id", ""),
        "siming.message_id": row["id"],
        "siming.capture_source": "saved_history_partial",
        "siming.full_api_request_available": False,
    }

    def span(name, key, kind, attrs, parent_id=root_id, order=0, error=""):
        # Each historical child gets an ordering marker. Zero duration is unknown.
        marker = start + order * 1_000
        item = Span(
            trace_id=trace_id,
            span_id=identity(row["id"] + key, 8),
            parent_span_id=parent_id,
            name=name,
            kind=Span.SPAN_KIND_INTERNAL,
            start_time_unix_nano=marker,
            end_time_unix_nano=marker,
            status=Status(
                code=Status.STATUS_CODE_ERROR if error else Status.STATUS_CODE_OK,
                message=error,
            ),
        )
        item.attributes.extend(
            attribute(k, v)
            for k, v in {
                **common,
                "openinference.span.kind": kind,
                "siming.latency_available": False,
                "siming.timestamp_note": "仅用于排列历史调用顺序；0 ms 表示耗时未知，不是真实耗时。",
                **attrs,
            }.items()
        )
        scope.spans.append(item)
        return item.span_id

    iteration = 0
    calls = {}
    for position, message in enumerate(messages):
        if message.get("role") == "assistant":
            iteration += 1
            metric = metrics[iteration - 1] if iteration <= len(metrics) else {}
            attrs = {
                "llm.model_name": turn.get("model", "unknown"),
                "input.mime_type": "application/json",
                "input.value": json_text(
                    {
                        "说明": "历史记录不含完整 API 请求。下列只是已保存的本轮消息，不能据此还原实际请求。",
                        "缺失": [
                            "实际请求体",
                            "完整系统提示词",
                            "之前回合的上下文",
                            "每步实际发送的工具 Schema",
                        ],
                        "recorded_current_turn_prefix": messages[:position],
                    }
                ),
                "output.mime_type": "application/json",
                "output.value": json_text(message),
                "llm.output_messages.0.message.role": "assistant",
                "llm.output_messages.0.message.content": message.get("content", "")
                or "",
                "metadata": json_text(
                    {"prompt_metrics": metric, "history_message_index": position}
                ),
            }
            if metric.get("usage_reported") and isinstance(
                metric.get("prompt_tokens"), int
            ):
                attrs["llm.token_count.prompt"] = metric["prompt_tokens"]
            for key in (
                "tool_count",
                "tool_schema_estimated_tokens",
                "system_prompt_estimated_tokens",
                "request_estimated_tokens",
            ):
                if key in metric:
                    attrs["siming." + key] = metric[key]
            for index, call in enumerate(message.get("tool_calls", [])):
                function = call.get("function", {})
                prefix = f"llm.output_messages.0.message.tool_calls.{index}.tool_call.function."
                attrs[prefix + "name"] = function.get("name", "")
                attrs[prefix + "arguments"] = function.get("arguments", "")
            parent = span(
                f"{iteration:02d} 模型 · {metric.get('phase', 'unknown')}（历史／耗时未知）",
                f":model:{position}",
                "LLM",
                attrs,
                order=position + 1,
            )
            for call in message.get("tool_calls", []):
                calls[call["id"]] = (parent, call["function"], iteration)
        elif message.get("role") == "tool":
            call_id = message.get("tool_call_id", "")
            parent, function, step = calls.get(call_id, (root_id, {}, iteration))
            raw = message.get("content", "")
            try:
                result = json.loads(raw)
            except (TypeError, ValueError):
                result = {}
            failed = result.get("status") in {"error", "denied", "failed"}
            name = function.get("name", "unknown_tool")
            if failed:
                failed_tools.append(
                    {
                        "step": step,
                        "tool": name,
                        "arguments": function.get("arguments"),
                        "result": result,
                    }
                )
            span(
                f"{step:02d} {name}（历史／耗时未知）",
                ":tool:" + call_id,
                "TOOL",
                {
                    "tool.name": name,
                    "tool.parameters": function.get("arguments", "{}"),
                    "input.mime_type": "application/json",
                    "input.value": function.get("arguments", "{}"),
                    "output.mime_type": "application/json",
                    "output.value": raw,
                    "siming.tool_call_id": call_id,
                },
                parent_id=parent,
                order=position + 1,
                error=result.get("detail", "工具失败") if failed else "",
            )

    root = Span(
        trace_id=trace_id,
        span_id=root_id,
        name=f"立项：{user}（历史还原／请求不完整）",
        kind=Span.SPAN_KIND_INTERNAL,
        start_time_unix_nano=start,
        end_time_unix_nano=end,
        status=Status(
            code=Status.STATUS_CODE_ERROR if failed_tools else Status.STATUS_CODE_OK,
            message=f"{len(failed_tools)} 个工具失败；模型回合已结束"
            if failed_tools
            else "",
        ),
    )
    root.attributes.extend(
        attribute(k, v)
        for k, v in {
            **common,
            "openinference.span.kind": "AGENT",
            "input.value": user,
            "output.value": row["content"],
            "siming.timestamp_note": "根节点使用消息行的创建/更新时间；子节点无逐步时间记录。",
            "metadata": json_text(
                {
                    "outcome": turn.get("outcome"),
                    "prompt_metrics": metrics,
                    "failed_tools": failed_tools,
                    "missing": "完整 API 请求体与每步实际耗时",
                }
            ),
        }.items()
    )
    scope.spans.insert(0, root)
    return request, {
        "trace_id": trace_id.hex(),
        "project": project,
        "model_steps": iteration,
        "tool_calls": len(calls),
        "failed_tools": len(failed_tools),
        "reported_input_tokens": sum(
            m["prompt_tokens"] for m in metrics if m.get("usage_reported")
        ),
        "full_api_request_available": False,
        "per_step_latency_available": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:6006/v1/traces")
    parser.add_argument("--project", default="siming-creation-history")
    args = parser.parse_args()
    url = urlsplit(args.endpoint)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.query
    ):
        parser.error(
            "History import only accepts a loopback HTTP collector without credentials"
        )
    request, summary = build_trace(
        *read_turn(args.database, args.message_id), args.project
    )
    http = Request(
        args.endpoint,
        data=request.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
    )
    with build_opener(ProxyHandler({})).open(http, timeout=30) as response:
        response.read()
    print(json_text(summary))


if __name__ == "__main__":
    main()
