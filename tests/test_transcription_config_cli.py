from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcription.cli import build_run_options, parse_cli_args
from transcription.config import PipelineSettings


class PipelineSettingsTests(unittest.TestCase):
    def test_from_env_uses_supplied_mapping_and_clamps_ranges(self):
        settings = PipelineSettings.from_env(
            {
                "TRANSCRIPT_MODEL": "large-v3",
                "TRANSCRIPT_MAX_SEGMENTS": "0",
                "TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD": "9",
                "SOURCE_SENTENCE_LIMIT": "8",
                "TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS": "invalid",
                "SEGMENT_SCREENSHOT_GENERATION_ENABLED": "false",
                "HEADLINE_STREAMER_ID": " dotitao ",
            }
        )
        self.assertEqual(settings.TRANSCRIPT_MODEL, "large-v3")
        self.assertEqual(settings.TRANSCRIPT_MAX_SEGMENTS, 1)
        self.assertEqual(settings.TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD, 1.0)
        self.assertEqual(settings.SOURCE_SENTENCE_LIMIT_DEFAULT, 2)
        self.assertIsNone(settings.TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS)
        self.assertFalse(settings.SEGMENT_SCREENSHOT_GENERATION_ENABLED)
        self.assertEqual(settings.HEADLINE_STREAMER_ID, "dotitao")

    def test_cli_overrides_are_converted_to_run_options(self):
        settings = PipelineSettings.from_env(
            {
                "TRANSCRIPT_MAX_SEGMENTS": "9",
                "TRANSCRIPT_SECOND_PASS_TOP_N": "2",
                "USE_GAME_TERM_DICTIONARY": "1",
            }
        )
        args = parse_cli_args(
            [
                "--headline-only",
                "--max-segments",
                "4",
                "--item-id",
                " item-1 ",
                "--no-game-term-dictionary",
                "--second-pass-top-n",
                "0",
                "--no-second-pass-word-timestamps",
            ]
        )
        options = build_run_options(args, settings)
        self.assertTrue(options.headline_only)
        self.assertTrue(options.force_headline_refresh)
        self.assertEqual(options.max_segments, 4)
        self.assertEqual(options.only_item_id, "item-1")
        self.assertFalse(options.use_game_term_dictionary)
        self.assertEqual(options.second_pass_top_n, 0)
        self.assertFalse(options.second_pass_word_timestamps)

    def test_import_does_not_read_process_environment_or_dotenv(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SCRIPTS)
        env["TRANSCRIPT_MODEL"] = "must-not-be-read-on-import"
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "import transcribe_segments as ts; print(ts.TRANSCRIPT_MODEL)",
            ],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.stdout.strip().splitlines()[-1], "small")


if __name__ == "__main__":
    unittest.main()
