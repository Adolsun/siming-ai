"""Regression tests for DeepSeek reasoning/content stream handling."""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ai.deepseek_adapter import DeepSeekAdapter
from app.core.exceptions import LLMError


def _chunk(*, content=None, reasoning_content=None, choices=True):
    if not choices:
        return SimpleNamespace(choices=[])
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _async_stream(*chunks):
    async def generate():
        for chunk in chunks:
            yield chunk

    return generate()


class DeepSeekStreamingTest(unittest.TestCase):
    @staticmethod
    def _adapter_with_stream(*chunks):
        adapter = DeepSeekAdapter(api_key="sk-test")
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_async_stream(*chunks)
        )
        adapter._get_client = MagicMock(return_value=client)
        return adapter

    def test_stream_ignores_usage_chunks_without_choices(self):
        adapter = self._adapter_with_stream(
            _chunk(choices=False),
            _chunk(content="final answer"),
        )

        async def collect():
            return [part async for part in adapter.stream_chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                model="deepseek-v4-flash",
            )]

        self.assertEqual(asyncio.run(collect()), ["final answer"])
        create = adapter._get_client.return_value.chat.completions.create
        self.assertEqual(
            create.await_args.kwargs["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    def test_stream_preserves_explicit_thinking_preference(self):
        adapter = self._adapter_with_stream(
            _chunk(reasoning_content="thinking"),
            _chunk(content="final answer"),
        )

        async def collect():
            return [part async for part in adapter.stream_chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                model="deepseek-v4-flash",
                extra_body={"thinking": {"type": "enabled"}},
            )]

        self.assertEqual(asyncio.run(collect()), ["final answer"])
        create = adapter._get_client.return_value.chat.completions.create
        self.assertEqual(
            create.await_args.kwargs["extra_body"],
            {"thinking": {"type": "enabled"}},
        )

    def test_reasoning_only_stream_reports_missing_final_answer(self):
        adapter = self._adapter_with_stream(
            _chunk(reasoning_content="thinking"),
            _chunk(choices=False),
        )

        async def collect():
            return [part async for part in adapter.stream_chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                model="deepseek-v4-flash",
            )]

        with self.assertRaises(LLMError) as raised:
            asyncio.run(collect())

        self.assertIn("最终回答为空", str(raised.exception))
        self.assertIn("无需永久关闭", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
