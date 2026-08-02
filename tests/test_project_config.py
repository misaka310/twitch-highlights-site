import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_config import load_project_config


class ProjectConfigTests(unittest.TestCase):
    def _write_configs(self, root: Path) -> tuple[Path, Path]:
        site_path = root / "site.json"
        site_path.write_text(
            json.dumps(
                {
                    "site": {
                        "name": "Configured Site",
                        "description": "Configured description",
                        "base_url": "https://example.test/",
                        "language": "ja",
                        "analytics": {"goatcounter_code": "example"},
                    },
                    "twitch": {"channel_login": "sample_channel", "channel_id": "123"},
                }
            ),
            encoding="utf-8",
        )
        tag_rules_path = root / "tag-rules.json"
        tag_rules_path.write_text(
            json.dumps(
                {
                    "extra_tag_rules": [
                        {"tag": "custom", "patterns": ["pattern-a", "pattern-b"]}
                    ]
                }
            ),
            encoding="utf-8",
        )
        return site_path, tag_rules_path

    def test_loads_instance_configuration(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            site_path, tag_rules_path = self._write_configs(Path(tmp_raw))
            config = load_project_config(site_path, env={}, tag_rules_path=tag_rules_path)
        self.assertEqual(config.site_name, "Configured Site")
        self.assertEqual(config.site_base_url, "https://example.test")
        self.assertEqual(config.twitch_channel_login, "sample_channel")
        self.assertEqual(config.twitch_channel_url, "https://www.twitch.tv/sample_channel")
        self.assertIn("123-sample_channel", config.twitchmetrics_url)
        self.assertEqual(config.extra_tag_rules, (("custom", ("pattern-a", "pattern-b")),))
        self.assertNotIn("youtube", config.public_dict())

    def test_environment_overrides_instance_configuration(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            site_path, tag_rules_path = self._write_configs(Path(tmp_raw))
            config = load_project_config(
                site_path,
                env={
                    "SITE_NAME": "Override Site",
                    "TWITCH_CHANNEL": "other_channel",
                    "TWITCH_CHANNEL_ID": "456",
                },
                tag_rules_path=tag_rules_path,
            )
        self.assertEqual(config.site_name, "Override Site")
        self.assertEqual(config.twitch_channel_login, "other_channel")
        self.assertEqual(config.twitch_channel_id, "456")

    def test_invalid_channel_login_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            site_path, tag_rules_path = self._write_configs(Path(tmp_raw))
            with self.assertRaises(RuntimeError):
                load_project_config(
                    site_path,
                    env={"TWITCH_CHANNEL": "not valid"},
                    tag_rules_path=tag_rules_path,
                )


if __name__ == "__main__":
    unittest.main()
