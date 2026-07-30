import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".json", ".yml", ".yaml", ".html", ".css", ".sh"}


def iter_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_keys(child)


class RepositoryArchitectureTests(unittest.TestCase):
    def test_public_enrichment_modules_exist_without_private_artifacts(self):
        required_paths = (
            ROOT / "requirements-transcribe.txt",
            ROOT / "scripts" / "transcribe_segments.py",
            ROOT / "scripts" / "headline_generation.py",
            ROOT / "scripts" / "transcription",
            ROOT / "scripts" / "verify_public_enrichment.py",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in required_paths if not path.exists()], [])

        forbidden_paths = (
            ROOT / "data" / "chat-archive",
            ROOT / "data" / "transcripts",
            ROOT / "data" / "timestamps",
            ROOT / "data" / "transcript-alignments",
            ROOT / "scripts" / "match_youtube_videos.py",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in forbidden_paths if path.exists()], [])

    def test_disallowed_backend_integrations_are_absent_from_public_infrastructure(self):
        disallowed_markers = (
            "".join(("ano", "sa")),
            "".join(("cloud", "flare")),
        )
        # `site/**` intentionally matches repository 19 byte-for-byte, including
        # its backward-compatible data field names. Public-only infrastructure
        # must not reintroduce the corresponding private backend integrations.
        roots = [ROOT / "scripts", ROOT / ".github", ROOT / "config"]
        matches = []
        for source_root in roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if any(part in {"node_modules", "public", "__pycache__"} for part in path.parts):
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
                for marker in disallowed_markers:
                    if marker in text:
                        matches.append(f"{path.relative_to(ROOT)}:{marker}")
        self.assertEqual(matches, [])

    def test_private_metadata_keys_are_absent_from_data(self):
        private_key_parts = (
            "".join(("trans", "cript")),
            "".join(("you", "tube")),
            "".join(("time", "stamp")),
        )
        matches = []
        paths = [
            ROOT / "data" / "processed_vods.json",
            ROOT / "data" / "vods.json",
            ROOT / "data" / "vod_index.json",
            *(ROOT / "data" / "vods").glob("*.json"),
        ]
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            for key in iter_keys(payload):
                for part in private_key_parts:
                    if part in key.lower():
                        matches.append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(matches, [])

    def test_instance_identity_is_not_hardcoded_in_public_pipeline(self):
        instance_markers = (
            "".join(("doti", "tao")),
            "".join(("709", "803150")),
            "".join(("night", "reign")),
        )
        # The published site intentionally preserves repository 19's identity.
        # Only the reusable public data pipeline must remain configuration-driven.
        roots = [ROOT / "scripts"]
        matches = []
        for source_root in roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
                for marker in instance_markers:
                    if marker in text:
                        matches.append(f"{path.relative_to(ROOT)}:{marker}")
        self.assertEqual(matches, [])

    def test_instance_configuration_and_example_exist(self):
        self.assertTrue((ROOT / "config" / "site.json").is_file())
        self.assertTrue((ROOT / "config" / "site.example.json").is_file())
        example = json.loads((ROOT / "config" / "site.example.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(example), ["analysis", "site", "twitch"])


if __name__ == "__main__":
    unittest.main()
