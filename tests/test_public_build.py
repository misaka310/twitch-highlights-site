import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicBuildTests(unittest.TestCase):
    def test_build_script_uses_react_frontend_and_whitelists_public_data(self):
        script = (ROOT / "scripts" / "build_public.sh").read_text(encoding="utf-8")
        self.assertIn("npm ci --prefix frontend", script)
        self.assertIn("npx tsc -b", script)
        self.assertIn("npx vite build", script)
        self.assertIn("cp -R frontend/dist/. public/", script)
        self.assertIn("public/data/vod_index.json", script)
        self.assertIn("public/data/vods/", script)
        self.assertIn("public/data/segment-thumbnails", script)
        self.assertNotIn("processed_vods.json public", script)
        self.assertNotIn("data/transcripts", script)

    def test_committed_public_runtime_is_the_production_bundle(self):
        public = ROOT / "public"
        self.assertTrue((public / "index.html").is_file())
        self.assertTrue((public / "favicon.svg").is_file())
        self.assertTrue((public / "site-config.json").is_file())
        self.assertTrue((public / "robots.txt").is_file())
        self.assertTrue((public / "sitemap.xml").is_file())
        self.assertTrue((public / "data" / "vods.json").is_file())
        self.assertTrue((public / "data" / "vod_index.json").is_file())
        self.assertTrue(any((public / "assets").glob("*.js")))
        self.assertTrue(any((public / "assets").glob("*.css")))
        self.assertFalse((public / "js").exists())
        self.assertFalse((public / "data" / "processed_vods.json").exists())
        self.assertFalse((public / "data" / "transcripts").exists())

    def test_public_index_has_production_metadata(self):
        html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>dotitao moments</title>", html)
        self.assertIn('rel="icon" href="/favicon.svg"', html)
        self.assertIn('name="description"', html)
        self.assertNotIn("Kumo preview", html)

    def test_public_site_config_contains_only_runtime_sections(self):
        payload = json.loads((ROOT / "public" / "site-config.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(payload), ["site", "twitch"])
        self.assertEqual(payload["site"]["name"], "dotitao moments")


if __name__ == "__main__":
    unittest.main()
