from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import headline_generation as hg


class GroqSdkTransportTests(unittest.TestCase):
    def test_qwen_uses_official_sdk_chat_json_without_reasoning(self) -> None:
        calls: dict[str, object] = {}

        class FakeCompletions:
            def create(self, **kwargs):
                calls["create"] = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"candidates": []}'))],
                    model="qwen/qwen3.6-27b",
                )

        class FakeGroq:
            def __init__(self, *, api_key: str, timeout: float) -> None:
                calls["client"] = {"api_key": api_key, "timeout": timeout}
                self.chat = SimpleNamespace(completions=FakeCompletions())

        generator = hg.GroqHeadlineGenerator(
            "secret",
            "qwen/qwen3.6-27b",
            settings=SimpleNamespace(groq_timeout_sec=45),
            callbacks=SimpleNamespace(),
        )
        with mock.patch.dict(sys.modules, {"groq": SimpleNamespace(Groq=FakeGroq)}):
            with mock.patch.object(
                hg.request,
                "urlopen",
                side_effect=AssertionError("urllib transport should not be used"),
            ):
                result = generator._request_headline(
                    instructions="Return JSON only.",
                    prompt="Generate candidates.",
                )

        self.assertEqual(result, '{"candidates": []}')
        self.assertEqual(calls["client"], {"api_key": "secret", "timeout": 45.0})
        self.assertEqual(
            calls["create"],
            {
                "model": "qwen/qwen3.6-27b",
                "messages": [
                    {"role": "system", "content": "Return JSON only."},
                    {"role": "user", "content": "Generate candidates."},
                ],
                "response_format": {"type": "json_object"},
                "reasoning_effort": "none",
            },
        )

    def test_sdk_rate_limit_preserves_retry_delay(self) -> None:
        class FakeRateLimitError(RuntimeError):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "2.5"})
            body = {"error": {"message": "rate limit reached"}}

        class FakeCompletions:
            def create(self, **kwargs):
                raise FakeRateLimitError("rate limit reached")

        class FakeGroq:
            def __init__(self, *, api_key: str, timeout: float) -> None:
                self.chat = SimpleNamespace(completions=FakeCompletions())

        generator = hg.GroqHeadlineGenerator(
            "secret",
            "qwen/qwen3.6-27b",
            settings=SimpleNamespace(groq_timeout_sec=45),
            callbacks=SimpleNamespace(),
        )
        with mock.patch.dict(sys.modules, {"groq": SimpleNamespace(Groq=FakeGroq)}):
            with self.assertRaises(hg.HeadlineProviderError) as raised:
                generator._request_headline(
                    instructions="Return JSON only.",
                    prompt="Generate candidates.",
                )

        self.assertTrue(raised.exception.retryable)
        self.assertEqual(raised.exception.retry_after_sec, 2.5)
        self.assertIn("HTTP 429", raised.exception.reason)


if __name__ == "__main__":
    unittest.main()
