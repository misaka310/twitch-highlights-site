from __future__ import annotations

from dataclasses import dataclass

import headline_validation as hlv


@dataclass(frozen=True)
class HeadlineScore:
    total: float
    base_score: float
    penalties: float
    bonuses: float
    penalty_reasons: list[str]
    bonus_reasons: list[str]


@dataclass(frozen=True)
class CandidateEvaluation:
    text: str
    validation: hlv.ValidationResult
    score: HeadlineScore


def score_headline(
    *,
    headline: str,
    source_terms: list[str],
    base_score: float,
    validation_result: hlv.ValidationResult,
) -> HeadlineScore:
    penalties = 0.0
    bonuses = 0.0
    penalty_reasons: list[str] = []
    bonus_reasons: list[str] = []

    for issue in validation_result.issues:
        if issue.severity == hlv.ValidationSeverity.HARD:
            penalties += 2.0
            penalty_reasons.append(f"hard_issue:{issue.code.value}")
        else:
            penalties += 0.6
            penalty_reasons.append(f"soft_issue:{issue.code.value}")

    for flag in validation_result.info_items:
        if flag.code == hlv.ValidationInfoCode.CONTAINS_SOFT_DROP_TOKEN:
            penalties += 0.8
            penalty_reasons.append(flag.label)
        elif flag.code == hlv.ValidationInfoCode.CONTAINS_REFLECTIVE_TOKEN:
            penalties += 0.3
            penalty_reasons.append(flag.label)

    if source_terms and any(term in validation_result.headline for term in source_terms[:2]):
        bonuses += 0.4
        bonus_reasons.append("bonus:reuses_top_source_terms")

    return HeadlineScore(
        total=base_score + bonuses - penalties,
        base_score=base_score,
        penalties=penalties,
        bonuses=bonuses,
        penalty_reasons=penalty_reasons,
        bonus_reasons=bonus_reasons,
    )


def evaluate_candidate(
    *,
    text: str,
    source_terms: list[str],
    base_score: float,
    validation_result: hlv.ValidationResult,
) -> CandidateEvaluation:
    score = score_headline(
        headline=text,
        source_terms=source_terms,
        base_score=base_score,
        validation_result=validation_result,
    )
    return CandidateEvaluation(text=text, validation=validation_result, score=score)


def rank_key(evaluation: CandidateEvaluation) -> tuple[int, int, float]:
    return (-len(evaluation.validation.hard_issues), -len(evaluation.validation.soft_issues), evaluation.score.total)


def diff_summary(winner: CandidateEvaluation, runner_up: CandidateEvaluation | None) -> str:
    if runner_up is None:
        return "winner only"
    delta = winner.score.total - runner_up.score.total
    return f"score_delta={delta:.2f}"
