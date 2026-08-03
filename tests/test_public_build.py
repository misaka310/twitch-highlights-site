import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicBuildTests(unittest.TestCase):
    def test_build_script_uses_installed_react_frontend_and_whitelists_public_data(self):
        script = (ROOT / "scripts" / "build_public.sh").read_text(encoding="utf-8")
        self.assertIn("run npm run setup first", script)
        self.assertIn("npm run build --prefix frontend", script)
        self.assertNotIn("npm ci --prefix frontend", script)
        self.assertIn("cp -R frontend/dist/. public/", script)
        self.assertNotIn("site/favicon.svg", script)
        self.assertTrue((ROOT / "frontend" / "public" / "favicon.svg").is_file())
        self.assertIn("public/data/vod_index.json", script)
        self.assertIn("public/data/vods/", script)
        self.assertIn("public/data/segment-thumbnails", script)
        self.assertNotIn("processed_vods.json public", script)
        self.assertNotIn("data/transcripts", script)

    def test_render_installs_dependencies_before_public_build(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("npm ci && npm ci --prefix frontend && npm run build:public", render)
        self.assertIn("staticPublishPath: public", render)

    def test_generated_output_has_dedicated_checks(self):
        self.assertTrue((ROOT / "scripts" / "check_public_build.py").is_file())
        self.assertTrue((ROOT / "scripts" / "check_public_reproducibility.py").is_file())
        self.assertTrue((ROOT / "playwright.public.config.js").is_file())

    def test_production_verification_fetches_existing_marker_parent(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        parent_lookup = 'parent_sha="$(git ls-remote origin "refs/heads/$verification_branch"'
        parent_fetch = 'git fetch --no-tags --depth=1 origin "refs/heads/$verification_branch"'
        parent_commit = 'git commit-tree "$tree_sha" -p "$parent_sha"'

        self.assertIn(parent_lookup, workflow)
        self.assertIn(parent_fetch, workflow)
        self.assertIn(parent_commit, workflow)
        self.assertLess(workflow.index(parent_fetch), workflow.index(parent_commit))


if __name__ == "__main__":
    unittest.main()
