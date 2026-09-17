from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from youtube_handoff import (  # noqa: E402
    build_material_manifest,
    create_material_bundle,
    extract_material_bundle,
    validate_material_manifest,
)


class YoutubeHandoffTests(unittest.TestCase):
    def _manifest(self) -> dict:
        return build_material_manifest(
            {
                "provider": "youtube",
                "vod_id": "WGTrmrSvZH0",
                "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                "title": "test",
                "published_at": "2026-09-17T00:00:00+00:00",
                "thumbnail_url": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                "duration_sec": 1000,
            },
            [
                {"content_offset_seconds": 100.0, "message": "private text must not be bundled"},
                {"content_offset_seconds": 101.0, "author_name": "private user"},
            ],
            [{"id": "WGTrmrSvZH0_90_120", "rank": 1, "start_sec": 90, "end_sec": 120}],
        )

    def test_manifest_contains_offsets_only(self) -> None:
        manifest = self._manifest()
        self.assertIn("chat_offsets", manifest)
        self.assertNotIn("comments", manifest)
        self.assertNotIn("message", json.dumps(manifest, ensure_ascii=False))
        self.assertNotIn("author", json.dumps(manifest, ensure_ascii=False))
        self.assertEqual(validate_material_manifest(manifest), manifest)

    def test_bundle_round_trip_is_limited_to_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "audio.wav"
            screenshot = root / "screenshot.webp"
            audio.write_bytes(b"wav")
            screenshot.write_bytes(b"webp")
            bundle = root / "material.tar.gz"
            create_material_bundle(
                bundle,
                self._manifest(),
                {"clips/clip-0.wav": audio, "clips/clip-0.webp": screenshot},
            )
            extracted = extract_material_bundle(bundle, root / "out")
            self.assertEqual(extracted["video"]["vod_id"], "WGTrmrSvZH0")
            self.assertTrue((root / "out" / "clips" / "clip-0.wav").is_file())
            self.assertTrue((root / "out" / "clips" / "clip-0.webp").is_file())

    def test_extraction_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "unsafe.tar.gz"
            with tarfile.open(bundle, "w:gz") as archive:
                payload = b"{}"
                info = tarfile.TarInfo("../escape")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(ValueError):
                extract_material_bundle(bundle, root / "out")

    def test_actions_workflow_receives_material_without_youtube_downloader(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "process-youtube-material.yml").read_text(encoding="utf-8")
        timer = (ROOT / "ops" / "oracle" / "youtube-highlight.timer").read_text(encoding="utf-8")
        service = (ROOT / "ops" / "oracle" / "youtube-highlight.service").read_text(encoding="utf-8")
        self.assertNotIn("yt-dlp", workflow)
        self.assertIn("repository_dispatch", workflow)
        self.assertIn("OnCalendar=*-*-* 06:07:00 Asia/Tokyo", timer)
        self.assertIn("EnvironmentFile=-/etc/youtube-highlight/youtube.env", service)


if __name__ == "__main__":
    unittest.main()
