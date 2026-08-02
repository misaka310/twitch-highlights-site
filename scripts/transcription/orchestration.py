from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PipelineSteps:
    setup_execution: Callable[[list[str] | None], tuple[Any, Any]]
    collect_targets: Callable[..., Any]
    print_run_options: Callable[[Any], None]
    print_dry_run_targets: Callable[..., bool]
    setup_transcription_components: Callable[..., tuple[Any, Any, Any, Any, Any]]
    create_summary: Callable[[], Any]
    run_first_pass: Callable[..., Any]
    run_second_pass: Callable[..., Any]
    run_headlines: Callable[..., None]
    finalize_outputs: Callable[[Any, Any], None]
    print_summary: Callable[[Any], None]


def run_pipeline(argv: list[str] | None, *, steps: PipelineSteps) -> None:
    options, headline_source_config = steps.setup_execution(argv)
    collected = steps.collect_targets(options=options)
    if collected is None:
        return
    videos, headline_generator, targets = collected

    steps.print_run_options(options)
    if steps.print_dry_run_targets(targets, options=options):
        return

    (
        transcriber,
        transcript_prereq_error,
        first_pass_config,
        second_pass_config,
        retranscribe_config,
    ) = steps.setup_transcription_components(targets, options=options)
    summary = steps.create_summary()

    first_pass_results = steps.run_first_pass(
        targets,
        transcriber=transcriber,
        transcript_prereq_error=transcript_prereq_error,
        first_pass_config=first_pass_config,
        headline_source_config=headline_source_config,
        options=options,
        summary=summary,
    )
    first_pass_results = steps.run_second_pass(
        targets,
        first_pass_results=first_pass_results,
        transcriber=transcriber,
        second_pass_config=second_pass_config,
        retranscribe_config=retranscribe_config,
        headline_source_config=headline_source_config,
        options=options,
    )
    steps.run_headlines(
        targets,
        first_pass_results=first_pass_results,
        headline_generator=headline_generator,
        headline_source_config=headline_source_config,
        options=options,
        summary=summary,
    )
    steps.finalize_outputs(videos, targets)
    steps.print_summary(summary)
