from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from transcription.orchestration import PipelineSteps, run_pipeline


class OrchestrationTests(unittest.TestCase):
    def build_steps(self, events: list[str], *, collect=True, dry_run=False) -> PipelineSteps:
        def setup(argv):
            events.append(f"setup:{argv}")
            return "options", "headline-config"

        def collect_targets(*, options):
            events.append(f"collect:{options}")
            return ("videos", "generator", "targets") if collect else None

        def print_options(options):
            events.append(f"print-options:{options}")

        def print_dry(targets, *, options):
            events.append(f"dry-run:{targets}:{options}")
            return dry_run

        def setup_components(targets, *, options):
            events.append(f"components:{targets}:{options}")
            return "transcriber", "prereq", "first-config", "second-config", "retranscribe"

        def first_pass(targets, **kwargs):
            events.append(f"first:{targets}:{kwargs['headline_source_config']}")
            return "first-results"

        def second_pass(targets, **kwargs):
            events.append(f"second:{targets}:{kwargs['first_pass_results']}")
            return "second-results"

        def headlines(targets, **kwargs):
            events.append(f"headlines:{targets}:{kwargs['first_pass_results']}")

        def finalize(videos, targets):
            events.append(f"finalize:{videos}:{targets}")

        def summary():
            events.append("summary")
            return "summary-value"

        def print_summary(value):
            events.append(f"print-summary:{value}")

        return PipelineSteps(
            setup_execution=setup,
            collect_targets=collect_targets,
            print_run_options=print_options,
            print_dry_run_targets=print_dry,
            setup_transcription_components=setup_components,
            create_summary=summary,
            run_first_pass=first_pass,
            run_second_pass=second_pass,
            run_headlines=headlines,
            finalize_outputs=finalize,
            print_summary=print_summary,
        )

    def test_runs_the_existing_pipeline_order(self):
        events: list[str] = []
        run_pipeline(["--example"], steps=self.build_steps(events))
        self.assertEqual(
            events,
            [
                "setup:['--example']",
                "collect:options",
                "print-options:options",
                "dry-run:targets:options",
                "components:targets:options",
                "summary",
                "first:targets:headline-config",
                "second:targets:first-results",
                "headlines:targets:second-results",
                "finalize:videos:targets",
                "print-summary:summary-value",
            ],
        )

    def test_stops_when_preconditions_fail(self):
        events: list[str] = []
        run_pipeline(None, steps=self.build_steps(events, collect=False))
        self.assertEqual(events, ["setup:None", "collect:options"])

    def test_dry_run_stops_before_transcription_setup(self):
        events: list[str] = []
        run_pipeline([], steps=self.build_steps(events, dry_run=True))
        self.assertEqual(
            events,
            ["setup:[]", "collect:options", "print-options:options", "dry-run:targets:options"],
        )


if __name__ == "__main__":
    unittest.main()
