from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import headline_generation as hg


class GroqRetryDelayTests(unittest.TestCase):
    def build_generator(self) -> hg.ResilientHeadlineGenerator:
        return hg.ResilientHeadlineGenerator(
            gemini=None,
            groq=None,
            nvidia=None,
            fallback=mock.Mock(),
            settings=SimpleNamespace(headline_max_attempts=1),
            callbacks=SimpleNamespace(),
        )

    def call_collect(self, generator: hg.ResilientHeadlineGenerator, provider: mock.Mock) -> None:
        generator._collect_provider_candidates(
            provider_name="Groq",
            provider=provider,
            video_title="title",
            start_time="00:00",
            end_time="00:30",
            transcript="transcript",
        )

    def test_retryable_error_waits_without_consuming_headline_attempt(self) -> None:
        provider = mock.Mock()
        provider.generate.side_effect = [
            hg.HeadlineProviderError(
                "Groq",
                "HTTP 429",
                retryable=True,
                retry_after_sec=1.25,
            ),
            hg.HeadlineProviderError("Groq", "stop"),
        ]
        with mock.patch.object(hg.time, "sleep") as sleep:
            self.call_collect(self.build_generator(), provider)
        self.assertEqual(provider.generate.call_count, 2)
        sleep.assert_called_once_with(1.75)

    def test_non_retryable_error_does_not_sleep(self) -> None:
        provider = mock.Mock()
        provider.generate.side_effect = hg.HeadlineProviderError("Groq", "HTTP 400")
        with mock.patch.object(hg.time, "sleep") as sleep:
            self.call_collect(self.build_generator(), provider)
        sleep.assert_not_called()

    def test_retry_after_header_is_used(self) -> None:
        exc = SimpleNamespace(headers={"Retry-After": "2.5"})
        self.assertEqual(hg.resolve_http_retry_after_seconds(exc, ""), 2.5)

    def test_groq_error_body_wait_is_used(self) -> None:
        exc = SimpleNamespace(headers={})
        detail = "Rate limit reached. Please try again in 13.3125s."
        self.assertEqual(hg.resolve_http_retry_after_seconds(exc, detail), 13.3125)


if __name__ == "__main__":
    unittest.main()
