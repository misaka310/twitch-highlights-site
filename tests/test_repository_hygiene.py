import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_repository_hygiene import find_local_output_violations  # noqa: E402


class RepositoryHygieneTests(unittest.TestCase):
    def test_detects_accidental_npm_cache_argument_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "=" / "npm-cache").mkdir(parents=True)
            (root / "frontend" / "=" / "npm-cache").mkdir(parents=True)

            violations = find_local_output_violations(root)

        self.assertEqual(
            violations,
            [
                "=: accidental npm cache argument directory must be removed",
                "frontend/=: accidental npm cache argument directory must be removed",
            ],
        )

    def test_accidental_cache_directory_is_not_hidden_by_gitignore(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("=/", gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
