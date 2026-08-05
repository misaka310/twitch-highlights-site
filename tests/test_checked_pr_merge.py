import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from checked_pr_merge import (  # noqa: E402
    REQUIRED_DISPATCH_WORKFLOWS,
    REQUIRED_PR_WORKFLOWS,
    build_parser,
    select_latest_workflow_run_ids,
)


class CheckedPullRequestMergeTests(unittest.TestCase):
    def test_selects_latest_run_for_each_required_workflow(self):
        runs = [
            {"databaseId": 10, "workflowName": "Frontend CI"},
            {"databaseId": 11, "workflowName": "Repository hygiene"},
            {"databaseId": 12, "workflowName": "Frontend CI"},
            {"databaseId": 13, "workflowName": "Repo Launch Doctor"},
            {"databaseId": 14, "workflowName": "Unrelated"},
        ]

        selected = select_latest_workflow_run_ids(runs)

        self.assertEqual(
            selected,
            {
                "Frontend CI": 12,
                "Repository hygiene": 11,
                "Repo Launch Doctor": 13,
            },
        )
        self.assertEqual(tuple(selected), REQUIRED_PR_WORKFLOWS)

    def test_trusted_dispatch_mode_has_explicit_workflow_files(self):
        self.assertEqual(
            REQUIRED_DISPATCH_WORKFLOWS,
            (
                ("Frontend CI", "ci.yml"),
                ("Repository hygiene", "repository-hygiene.yml"),
                ("Repo Launch Doctor", "repo-launch-doctor.yml"),
            ),
        )
        parsed = build_parser().parse_args(
            [
                "--branch",
                "automation/update-vods",
                "--head-sha",
                "abc",
                "--title",
                "title",
                "--body",
                "body",
                "--workflow-mode",
                "trusted-dispatch",
            ]
        )
        self.assertEqual(parsed.workflow_mode, "trusted-dispatch")

    def test_trusted_automation_workflows_are_dispatchable_without_live_checks(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        hygiene = (ROOT / ".github" / "workflows" / "repository-hygiene.yml").read_text(encoding="utf-8")
        update = (ROOT / ".github" / "workflows" / "update-vods.yml").read_text(encoding="utf-8")

        self.assertIn("run_live:", ci)
        self.assertIn("inputs.run_live == true", ci)
        self.assertIn("workflow_dispatch:", hygiene)
        self.assertIn("--workflow-mode trusted-dispatch", update)

    def test_release_and_update_workflows_delegate_checked_merge(self):
        script_reference = "python .github/scripts/checked_pr_merge.py"
        release = (ROOT / ".github" / "workflows" / "publish-release.yml").read_text(encoding="utf-8")
        update = (ROOT / ".github" / "workflows" / "update-vods.yml").read_text(encoding="utf-8")

        self.assertIn(script_reference, release)
        self.assertIn("--workflow-mode trusted-dispatch", release)
        self.assertIn(script_reference, update)
        for workflow in (release, update):
            self.assertNotIn('required_pr_workflows=("Frontend CI"', workflow)
            self.assertNotIn("gh run watch", workflow)


if __name__ == "__main__":
    unittest.main()
