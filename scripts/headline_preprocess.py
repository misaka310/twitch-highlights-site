from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

SOURCE_CLAUSE_EXTRA_CHARS = 28

COMMON_INTERJECTION_PATTERNS = [
    r"え+",
    r"あ+",
    r"お+",
    r"いや",
    r"まあ",
    r"まぁ",
    r"その",
    r"なんか",
    r"ほら",
    r"はい",
    r"え待って",
    r"あやったー",
]

COMMON_TRAILING_CHATTER_PATTERNS = [
    r"みんな知ってるそれ.*",
    r"最近来た人知らない.*",
    r"見てきて.*",
    r"知らないでしょ.*",
    r"今日も嫌がらせありがとうございます.*",
    r"嫌がらせコメントありがとうございます.*",
    r"誰が.*",
    r"落ちた.*",
    r"やったー.*",
    r"いらないかなぁ?.*",
    r"欲しいかもね.*",
]

COMMON_LOW_SIGNAL_PATTERNS = [
    r"見てきて",
    r"落ちた",
    r"誰が",
    r"やったー",
    r"ありがとうございます",
    r"ありがとう",
    r"みんな知ってるそれ",
    r"最近来た人知らないでしょ",
    r"いらないかなぁ?",
    r"欲しいかもね",
]

STREAMER_SPECIFIC_PATTERNS: dict[str, dict[str, list[str]]] = {
    "default": {
        "interjection": [],
        "trailing_chatter": [],
        "low_signal": [],
    }
}


@dataclass(frozen=True)
class SourcePatternConfig:
    interjection: list[str]
    trailing_chatter: list[str]
    low_signal: list[str]


@dataclass(frozen=True)
class CompiledSourcePatterns:
    sentence_split_re: re.Pattern[str]
    interjection_re: re.Pattern[str]
    trailing_chatter_re: re.Pattern[str]
    low_signal_re: re.Pattern[str]


@dataclass(frozen=True)
class SourcePreprocessContext:
    patterns: CompiledSourcePatterns
    source_clause_max_chars: int


Logger = Callable[[str], None]


def _join_or_never(patterns: list[str]) -> str:
    if not patterns:
        return r"(?!)"
    return "(?:" + "|".join(patterns) + ")"


def build_source_pattern_config(streamer_id: str | None = None) -> SourcePatternConfig:
    specific = STREAMER_SPECIFIC_PATTERNS.get(streamer_id or "", STREAMER_SPECIFIC_PATTERNS["default"])
    return SourcePatternConfig(
        interjection=[*COMMON_INTERJECTION_PATTERNS, *specific.get("interjection", [])],
        trailing_chatter=[*COMMON_TRAILING_CHATTER_PATTERNS, *specific.get("trailing_chatter", [])],
        low_signal=[*COMMON_LOW_SIGNAL_PATTERNS, *specific.get("low_signal", [])],
    )


def compile_source_patterns(config: SourcePatternConfig) -> CompiledSourcePatterns:
    interjection_body = _join_or_never(config.interjection)
    trailing_body = _join_or_never(config.trailing_chatter)
    low_signal_body = _join_or_never(config.low_signal)
    return CompiledSourcePatterns(
        sentence_split_re=re.compile(r"[\r\n。！？?!]+"),
        interjection_re=re.compile(rf"^{interjection_body}(?:[\s、。！？?!]+|$)", re.IGNORECASE),
        trailing_chatter_re=re.compile(rf"{trailing_body}$"),
        low_signal_re=re.compile(rf"^{low_signal_body}(?:[\s、。！？?!].*)?$"),
    )


def build_source_clause_max_chars(headline_max_chars: int) -> int:
    return max(1, int(headline_max_chars)) + SOURCE_CLAUSE_EXTRA_CHARS


def build_preprocess_context(*, headline_max_chars: int, streamer_id: str | None = None) -> SourcePreprocessContext:
    config = build_source_pattern_config(streamer_id=streamer_id)
    return SourcePreprocessContext(
        patterns=compile_source_patterns(config),
        source_clause_max_chars=build_source_clause_max_chars(headline_max_chars),
    )


def split_source_text(text: str, *, sentence_split_re: re.Pattern[str]) -> list[str]:
    return [part.strip() for part in sentence_split_re.split(str(text or "")) if part and part.strip()]


def is_low_signal_clause(
    clause: str,
    *,
    low_signal_re: re.Pattern[str],
    japanese_char_re: re.Pattern[str],
) -> bool:
    if not clause:
        return True
    if low_signal_re.fullmatch(clause):
        return True
    return len(japanese_char_re.findall(clause)) < 4 and len(clause) < 10


def normalize_source_clause(
    clause: str,
    *,
    normalize_source_text: Callable[[str], str],
    collapse_japanese_spacing: Callable[[str], str],
    smart_truncate: Callable[[str, int], str],
    filler_prefix_re: re.Pattern[str],
    japanese_char_re: re.Pattern[str],
    max_chars: int,
    interjection_re: re.Pattern[str],
    trailing_chatter_re: re.Pattern[str],
    low_signal_re: re.Pattern[str],
) -> str:
    cleaned = normalize_source_text(clause)
    if not cleaned:
        return ""

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = interjection_re.sub("", cleaned).strip()
        cleaned = filler_prefix_re.sub("", cleaned).strip()
        cleaned = trailing_chatter_re.sub("", cleaned).strip(" ,.!?、。！？")
        cleaned = normalize_source_text(cleaned)

    cleaned = collapse_japanese_spacing(cleaned)
    cleaned = re.sub(r"\b(?:w{2,}|www)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?、。！？")
    if not cleaned:
        return ""
    if is_low_signal_clause(cleaned, low_signal_re=low_signal_re, japanese_char_re=japanese_char_re):
        return ""
    if len(cleaned) > max_chars:
        cleaned = smart_truncate(cleaned, max_chars)
    return cleaned


def extract_candidate_clauses(
    text: str,
    *,
    normalize_source_text: Callable[[str], str],
    collapse_japanese_spacing: Callable[[str], str],
    smart_truncate: Callable[[str, int], str],
    filler_prefix_re: re.Pattern[str],
    japanese_char_re: re.Pattern[str],
    context: SourcePreprocessContext,
    logger: Logger | None = None,
) -> list[str]:
    clauses: list[str] = []
    parts = split_source_text(text, sentence_split_re=context.patterns.sentence_split_re)
    for idx, part in enumerate(parts, start=1):
        cleaned = normalize_source_clause(
            part,
            normalize_source_text=normalize_source_text,
            collapse_japanese_spacing=collapse_japanese_spacing,
            smart_truncate=smart_truncate,
            filler_prefix_re=filler_prefix_re,
            japanese_char_re=japanese_char_re,
            max_chars=context.source_clause_max_chars,
            interjection_re=context.patterns.interjection_re,
            trailing_chatter_re=context.patterns.trailing_chatter_re,
            low_signal_re=context.patterns.low_signal_re,
        )
        if cleaned:
            clauses.append(cleaned)
            if logger is not None:
                logger(f"debug: source clause accepted [{idx}] {cleaned}")
        elif logger is not None:
            logger(f"debug: source clause dropped [{idx}] {part.strip()}")
    return clauses
