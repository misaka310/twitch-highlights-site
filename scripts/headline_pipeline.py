from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import headline_preprocess as hpp
import headline_scoring as hls
import headline_validation as hlv


@dataclass(frozen=True)
class HeadlineLogContext:
    provider: str
    attempt: int
    max_attempts: int


@dataclass(frozen=True)
class SourceSelection:
    evaluations: list[Any]
    selected: list[str]
    source_text: str


Logger = Callable[[str], None]


def summarize_candidate_evaluations(
    evaluations: list[hls.CandidateEvaluation],
    *,
    logger: Logger,
) -> None:
    for idx, evaluation in enumerate(evaluations, start=1):
        logger(
            "debug: candidate "
            f"index={idx} text={evaluation.text} hard={evaluation.validation.hard_issues or 'none'} "
            f"soft={evaluation.validation.soft_issues or 'none'} "
            f"issue_codes={[code.value for code in evaluation.validation.issue_codes] or 'none'} "
            f"flags={evaluation.validation.info_flags or 'none'} tokenizer={evaluation.validation.tokenizer_name}"
        )
        logger(
            "debug: candidate score "
            f"index={idx} total={evaluation.score.total:.2f} base={evaluation.score.base_score:.2f} "
            f"penalties={evaluation.score.penalties:.2f} bonuses={evaluation.score.bonuses:.2f} "
            f"penalty_reasons={evaluation.score.penalty_reasons or 'none'}"
        )

    summary = hlv.summarize_validation_issues(evaluations)
    logger(
        "debug: candidate issue summary "
        f"candidates={summary.total_candidates} hard={summary.hard_issue_count} soft={summary.soft_issue_count} "
        f"codes={{ {', '.join(f'{code.value}:{count}' for code, count in summary.code_counts.items())} }}"
    )


def choose_best_candidate(
    evaluations: list[hls.CandidateEvaluation],
    *,
    logger: Logger,
) -> hls.CandidateEvaluation:
    ranked = sorted(evaluations, key=hls.rank_key, reverse=True)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    logger(
        "info: candidate winner "
        f"text={winner.text} {hls.diff_summary(winner, runner_up)} "
        f"hard={winner.validation.hard_issues or 'none'} soft={winner.validation.soft_issues or 'none'}"
    )
    return winner


def log_source_selection(selection: SourceSelection, *, logger: Logger) -> None:
    for idx, evaluation in enumerate(selection.evaluations, start=1):
        breakdown = evaluation.score.breakdown
        logger(
            "debug: source clause eval "
            f"index={idx} clause={evaluation.clause} score={evaluation.score.total:.2f} "
            f"length_factor={breakdown.length_factor:.2f} noise_factor={breakdown.noise_factor:.2f} "
            f"term_reuse_factor={breakdown.term_reuse_factor:.2f} "
            f"preferred_term_factor={breakdown.preferred_term_factor:.2f} "
            f"selected={evaluation.selected} reason={evaluation.reason}"
        )
    for idx, clause in enumerate(selection.selected, start=1):
        logger(f"debug: source clause selected[{idx}] {clause}")
    logger(f"info: source text prepared clauses={len(selection.selected)} text={selection.source_text}")


def log_provider_attempt(
    *,
    context: HeadlineLogContext,
    headline: str,
    validation_result: hlv.ValidationResult,
    logger: Logger,
) -> None:
    logger(
        "info: headline attempt "
        f"provider={context.provider} attempt={context.attempt}/{context.max_attempts} headline={headline} "
        f"hard={validation_result.hard_issues or 'none'} soft={validation_result.soft_issues or 'none'} "
        f"issue_codes={[code.value for code in validation_result.issue_codes] or 'none'} "
        f"flags={validation_result.info_flags or 'none'} tokenizer={validation_result.tokenizer_name}"
    )


def log_provider_error(*, context: HeadlineLogContext, reason: str, logger: Logger) -> None:
    logger(
        "warn: headline attempt failed "
        f"provider={context.provider} attempt={context.attempt}/{context.max_attempts} reason={reason}"
    )


def merge_preprocess_context(
    *,
    headline_max_chars: int,
    streamer_id: str | None,
) -> hpp.SourcePreprocessContext:
    return hpp.build_preprocess_context(headline_max_chars=headline_max_chars, streamer_id=streamer_id)


def should_retry_attempt(validation_result: hlv.ValidationResult) -> bool:
    return hlv.should_retry(validation_result)


def is_usable_remote_headline(validation_result: hlv.ValidationResult) -> bool:
    return validation_result.accepted


def format_rejection_summary(validation_result: hlv.ValidationResult) -> str:
    if not validation_result.hard_issues:
        return ""
    return "; ".join(validation_result.hard_issues[:2])


@dataclass(frozen=True)
class SourceValidationResult:
    accepted: bool
    reasons: list[str]
    content_word_count: int
    subject_hint_count: int
    action_hint_count: int
    unknown_ratio: float


SOURCE_VALIDATION_PENALTY_WEIGHTS: dict[str, float] = {
    "missing_action_hint": 0.8,
    "missing_subject_hint": 1.0,
    "too_few_content_words": 1.0,
    "incomplete_sentence": 0.6,
    "too_many_unknown_tokens": 1.4,
    "too_many_symbols": 1.2,
    "repeated_noise_phrase": 1.1,
    "greeting_only": 1.8,
    "reaction_only": 1.8,
    "call_only": 1.6,
    "empty_source": 2.4,
}
SOFT_SOURCE_REASONS = {
    "missing_action_hint",
    "missing_subject_hint",
    "too_few_content_words",
    "incomplete_sentence",
}


def compute_source_quality_penalty(validation: SourceValidationResult) -> float:
    return sum(SOURCE_VALIDATION_PENALTY_WEIGHTS.get(reason, 1.0) for reason in validation.reasons)


def decide_headline_generation_strategy(validation: SourceValidationResult) -> tuple[str, str, float]:
    if validation.accepted:
        return ("llm_ranked", "high", 0.0)

    penalty = compute_source_quality_penalty(validation)
    severe_reasons = [reason for reason in validation.reasons if reason not in SOFT_SOURCE_REASONS]
    if severe_reasons and penalty >= 3.0:
        return ("fallback_extractive", "low", penalty)

    confidence = "medium" if penalty <= 2.6 else "low"
    return ("weak_llm", confidence, penalty)


def should_skip_headline_generation(source_text: str, validation: SourceValidationResult) -> bool:
    del source_text, validation
    return False
