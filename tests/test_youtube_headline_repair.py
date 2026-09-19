import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from headline_candidate_selection import build_headline_source_config  # noqa: E402
from repair_youtube_headlines import collect_caption_text, repair_video_headlines  # noqa: E402


class YoutubeHeadlineRepairTests(unittest.TestCase):
    def test_collect_caption_text_uses_only_overlapping_cues(self):
        cues = [
            {"start_sec": 0, "end_sec": 5, "text": "before"},
            {"start_sec": 10, "end_sec": 15, "text": "離婚してる。"},
            {"start_sec": 14, "end_sec": 20, "text": "この気まずくなる流れ好きすぎるからやめて。"},
            {"start_sec": 25, "end_sec": 30, "text": "after"},
        ]
        text = collect_caption_text(cues, 10, 20)
        self.assertIn("離婚してる", text)
        self.assertIn("気まずくなる流れ", text)
        self.assertNotIn("before", text)
        self.assertNotIn("after", text)

    def test_repair_video_headlines_requires_remote_llm_result(self):
        video = {
            "title": "archive",
            "items": [
                {
                    "id": "2a_ATYeOiAQ_4770_4850",
                    "start_sec": 10,
                    "end_sec": 20,
                    "start_time": "00:00:10",
                    "end_time": "00:00:20",
                    "headline": "broken",
                }
            ],
        }
        captions = {
            "cues": [
                {"start_sec": 10, "end_sec": 15, "text": "離婚してる。"},
                {"start_sec": 14, "end_sec": 20, "text": "この気まずくなる流れ好きすぎるからやめて。"},
            ]
        }

        class RemoteGenerator:
            def generate(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    text="離婚話で気まずくなる流れ",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="high",
                    notes="",
                )

        generator = RemoteGenerator()
        repaired = repair_video_headlines(
            video,
            captions,
            headline_generator=generator,
            source_config=build_headline_source_config(),
        )
        self.assertEqual(repaired, 1)
        self.assertEqual(video["items"][0]["headline"], "離婚話で気まずくなる流れ")
        self.assertIn("離婚", generator.kwargs["prepared_transcript"])

        class FallbackGenerator:
            def generate(self, **_kwargs):
                return SimpleNamespace(
                    text="気まずくなる流れ好き",
                    source="extractive",
                    model="local-extractive",
                    generation_mode="fallback_extractive",
                    confidence="low",
                    notes="extractive_fallback",
                )

        with self.assertRaisesRegex(RuntimeError, "no remote LLM headline"):
            repair_video_headlines(
                video,
                captions,
                headline_generator=FallbackGenerator(),
                source_config=build_headline_source_config(),
            )

    def test_workflow_exposes_repair_vod_input(self):
        workflow = (ROOT / ".github" / "workflows" / "process-youtube-material.yml").read_text(encoding="utf-8")
        self.assertIn("repair_vod_id:", workflow)
        self.assertIn("scripts/repair_youtube_headlines.py --vod-id", workflow)
        self.assertIn("GROQ_MODEL: openai/gpt-oss-120b", workflow)


if __name__ == "__main__":
    unittest.main()
