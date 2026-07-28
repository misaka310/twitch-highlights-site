from __future__ import annotations

from pathlib import Path
from textwrap import dedent


root = Path.cwd()
source_path = root / "scripts" / "headline_generation.py"
requirements_path = root / "requirements-transcribe.txt"
test_path = root / "tests" / "test_groq_sdk_transport.py"

source = source_path.read_text(encoding="utf-8")

old_resolver = dedent(
    '''
    def resolve_http_retry_after_seconds(exc: Any, detail: str) -> float | None:
        headers = getattr(exc, "headers", None)
        if headers is not None:
            for name in ("Retry-After", "X-RateLimit-Reset-Tokens"):
                parsed = _parse_retry_after_value(headers.get(name))
                if parsed is not None:
                    return parsed
        match = _GROQ_RETRY_AFTER_RE.search(str(detail or ""))
        if match:
            return min(max(0.0, float(match.group(1))), HEADLINE_RETRY_MAX_WAIT_SEC)
        return None
    '''
).lstrip()
new_resolver = dedent(
    '''
    def resolve_http_retry_after_seconds(exc: Any, detail: str) -> float | None:
        headers = getattr(exc, "headers", None)
        if headers is None:
            response = getattr(exc, "response", None)
            headers = getattr(response, "headers", None)
        if headers is not None:
            for name in ("Retry-After", "X-RateLimit-Reset-Tokens"):
                parsed = _parse_retry_after_value(headers.get(name))
                if parsed is not None:
                    return parsed
        match = _GROQ_RETRY_AFTER_RE.search(str(detail or ""))
        if match:
            return min(max(0.0, float(match.group(1))), HEADLINE_RETRY_MAX_WAIT_SEC)
        return None
    '''
).lstrip()
if old_resolver not in source:
    raise SystemExit("retry resolver block did not match")
source = source.replace(old_resolver, new_resolver, 1)

class_start = source.index("class GroqHeadlineGenerator:")
method_start = source.index("    def _request_headline", class_start)
method_end = source.index("\n\nclass NvidiaHeadlineGenerator:", method_start)
new_method = '''    def _request_headline(self, *, instructions: str, prompt: str) -> str:
        try:
            import groq as groq_sdk
        except ImportError as exc:
            raise HeadlineProviderError("Groq", "official Groq SDK is not installed") from exc

        client = groq_sdk.Groq(
            api_key=self.api_key,
            timeout=float(self.settings.groq_timeout_sec),
        )
        request_options: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.model.startswith("qwen/"):
            request_options["reasoning_effort"] = "none"

        try:
            completion = client.chat.completions.create(**request_options)
        except Exception as exc:
            status_code = int(getattr(exc, "status_code", 0) or 0)
            body = getattr(exc, "body", None)
            if isinstance(body, (dict, list)):
                detail = json.dumps(body, ensure_ascii=False)
            else:
                detail = str(body or exc)
            retryable = status_code == 429 or 500 <= status_code < 600
            retry_after_sec = resolve_http_retry_after_seconds(exc, detail) if retryable else None
            if status_code:
                reason = f"HTTP {status_code}: {detail[:300] or 'request failed'}"
            else:
                error_name = type(exc).__name__.lower()
                retryable = "timeout" in error_name or "connection" in error_name
                reason = "request timed out" if "timeout" in error_name else f"request failed: {detail[:300]}"
            raise HeadlineProviderError(
                "Groq",
                reason,
                retryable=retryable,
                retry_after_sec=retry_after_sec,
            ) from exc

        choices = list(getattr(completion, "choices", None) or [])
        if not choices:
            raise HeadlineProviderError("Groq", "response did not include a choice")
        message = getattr(choices[0], "message", None)
        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            raise HeadlineProviderError("Groq", "response did not include message content")
        return content
'''
source = source[:method_start] + new_method + source[method_end:]
source_path.write_text(source, encoding="utf-8")

requirements = requirements_path.read_text(encoding="utf-8-sig").splitlines()
if "groq" not in {row.strip() for row in requirements}:
    requirements.append("groq")
requirements_path.write_text("\n".join(requirements) + "\n", encoding="utf-8")

test_path.write_text(
    dedent(
        '''
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
        '''
    ).lstrip(),
    encoding="utf-8",
)
