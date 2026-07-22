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
    def test_retired_feature_modules_and_data_directories_are_absent(self):
        time_module = "".join(("time", "stamp_generation"))
        speech_module = "".join(("trans", "cription"))
        text_data = "".join(("trans", "cripts"))
        time_data = "".join(("time", "stamps"))
        alignment_data = "".join(("trans", "cript-alignments"))
        requirements_file = "".join(("requirements-trans", "cribe.txt"))
        external_matcher = "".join(("match_you", "tube_videos.py"))
        segment_converter = "".join(("trans", "cribe_segments.py"))
        retired_paths = (
            ROOT / "scripts" / time_module,
            ROOT / "scripts" / speech_module,
            ROOT / "data" / text_data,
            ROOT / "data" / time_data,
            ROOT / "data" / alignment_data,
            ROOT / requirements_file,
            ROOT / "scripts" / external_matcher,
            ROOT / "scripts" / segment_converter,
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in retired_paths if path.exists()], [])

    def test_retired_integrations_are_absent_from_engine_sources(self):
        retired_markers = (
            "".join(("ano", "sa")),
            "".join(("cloud", "flare")),
            "".join(("trans", "cript")),
            "".join(("you", "tube")),
            "".join(("faster", "_whisper")),
            "".join(("gro", "q")),
            "".join(("gem", "ini")),
            "".join(("nvi", "dia")),
        )
        roots = [ROOT / "scripts", ROOT / "site", ROOT / ".github", ROOT / "config"]
        matches = []
        for source_root in roots:
            for path in source_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if any(part in {"node_modules", "public", "__pycache__"} for part in path.parts):
                    continue
                text = path.read_text(encoding="utf-8-sig", errors="ignore").lower()
                for marker in retired_markers:
                    if marker in text:
                        matches.append(f"{path.relative_to(ROOT)}:{marker}")
        self.assertEqual(matches, [])

    def test_retired_metadata_keys_are_absent_from_data(self):
        retired_key_parts = (
            "".join(("trans", "cript")),
            "".join(("you", "tube")),
            "".join(("time", "stamp")),
            "".join(("head", "line")),
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
                for part in retired_key_parts:
                    if part in key.lower():
                        matches.append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(matches, [])

    def test_instance_identity_is_not_hardcoded_in_engine_sources(self):
        instance_markers = (
            "".join(("doti", "tao")),
            "".join(("709", "803150")),
            "".join(("night", "reign")),
        )
        roots = [ROOT / "scripts", ROOT / "site", ROOT / ".github"]
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
