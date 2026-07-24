from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

try:
    from rapidfuzz import fuzz as _fuzz
except Exception:  # pragma: no cover - optional dependency
    _fuzz = None


@dataclass(frozen=True)
class TermEntry:
    canonical: str
    aliases: tuple[str, ...]
    category: str
    exact_aliases: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class TermDictionary:
    entries: tuple[TermEntry, ...]
    optional_aliases: dict[str, str]


@dataclass(frozen=True)
class TermNormalizationConfig:
    similarity_threshold: int
    min_token_len: int
    min_term_len: int


@dataclass(frozen=True)
class TermReplacement:
    original: str
    replacement: str
    category: str
    similarity: float


@dataclass(frozen=True)
class NormalizedTranscriptResult:
    text: str
    replacements: tuple[TermReplacement, ...]


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=str(left or ""), b=str(right or "")).ratio()


def fuzzy_similarity(left: str, right: str) -> float:
    a = str(left or "").strip().lower()
    b = str(right or "").strip().lower()
    if not a or not b:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.ratio(a, b))
    return text_similarity(a, b) * 100.0


def load_term_dictionary(path: Path | str) -> TermDictionary:
    target = Path(path)
    if not target.exists():
        print(f"debug: term dictionary not found path={target}")
        return TermDictionary(entries=tuple(), optional_aliases={})

    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    entries: list[TermEntry] = []
    for category in ("game_terms", "streamer_terms", "title_terms"):
        for row in payload.get(category) or []:
            if not isinstance(row, dict):
                continue
            canonical = str(row.get("canonical") or "").strip()
            if not canonical:
                continue
            aliases = tuple(
                alias.strip()
                for alias in (row.get("aliases") or [])
                if isinstance(alias, str) and alias.strip()
            )
            raw_exact_aliases = row.get("exact_aliases")
            exact_aliases = tuple(
                alias.strip()
                for alias in (raw_exact_aliases if isinstance(raw_exact_aliases, list) else [])
                if isinstance(alias, str) and alias.strip()
            )
            entries.append(
                TermEntry(
                    canonical=canonical,
                    aliases=aliases,
                    category=category,
                    exact_aliases=exact_aliases,
                )
            )

    optional_aliases = {
        str(key).strip(): str(value).strip()
        for key, value in (payload.get("optional_aliases") or {}).items()
        if str(key).strip() and str(value).strip()
    }
    return TermDictionary(entries=tuple(entries), optional_aliases=optional_aliases)


def _replace_by_similarity(
    token: str,
    canonical: str,
    *,
    category: str,
    threshold: int,
) -> TermReplacement | None:
    similarity = fuzzy_similarity(token, canonical)
    if similarity < threshold:
        return None
    return TermReplacement(
        original=token,
        replacement=canonical,
        category=category,
        similarity=similarity,
    )


def normalize_transcript_terms(
    text: str,
    term_dict: TermDictionary,
    config: TermNormalizationConfig,
) -> NormalizedTranscriptResult:
    if not text or not term_dict.entries:
        return NormalizedTranscriptResult(text=str(text or ""), replacements=tuple())

    normalized = str(text)
    replacements: list[TermReplacement] = []

    for alias, canonical in term_dict.optional_aliases.items():
        if len(alias) < config.min_term_len:
            continue
        if alias in normalized and alias != canonical:
            normalized = normalized.replace(alias, canonical)
            replacements.append(
                TermReplacement(
                    original=alias,
                    replacement=canonical,
                    category="optional_aliases",
                    similarity=100.0,
                )
            )

    token_pattern = re.compile(r"[^\s??,.!???]+")

    def _rewrite_token(match: re.Match[str]) -> str:
        token = match.group(0)
        if len(token) < config.min_token_len:
            return token

        best: TermReplacement | None = None
        for entry in term_dict.entries:
            if len(entry.canonical) < config.min_term_len:
                continue
            candidates = (entry.canonical,) + entry.aliases
            for candidate in candidates:
                if len(candidate) < config.min_term_len:
                    continue
                replacement = _replace_by_similarity(
                    token,
                    candidate,
                    category=entry.category,
                    threshold=config.similarity_threshold,
                )
                if replacement is not None:
                    replacement = TermReplacement(
                        original=token,
                        replacement=entry.canonical,
                        category=entry.category,
                        similarity=replacement.similarity,
                    )
                if replacement is None:
                    continue
                if best is None or replacement.similarity > best.similarity:
                    best = replacement
        if best is None:
            return token
        if best.original != best.replacement:
            replacements.append(best)
        return best.replacement

    normalized = token_pattern.sub(_rewrite_token, normalized)
    return NormalizedTranscriptResult(text=normalized, replacements=tuple(replacements))


def merge_term_dictionaries(*term_dictionaries: TermDictionary) -> TermDictionary:
    entries: list[TermEntry] = []
    optional_aliases: dict[str, str] = {}
    seen_keys: set[tuple[str, str]] = set()

    for term_dictionary in term_dictionaries:
        for entry in term_dictionary.entries:
            key = (entry.category, entry.canonical)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            entries.append(entry)
        for alias, canonical in term_dictionary.optional_aliases.items():
            optional_aliases[alias] = canonical

    return TermDictionary(entries=tuple(entries), optional_aliases=optional_aliases)


def resolve_active_term_dictionary(
    *,
    use_game_term_dictionary: bool,
    base_term_dictionary: TermDictionary,
    game_term_dictionary: TermDictionary,
) -> TermDictionary:
    if use_game_term_dictionary:
        return merge_term_dictionaries(base_term_dictionary, game_term_dictionary)
    return base_term_dictionary
