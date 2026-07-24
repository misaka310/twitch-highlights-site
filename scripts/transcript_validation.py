from __future__ import annotations

import re
from typing import Any, Callable, Pattern


def transcript_quality_metrics(
    text: str,
    *,
    content_token_re: Pattern[str],
    interjection_token_re: Pattern[str],
) -> dict[str, float]:
    tokens = [token for token in re.split(r"[\s??,.!???]+", str(text or "")) if token]
    content_count = sum(1 for token in tokens if content_token_re.search(token))
    interjection_count = sum(1 for token in tokens if interjection_token_re.search(token))
    suspicious_count = sum(
        1
        for token in tokens
        if len(token) <= 2 or re.search(r"[\?繝ｻ・ｽ]{2,}", token) or token.isdigit()
    )
    token_count = len(tokens)
    return {
        "token_count": float(token_count),
        "content_count": float(content_count),
        "interjection_ratio": (interjection_count / token_count) if token_count else 1.0,
        "suspicious_ratio": (suspicious_count / token_count) if token_count else 1.0,
    }


def score_retranscribe_priority(
    item: dict[str, Any],
    transcript_text: str,
    config: Any,
    *,
    to_int: Callable[[Any], int | None],
    to_optional_float: Callable[[Any], float | None],
    content_token_re: Pattern[str],
    interjection_token_re: Pattern[str],
) -> float:
    metrics = transcript_quality_metrics(
        transcript_text,
        content_token_re=content_token_re,
        interjection_token_re=interjection_token_re,
    )
    base = 0.0
    rank = to_int(item.get("rank"))
    if rank is not None and rank <= max(1, config.top_n):
        base += 100 - rank
    score = to_optional_float(item.get("score"))
    if score is not None:
        base += max(0.0, score) * 3.0
    if metrics["token_count"] <= config.low_info_token_threshold:
        base += 15.0
    if metrics["suspicious_ratio"] >= config.suspicious_ratio_threshold:
        base += 20.0
    return base


def should_retranscribe_clip(
    item: dict[str, Any],
    transcript_text: str,
    config: Any,
    *,
    to_int: Callable[[Any], int | None],
    to_optional_float: Callable[[Any], float | None],
    content_token_re: Pattern[str],
    interjection_token_re: Pattern[str],
) -> bool:
    if not config.enabled:
        return False
    mode = (config.selection_mode or "hybrid").strip().lower()
    rank = to_int(item.get("rank"))
    zscore_rank = to_int(item.get("_second_pass_zscore_rank"))
    metrics = transcript_quality_metrics(
        transcript_text,
        content_token_re=content_token_re,
        interjection_token_re=interjection_token_re,
    )
    low_info = metrics["token_count"] <= config.low_info_token_threshold
    suspicious = metrics["suspicious_ratio"] >= config.suspicious_ratio_threshold

    rank_hit = rank is not None and rank <= config.top_n
    zscore_hit = zscore_rank is not None and zscore_rank <= config.top_n
    quality_hit = low_info or suspicious

    if mode == "rank":
        return rank_hit
    if mode == "zscore":
        return zscore_hit
    if mode == "quality":
        return quality_hit
    return rank_hit or zscore_hit or quality_hit


def annotate_zscore_rank(
    targets: list[Any],
    *,
    to_optional_float: Callable[[Any], float | None],
) -> None:
    scored = [
        target
        for target in targets
        if isinstance(target.item, dict) and to_optional_float(target.item.get("score")) is not None
    ]
    for idx, target in enumerate(
        sorted(scored, key=lambda row: to_optional_float(row.item.get("score")) or 0.0, reverse=True),
        start=1,
    ):
        target.item["_second_pass_zscore_rank"] = idx
