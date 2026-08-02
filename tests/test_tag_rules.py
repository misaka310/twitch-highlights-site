import json
import tempfile
import unittest
from pathlib import Path

from scripts.tag_rules import load_extra_tag_rules


class TagRulesTests(unittest.TestCase):
    def _write_rules(self, root: Path, payload: object) -> Path:
        path = root / "tag-rules.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_loads_extra_tag_rules(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            path = self._write_rules(
                Path(tmp_raw),
                {
                    "extra_tag_rules": [
                        {"tag": "custom", "patterns": ["pattern-a", "pattern-b"]}
                    ]
                },
            )
            rules = load_extra_tag_rules(path)
        self.assertEqual(rules, (("custom", ("pattern-a", "pattern-b")),))

    def test_ignores_incomplete_rules_and_empty_patterns(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            path = self._write_rules(
                Path(tmp_raw),
                {
                    "extra_tag_rules": [
                        {"tag": "", "patterns": ["ignored"]},
                        {"tag": "missing-patterns"},
                        {"tag": "empty", "patterns": ["", "  "]},
                        {"tag": "valid", "patterns": ["keep", ""]},
                    ]
                },
            )
            rules = load_extra_tag_rules(path)
        self.assertEqual(rules, (("valid", ("keep",)),))

    def test_missing_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            path = Path(tmp_raw) / "missing.json"
            with self.assertRaisesRegex(RuntimeError, "tag rules config not found"):
                load_extra_tag_rules(path)

    def test_invalid_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_raw:
            path = Path(tmp_raw) / "tag-rules.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "invalid tag rules config JSON"):
                load_extra_tag_rules(path)


if __name__ == "__main__":
    unittest.main()
