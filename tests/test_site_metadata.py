import html
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_site_metadata import render_site_metadata  # noqa: E402


class SiteMetadataTests(unittest.TestCase):
    def test_renders_static_metadata_from_runtime_site_config(self):
        template = """<!doctype html>
<html lang="__SITE_LANGUAGE__">
<head>
<meta name="description" content="__SITE_DESCRIPTION__" />
<meta property="og:title" content="__SITE_NAME__" />
<meta property="og:description" content="__SITE_DESCRIPTION__" />
<meta property="og:url" content="__SITE_BASE_URL__" />
<title>__SITE_NAME__</title>
</head>
</html>
"""
        config = {
            "site": {
                "name": "A & B <Highlights>",
                "description": 'A "quoted" description',
                "base_url": "https://example.test/",
                "language": "en",
            }
        }

        rendered = render_site_metadata(template, config)

        self.assertNotIn("__SITE_", rendered)
        self.assertIn('lang="en"', rendered)
        self.assertIn(f"<title>{html.escape(config['site']['name'])}</title>", rendered)
        self.assertIn('content="A &quot;quoted&quot; description"', rendered)
        self.assertIn('content="https://example.test"', rendered)

    def test_requires_all_metadata_placeholders(self):
        with self.assertRaisesRegex(RuntimeError, "metadata placeholder"):
            render_site_metadata("<title>missing placeholders</title>", {"site": {}})


if __name__ == "__main__":
    unittest.main()
