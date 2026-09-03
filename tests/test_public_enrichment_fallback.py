import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_public_enrichment.py"


class PublicEnrichmentFallbackTests(unittest.TestCase):
    def load_verifier(self):
        fake_transcribe = types.ModuleType("transcribe_segments")
        fake_transcribe.is_publishable_headline = lambda headline: bool(str(headline).strip())
        fake_transcribe.validate_final_headline_japanese = lambda headline: SimpleNamespace(reasons=[])

        spec = importlib.util.spec_from_file_location("verify_public_enrichment_under_test", SCRIPT_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"transcribe_segments": fake_transcribe}):
            spec.loader.exec_module(module)
        return module

    def build_payload(self, *, headline: str = "", reason: str = "Chat activity spike around 01:02:03 (z-score=4.2)."):
        return {
            "videos": [
                {
                    "vod_id": "123",
                    "items": [
                        {
                            "id": "123_3723_3783",
                            "headline": headline,
                            "reason": reason,
                            "screenshot_url": "/data/segment-thumbnails/123/123_3723_3783.webp",
                        }
                    ],
                }
            ]
        }

    def create_screenshot(self, root: Path) -> None:
        path = root / "data" / "segment-thumbnails" / "123" / "123_3723_3783.webp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"webp")

    def test_reason_fallback_allows_missing_headline(self):
        verifier = self.load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_screenshot(root)
            failures = verifier.collect_public_enrichment_failures(self.build_payload(), root=root)
        self.assertEqual([], failures)

    def test_missing_headline_and_reason_remains_blocking(self):
        verifier = self.load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.create_screenshot(root)
            failures = verifier.collect_public_enrichment_failures(self.build_payload(reason=""), root=root)
        self.assertEqual(["segment_id=123_3723_3783: display title source missing"], failures)


if __name__ == "__main__":
    unittest.main()
