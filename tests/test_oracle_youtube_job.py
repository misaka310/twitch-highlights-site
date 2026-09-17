import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oracle_youtube_job  # noqa: E402


class OracleYoutubeJobTests(unittest.TestCase):
    def test_reads_live_chat_artifact_created_by_successful_ytdlp(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    (work_dir / "archive.live_chat.json").write_text(
                        json.dumps({"videoOffsetTimeMsec": 1234}) + "\n",
                        encoding="utf-8",
                    )
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "id": "WGTrmrSvZH0",
                            "title": "Oracle archive",
                            "upload_date": "20260917",
                            "duration": 120,
                        }
                    )
                )

            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                _video, comments = oracle_youtube_job._download_chat_and_metadata(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "$HOME/yt-dlp",
                    "$HOME/.local/bin/deno",
                    "$HOME/youtube-cookies.txt",
                )

        self.assertEqual(comments, [{"content_offset_seconds": 1.234}])

    def test_keeps_live_chat_artifact_when_ytdlp_finishes_with_format_403(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    (work_dir / "archive.live_chat.json").write_text(
                        json.dumps({"videoOffsetTimeMsec": 1234}) + "\n",
                        encoding="utf-8",
                    )
                    raise oracle_youtube_job.OracleJobFailure("yt_dlp_failure", "format probe returned 403")
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "id": "WGTrmrSvZH0",
                            "title": "Oracle archive",
                            "upload_date": "20260917",
                            "duration": 120,
                            "thumbnail": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                        }
                    )
                )

            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                video, comments = oracle_youtube_job._download_chat_and_metadata(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "$HOME/yt-dlp",
                    "$HOME/.local/bin/deno",
                    "$HOME/youtube-cookies.txt",
                )

        self.assertEqual(video["vod_id"], "WGTrmrSvZH0")
        self.assertEqual(comments, [{"content_offset_seconds": 1.234}])


if __name__ == "__main__":
    unittest.main()
