from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Iterable, Protocol

HEADLINE_ALLOWED_CHARS_RE = re.compile(r"^[一-鿿゠-ヿA-Za-z0-9\s、,\-・]+$")
REFLECTIVE_HEADLINE_TOKENS = {"反省", "振り返り", "検証", "相談", "解説", "紹介", "報告"}
SOFT_DROP_HEADLINE_TOKENS = {"雑談"}
SOFT_HEADLINE_ISSUES = {"does not reuse enough source terms"}
FUNCTION_LIKE_POS_TAGS = {"助詞", "助動詞", "動詞", "形容詞", "形状詞"}


class ValidationSeverity(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class ValidationIssueCode(str, Enum):
    EMPTY = "empty"
    META_WORDING = "meta_wording"
    SENSITIVE = "sensitive"
    TOO_VAGUE = "too_vague"
    TOO_SHORT = "too_short"
    BROKEN_PHRASE = "broken_phrase"
    MISSING_FUNCTION_WORD = "missing_function_word"
    NOUN_LIST_LIKE = "noun_list_like"
    EMOJI = "emoji"
    TOO_MANY_SYMBOLS = "too_many_symbols"
    SOURCE_TERM_REUSE = "source_term_reuse"


class ValidationInfoCode(str, Enum):
    CONTAINS_SOFT_DROP_TOKEN = "contains_soft_drop_token"
    CONTAINS_REFLECTIVE_TOKEN = "contains_reflective_token"


@dataclass(frozen=True)
class ValidationIssue:
    code: ValidationIssueCode
    message: str
    severity: ValidationSeverity


@dataclass(frozen=True)
class ValidationInfoFlag:
    code: ValidationInfoCode
    token: str

    @property
    def label(self) -> str:
        return f"{self.code.value}:{self.token}"


@dataclass(frozen=True)
class ValidationResult:
    headline: str
    issues: list[ValidationIssue]
    info_items: list[ValidationInfoFlag]
    tokenized: list[str]
    tokenizer_name: str
    tokenizer_is_fallback: bool

    @property
    def hard_issues(self) -> list[str]:
        return [issue.message for issue in self.issues if issue.severity == ValidationSeverity.HARD]

    @property
    def soft_issues(self) -> list[str]:
        return [issue.message for issue in self.issues if issue.severity == ValidationSeverity.SOFT]

    @property
    def accepted(self) -> bool:
        return not self.hard_issues

    @property
    def issue_codes(self) -> list[ValidationIssueCode]:
        return [issue.code for issue in self.issues]

    @property
    def info_flags(self) -> list[str]:
        return [item.label for item in self.info_items]

    @property
    def issue_messages(self) -> list[str]:
        return [issue.message for issue in self.issues]


class TokenizerAdapter(Protocol):
    name: str
    is_fallback: bool

    def tokenize_text(self, text: str) -> list[str]:
        ...

    def has_function_like_token(self, text: str, *, function_word_re: re.Pattern[str]) -> bool:
        ...


class RegexFallbackTokenizer:
    name = "regex_fallback"
    is_fallback = True

    def tokenize_text(self, text: str) -> list[str]:
        return [token for token in re.split(r"[\s、。,!！？/]+", str(text or "")) if token]

    def has_function_like_token(self, text: str, *, function_word_re: re.Pattern[str]) -> bool:
        if function_word_re.search(text):
            return True
        return any(function_word_re.search(token) for token in self.tokenize_text(text))


class SudachiPyTokenizer:
    name = "sudachipy"
    is_fallback = False

    def __init__(self) -> None:
        from sudachipy import Dictionary, SplitMode

        self._tokenizer = Dictionary().create()
        self._split_mode = SplitMode.C

    def _morphemes(self, text: str):
        return self._tokenizer.tokenize(str(text or ""), self._split_mode)

    def tokenize_text(self, text: str) -> list[str]:
        return [token.surface() for token in self._morphemes(text) if token.surface()]

    def has_function_like_token(self, text: str, *, function_word_re: re.Pattern[str]) -> bool:
        for token in self._morphemes(text):
            surface = token.surface()
            if not surface:
                continue
            pos = token.part_of_speech()
            pos_major = pos[0] if pos else ""
            if pos_major in FUNCTION_LIKE_POS_TAGS:
                return True
            if pos_major == "名詞" and function_word_re.search(surface):
                return True
        return False


def _build_default_tokenizer() -> TokenizerAdapter:
    preferred = (os.environ.get("HEADLINE_TOKENIZER") or "auto").strip().lower()
    if preferred in {"regex", "fallback"}:
        return RegexFallbackTokenizer()
    if preferred not in {"auto", "", "sudachi", "sudachipy"}:
        return RegexFallbackTokenizer()
    try:
        return SudachiPyTokenizer()
    except Exception:
        return RegexFallbackTokenizer()


@lru_cache(maxsize=1)
def get_default_tokenizer() -> TokenizerAdapter:
    return _build_default_tokenizer()


DEFAULT_TOKENIZER = get_default_tokenizer()


def resolve_tokenizer(tokenizer: TokenizerAdapter | None = None) -> TokenizerAdapter:
    return tokenizer or get_default_tokenizer()


def tokenize_text(text: str, tokenizer: TokenizerAdapter | None = None) -> list[str]:
    active = resolve_tokenizer(tokenizer)
    return active.tokenize_text(text)


def contains_function_like_tokens(
    headline: str,
    *,
    function_word_re: re.Pattern[str],
    tokenizer: TokenizerAdapter | None = None,
) -> bool:
    active = resolve_tokenizer(tokenizer)
    return active.has_function_like_token(headline, function_word_re=function_word_re)


def split_headline_issues(
    issues: list[str],
    *,
    soft_issue_set: set[str] = SOFT_HEADLINE_ISSUES,
) -> tuple[list[str], list[str]]:
    hard_issues = [issue for issue in issues if issue not in soft_issue_set]
    soft_issues = [issue for issue in issues if issue in soft_issue_set]
    return hard_issues, soft_issues


def _collect_info_flags(
    headline: str,
    *,
    soft_drop_tokens: set[str] = SOFT_DROP_HEADLINE_TOKENS,
    reflective_tokens: set[str] = REFLECTIVE_HEADLINE_TOKENS,
) -> list[ValidationInfoFlag]:
    flags: list[ValidationInfoFlag] = []
    for token in sorted(soft_drop_tokens):
        if token in headline:
            flags.append(ValidationInfoFlag(code=ValidationInfoCode.CONTAINS_SOFT_DROP_TOKEN, token=token))
    for token in sorted(reflective_tokens):
        if token in headline:
            flags.append(ValidationInfoFlag(code=ValidationInfoCode.CONTAINS_REFLECTIVE_TOKEN, token=token))
    return flags


def _append_issue(
    issues: list[ValidationIssue],
    *,
    code: ValidationIssueCode,
    message: str,
    severity: ValidationSeverity,
) -> None:
    issues.append(ValidationIssue(code=code, message=message, severity=severity))


def _dedupe_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    deduped: list[ValidationIssue] = []
    seen: set[tuple[ValidationIssueCode, ValidationSeverity]] = set()
    for issue in issues:
        key = (issue.code, issue.severity)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def validate_headline(
    headline: str,
    source_terms: list[str],
    *,
    sanitize_headline: Callable[[str], str],
    meta_re: re.Pattern[str],
    sensitive_re: re.Pattern[str],
    low_signal_re: re.Pattern[str],
    broken_phrase_re: re.Pattern[str],
    function_word_re: re.Pattern[str],
    contains_emoji: Callable[[str], bool],
    has_excessive_symbols: Callable[[str], bool],
    allowed_chars_re: re.Pattern[str] = HEADLINE_ALLOWED_CHARS_RE,
    soft_issue_set: set[str] = SOFT_HEADLINE_ISSUES,
    tokenizer: TokenizerAdapter | None = None,
) -> ValidationResult:
    value = sanitize_headline(headline)
    active_tokenizer = resolve_tokenizer(tokenizer)
    issues: list[ValidationIssue] = []

    if not value:
        _append_issue(
            issues,
            code=ValidationIssueCode.EMPTY,
            message="headline is empty",
            severity=ValidationSeverity.HARD,
        )
    else:
        if meta_re.search(value):
            _append_issue(
                issues,
                code=ValidationIssueCode.META_WORDING,
                message="contains stream or platform meta wording",
                severity=ValidationSeverity.HARD,
            )
        if sensitive_re.search(value):
            _append_issue(
                issues,
                code=ValidationIssueCode.SENSITIVE,
                message="contains sensitive wording",
                severity=ValidationSeverity.HARD,
            )
        if low_signal_re.search(value) and len(re.findall(r"[\u30a0-\u30ff\u4e00-\u9fff]", value)) < 4:
            _append_issue(
                issues,
                code=ValidationIssueCode.TOO_VAGUE,
                message="is too vague",
                severity=ValidationSeverity.HARD,
            )
        if len(value) < 8 and len(re.findall(r"[\u30a0-\u30ff\u4e00-\u9fff]", value)) < 4:
            _append_issue(
                issues,
                code=ValidationIssueCode.TOO_SHORT,
                message="is too short",
                severity=ValidationSeverity.HARD,
            )
        if broken_phrase_re.search(value):
            _append_issue(
                issues,
                code=ValidationIssueCode.BROKEN_PHRASE,
                message="contains a broken phrase",
                severity=ValidationSeverity.HARD,
            )
        if not contains_function_like_tokens(value, function_word_re=function_word_re, tokenizer=active_tokenizer):
            _append_issue(
                issues,
                code=ValidationIssueCode.MISSING_FUNCTION_WORD,
                message="is missing a particle, verb, or adjective",
                severity=ValidationSeverity.HARD,
            )
        if allowed_chars_re.fullmatch(value) and re.search(r"[\s\u3001,\u30fb]", value):
            _append_issue(
                issues,
                code=ValidationIssueCode.NOUN_LIST_LIKE,
                message="looks like a noun list instead of a natural phrase",
                severity=ValidationSeverity.HARD,
            )
        if contains_emoji(value):
            _append_issue(
                issues,
                code=ValidationIssueCode.EMOJI,
                message="contains emoji",
                severity=ValidationSeverity.HARD,
            )
        if has_excessive_symbols(value):
            _append_issue(
                issues,
                code=ValidationIssueCode.TOO_MANY_SYMBOLS,
                message="contains too many symbols",
                severity=ValidationSeverity.HARD,
            )

        if source_terms and not any(term in value for term in source_terms[:4]):
            severity = ValidationSeverity.SOFT
            if "does not reuse enough source terms" not in soft_issue_set:
                severity = ValidationSeverity.HARD
            _append_issue(
                issues,
                code=ValidationIssueCode.SOURCE_TERM_REUSE,
                message="does not reuse enough source terms",
                severity=severity,
            )

    deduped_issues = _dedupe_issues(issues)
    return ValidationResult(
        headline=value,
        issues=deduped_issues,
        info_items=_collect_info_flags(value),
        tokenized=tokenize_text(value, tokenizer=active_tokenizer),
        tokenizer_name=active_tokenizer.name,
        tokenizer_is_fallback=active_tokenizer.is_fallback,
    )


def should_retry(validation_result: ValidationResult) -> bool:
    return not validation_result.accepted


def _as_validation_result(item: Any) -> ValidationResult | None:
    if isinstance(item, ValidationResult):
        return item
    validation = getattr(item, "validation", None)
    if isinstance(validation, ValidationResult):
        return validation
    return None


def count_issue_codes(items: Iterable[Any]) -> Counter[ValidationIssueCode]:
    counts: Counter[ValidationIssueCode] = Counter()
    for item in items:
        result = _as_validation_result(item)
        if result is None:
            continue
        for issue in result.issues:
            counts[issue.code] += 1
    return counts


@dataclass(frozen=True)
class ValidationIssueSummary:
    total_candidates: int
    hard_issue_count: int
    soft_issue_count: int
    code_counts: dict[ValidationIssueCode, int]


def summarize_validation_issues(items: Iterable[Any]) -> ValidationIssueSummary:
    results = [result for result in (_as_validation_result(item) for item in items) if result is not None]
    hard_issue_count = 0
    soft_issue_count = 0
    for result in results:
        for issue in result.issues:
            if issue.severity == ValidationSeverity.HARD:
                hard_issue_count += 1
            else:
                soft_issue_count += 1
    return ValidationIssueSummary(
        total_candidates=len(results),
        hard_issue_count=hard_issue_count,
        soft_issue_count=soft_issue_count,
        code_counts=dict(count_issue_codes(results)),
    )
