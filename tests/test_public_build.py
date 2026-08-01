import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class PublicBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = shutil.which("sh") or shutil.which("bash")
        self.node = shutil.which("node")
        if self.shell is None or self.node is None:
            self.skipTest("sh/bash and Node.js are required")
        if self.shell.lower().endswith("\\system32\\bash.exe"):
            self.skipTest("WSL bash launcher is unreliable on this host")

    def _prepare(self, root: Path) -> None:
        source_root = Path(__file__).resolve().parents[1]
        (root / "scripts").mkdir(parents=True)
        (root / "site" / "js").mkdir(parents=True)
        (root / "data" / "vods").mkdir(parents=True)
        (root / "data" / "segment-thumbnails" / "1").mkdir(parents=True)
        (root / "config").mkdir(parents=True)

        for relative in (
            "scripts/build_public.sh",
            "scripts/export-site-config.mjs",
            "scripts/site-config-runtime.mjs",
        ):
            destination = root / relative
            destination.write_text((source_root / relative).read_text(encoding="utf-8"), encoding="utf-8")

        config = {
            "site": {
                "name": "Configured Site",
                "description": "Configured description",
                "base_url": "https://example.test",
                "language": "ja",
                "analytics": {"goatcounter_code": ""},
            },
            "twitch": {"channel_login": "example_channel", "channel_id": "123"},
        }
        (root / "config" / "site.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "site" / "index.html").write_text("<html></html>\n", encoding="utf-8")
        (root / "site" / "styles.css").write_text("body{}\n", encoding="utf-8")
        (root / "site" / "favicon.svg").write_text("<svg/>\n", encoding="utf-8")
        (root / "site" / "js" / "app.js").write_text("console.log('ok');\n", encoding="utf-8")
        (root / "data" / "vods.json").write_text('{"videos":[]}\n', encoding="utf-8")
        (root / "data" / "vod_index.json").write_text('{"videos":[]}\n', encoding="utf-8")
        (root / "data" / "vods" / "1.json").write_text('{"vod_id":"1"}\n', encoding="utf-8")
        (root / "data" / "segment-thumbnails" / "1" / "1.webp").write_bytes(b"image")

    def test_build_copies_only_core_public_assets(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            self._prepare(root)
            subprocess.run([self.shell, "scripts/build_public.sh"], cwd=root, check=True)

            self.assertTrue((root / "public" / "data" / "vods.json").is_file())
            self.assertTrue((root / "public" / "data" / "vod_index.json").is_file())
            self.assertTrue((root / "public" / "data" / "vods" / "1.json").is_file())
            self.assertTrue((root / "public" / "data" / "segment-thumbnails" / "1" / "1.webp").is_file())
            config = json.loads((root / "public" / "site-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["site"]["name"], "Configured Site")
            self.assertEqual(sorted(config), ["site", "twitch"])

            for source_path in sorted((root / "site").rglob("*")):
                if not source_path.is_file():
                    continue
                relative_path = source_path.relative_to(root / "site")
                published_path = root / "public" / relative_path
                self.assertTrue(published_path.is_file(), relative_path.as_posix())
                self.assertEqual(
                    source_path.read_bytes(),
                    published_path.read_bytes(),
                    relative_path.as_posix(),
                )

    def test_committed_public_runtime_matches_site(self):
        root = Path(__file__).resolve().parents[1]
        for source_path in sorted((root / "site").rglob("*")):
            if not source_path.is_file():
                continue
            relative_path = source_path.relative_to(root / "site")
            published_path = root / "public" / relative_path
            self.assertTrue(published_path.is_file(), relative_path.as_posix())
            self.assertEqual(
                source_path.read_bytes(),
                published_path.read_bytes(),
                relative_path.as_posix(),
            )


if __name__ == "__main__":
    unittest.main()
