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


if __name__ == "__main__":
    unittest.main()
