from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATE_SCRIPT = ROOT / "scripts" / "update_vods.py"
WORKFLOW = ROOT / ".github" / "workflows" / "update-vods.yml"


class PrivacyRetentionTests(unittest.TestCase):
    def test_update_script_has_no_raw_chat_persistence(self) -> None:
        text = UPDATE_SCRIPT.read_text(encoding="utf-8-sig")
        forbidden = (
            "CHAT_ARCHIVE_ROOT",
            "archive_chat_for_video",
            "write_chat_archive_jsonl",
            "build_chat_archive_records",
            ".chat.jsonl",
        )
        for value in forbidden:
            self.assertNotIn(value, text)

    def test_workflow_does_not_commit_raw_chat(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertNotIn("data/chat-archive", text)
        self.assertNotIn("*.chat.jsonl", text)

    def test_repository_contains_no_raw_chat_files(self) -> None:
        raw_files = [
            path
            for path in ROOT.rglob("*")
            if path.is_file()
            and (
                path.name.endswith(".chat.jsonl")
                or "chat-archive" in path.parts
                or path.name == "chat.json"
            )
        ]
        self.assertEqual([], raw_files)


if __name__ == "__main__":
    unittest.main()
