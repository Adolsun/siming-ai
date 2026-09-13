"""Only provider-declared numeric usage is projected into summary diagnostics."""

from .trace_capture import active_trace

_COUNTERS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "cached_tokens",
        "reasoning_tokens",
    }
)
_DETAILS = frozenset(
    {
        "prompt_tokens_details",
        "completion_tokens_details",
        "input_tokens_details",
        "output_tokens_details",
    }
)


def safe_usage(value: dict) -> dict:
    output = {}
    for key, item in value.items():
        if (
            key in _COUNTERS
            and isinstance(item, (int, float))
            and not isinstance(item, bool)
            and item >= 0
        ):
            output[key] = item
        elif key in _DETAILS and isinstance(item, dict):
            output[key] = safe_usage(item)
    return output


def record_usage(value) -> None:
    trace = active_trace()
    if not trace or not isinstance(value, dict) or not isinstance(value.get("usage"), dict):
        return
    usage = safe_usage(value["usage"])
    if usage:
        trace.emit("usage", {"usage": usage, "usage_source": "provider_reported"})
