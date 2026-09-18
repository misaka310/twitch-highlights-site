import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VerificationHarnessTests(unittest.TestCase):
    def test_package_scripts_use_non_recursive_python_harnesses(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]

        self.assertEqual(scripts["setup"], "python scripts/setup_dependencies.py")
        self.assertEqual(scripts["verify"], "python scripts/verify.py")
        self.assertEqual(scripts["verify:browser"], "python scripts/verify.py --step browser")
        self.assertEqual(scripts["verify:live"], "python scripts/verify.py --step live")
        self.assertEqual(scripts["verify:live:browser"], "python scripts/verify.py --step live-browser")
        self.assertNotIn("npm run typecheck:frontend &&", scripts["verify"])

    def test_setup_harness_uses_an_explicit_ignored_npm_cache(self):
        harness = (ROOT / "scripts" / "setup_dependencies.py").read_text(encoding="utf-8")
        self.assertIn('environment["npm_config_cache"] = str(ROOT / ".cache" / "npm")', harness)
        self.assertIn('environment.setdefault("COMSPEC"', harness)

    def test_frontend_playwright_server_does_not_spawn_nested_npm(self):
        config = (ROOT / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")
        self.assertIn("node node_modules/vite/bin/vite.js", config)
        self.assertNotIn('command: "npm run dev"', config)

    def test_verification_harness_covers_all_product_gates(self):
        harness = (ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
        required_markers = (
            "TypeScript typecheck",
            "ESLint",
            "Frontend unit tests",
            "Python unit tests",
            "Frontend browser tests",
            "Public build",
            "Public build validation",
            "Public reproducibility",
            "Public browser tests",
            "Repository hygiene",
        )
        for marker in required_markers:
            self.assertIn(marker, harness)

    def test_standard_verification_does_not_auto_run_browser_e2e(self):
        harness = (ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
        standard = harness.split("STANDARD_SEQUENCE = (", 1)[1].split(")", 1)[0]
        self.assertNotIn('"frontend-e2e"', standard)
        self.assertNotIn('"public-e2e"', standard)
        self.assertIn('"browser": ("frontend-e2e", "public-e2e")', harness)
        self.assertIn('"live": ("live-data",)', harness)
        self.assertIn('"live-browser": ("live-youtube", "live-production")', harness)


if __name__ == "__main__":
    unittest.main()
