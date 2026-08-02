from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib import error
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import headline_generation as hg
import transcribe_segments as ts


class HeadlineProviderBoundaryTests(unittest.TestCase):
    def test_extracts_responses_and_keeps_compatibility_aliases(self):
        self.assertEqual(
            hg.extract_response_output_text({"output_text": " direct "}),
            "direct",
        )
        self.assertEqual(
            hg.extract_response_output_text(
                {
                    "output": [
                        {"content": [{"type": "output_text", "text": " one "}]},
                        {"content": [{"type": "ignored", "text": "no"}, {"type": "output_text", "text": "two"}]},
                    ]
                }
            ),
            "one two",
        )
        self.assertEqual(
            hg.extract_gemini_output_text(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": " first "}, {"text": "second"}]}},
                        {"content": {"parts": [{"ignored": True}]}},
                    ]
                }
            ),
            "first second",
        )
        self.assertIs(ts.extract_response_output_text, hg.extract_response_output_text)
        self.assertIs(ts.extract_gemini_output_text, hg.extract_gemini_output_text)

    def test_reads_http_error_body_safely(self):
        exc = error.HTTPError(
            "https://example.test",
            400,
            "bad request",
            {},
            io.BytesIO(b'{"error":{"message":"bad"}}'),
        )
        self.assertEqual(hg.read_http_error_detail(exc), '{"error":{"message":"bad"}}')
        self.assertEqual(hg.read_http_error_detail(SimpleNamespace()), "")
        self.assertIs(ts.read_http_error_detail, hg.read_http_error_detail)

    def test_classifies_gemini_http_statuses_without_changing_retry_policy(self):
        cases = [
            (400, '{"error":{"message":"invalid"}}', "HTTP 400: invalid", False),
            (401, '{"error":{"message":"unauthorized"}}', "HTTP 401: unauthorized", False),
            (429, '{"error":{"status":"RESOURCE_EXHAUSTED"}}', "RESOURCE_EXHAUSTED / HTTP 429", True),
            (500, "server error", "temporary API error (HTTP 500)", True),
            (503, '{"error":{"status":"UNAVAILABLE"}}', "temporary unavailable (HTTP 503)", True),
            (504, '{"error":{"status":"DEADLINE_EXCEEDED"}}', "request timed out (HTTP 504)", True),
        ]
        for code, detail, expected_reason, expected_retryable in cases:
            with self.subTest(code=code):
                self.assertEqual(
                    hg.classify_gemini_http_error(code, detail),
                    (expected_reason, expected_retryable),
                )
        self.assertIs(ts.classify_gemini_http_error, hg.classify_gemini_http_error)

    def test_transport_error_classification_is_provider_owned(self):
        for reason in (
            "request timed out",
            "temporary failure",
            "connection reset by peer",
            "service unavailable",
        ):
            self.assertTrue(hg.is_temporary_transport_error(reason))
        self.assertFalse(hg.is_temporary_transport_error("certificate rejected"))
        self.assertIs(ts.is_temporary_transport_error, hg.is_temporary_transport_error)

    def test_gemini_generator_uses_internal_error_classification(self):
        settings = SimpleNamespace(gemini_timeout_sec=45)
        callbacks = SimpleNamespace(build_headline_response_schema=lambda: {"type": "object"})
        generator = hg.GeminiHeadlineGenerator(
            "key",
            "model",
            "https://example.test/{model}",
            settings=settings,
            callbacks=callbacks,
        )
        body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED"}}).encode("utf-8")
        exc = error.HTTPError("https://example.test", 429, "rate limit", {}, io.BytesIO(body))
        with mock.patch.object(hg.request, "urlopen", side_effect=exc):
            with self.assertRaises(hg.HeadlineProviderError) as raised:
                generator._request_headline(instructions="system", prompt="user")
        self.assertEqual(raised.exception.reason, "RESOURCE_EXHAUSTED / HTTP 429")
        self.assertTrue(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
