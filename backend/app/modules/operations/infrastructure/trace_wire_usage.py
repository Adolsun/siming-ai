"""Bounded counter-only inspection, including when content recording is disabled."""

import json

from ..application.trace_metrics import safe_usage


class WireUsage:
    def __init__(self, trace, span_id, media):
        self.trace, self.span_id, self.media = trace, span_id, media
        self.buffer = bytearray()
        self.overflow = False

    def feed(self, chunk):
        for start in range(0, len(chunk), 8192):
            self.buffer.extend(chunk[start : start + 8192])
            if self.media == "text/event-stream":
                while b"\n" in self.buffer:
                    line, _, rest = self.buffer.partition(b"\n")
                    self.buffer = bytearray(rest)
                    if not self.overflow and line.startswith(b"data:"):
                        self._read(line[5:].strip())
                    self.overflow = False
            if len(self.buffer) > 65536:
                self.buffer.clear()
                self.overflow = True

    def finish(self):
        if self.media != "text/event-stream" and not self.overflow:
            self._read(self.buffer)

    def _read(self, raw):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict):
                return
            for candidate in (value, value.get("response"), value.get("message")):
                if isinstance(candidate, dict) and isinstance(candidate.get("usage"), dict):
                    usage = safe_usage(candidate["usage"])
                    if usage:
                        self.trace.emit(
                            "usage",
                            {
                                "usage": usage,
                                "usage_source": "provider_reported",
                                "span_id": self.span_id,
                            },
                        )
        except (ValueError, UnicodeError, RecursionError):
            pass
