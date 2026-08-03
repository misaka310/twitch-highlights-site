import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SHA256_RE = re.compile(r"^[0-9a-f]{40}$")


class SupplyChainTests(unittest.TestCase):
    def test_transcription_requirements_are_exactly_pinned(self):
        requirements = [
            line.strip()
            for line in (ROOT / "requirements-transcribe.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertTrue(requirements)
        self.assertEqual([line for line in requirements if "==" not in line], [])

    def test_github_actions_are_pinned_to_commit_shas(self):
        invalid = []
        for workflow in WORKFLOWS.glob("*.yml"):
            for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if not stripped.startswith("uses:"):
                    continue
                reference = stripped.split("@", 1)[1] if "@" in stripped else ""
                if not SHA256_RE.fullmatch(reference):
                    invalid.append(f"{workflow.name}:{line_number}:{reference}")
        self.assertEqual(invalid, [])

    def test_twitch_downloader_archive_is_verified_before_extraction(self):
        workflow = (WORKFLOWS / "update-vods.yml").read_text(encoding="utf-8")
        checksum_command = (
            "echo '5b52964764e6e6c704f9d3b5aaaeb02f78c7c91a57b1bf9b2636738da293af89  "
            ".tmp-tools/twitchdownloader/td.zip' | sha256sum --check --strict"
        )
        self.assertIn(checksum_command, workflow)
        self.assertLess(workflow.index("sha256sum --check"), workflow.index("unzip -o"))


if __name__ == "__main__":
    unittest.main()
