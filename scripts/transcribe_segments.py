from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib import error

import headline_pipeline as hlp
import headline_preprocess as hpp
import headline_scoring as hls
import headline_validation as hlv
import headline_generation as hlg
import transcript_io as tio
import transcript_postprocess as tpp
import transcript_validation as tv
from transcription import audio_extraction as tx_audio
from transcription import screenshot as tx_screenshot
from transcription import segment_persistence as tx_persistence
from transcription import target_selection as tx_targets
from transcription import whisper_runner as tx_whisper
from transcription.cli import RunOptions, build_run_options, parse_cli_args
from transcription.config import PipelineSettings

from transcript_postprocess import (
    NormalizedTranscriptResult,
    TermDictionary,
    TermNormalizationConfig,
)

from update_vods import (
    ENV_PATH,
    CACHE_PATH,
    OUT_PATH,
    build_segment_screenshot_file_path,
    build_segment_screenshot_public_path,
    load_local_env,
    write_processed_cache,
    write_public_data,
)

HeadlineProviderError = hlg.HeadlineProviderError


def apply_pipeline_settings(settings: PipelineSettings) -> None:
    globals().update(settings.as_globals())


apply_pipeline_settings(PipelineSettings.from_env({}))

SEGMENT_SCREENSHOT_WIDTH = 192
SEGMENT_SCREENSHOT_HEIGHT = 108
SEGMENT_SCREENSHOT_CAPTURE_OFFSET_SEC = 1.0
SEGMENT_SCREENSHOT_TIMEOUT_SEC = 30
SEGMENT_SCREENSHOT_QUALITY = 72
LOCAL_HEADLINE_MODEL = "extractive-ja-v1"
DEFAULT_HEADLINE_TEXT = "\u898b\u3069\u3053\u308d\u30af\u30ea\u30c3\u30d7"
JAPANESE_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
FILLER_PREFIX_RE = re.compile(
    r"^(?:\u3048+\u30fc*|\u3042\u306e|\u307e\u3042|\u306a\u3093\u304b|\u3066\u3044\u3046\u304b|\u305d\u306e|\u3044\u3084|\u3082\u3046|\u3046\u30fc\u3093|\u307b\u3093\u3068|\u3061\u3087\u3063\u3068|\u305f\u3076\u3093|\u308f\u304b\u3093\u306a\u3044)(?:[\s,\.\!\?\u3001\u3002\uff01\uff1f]+|$)",
    re.IGNORECASE,
)
WEAK_HEADLINE_RE = re.compile(
    r"^(?:\u5927\u4e08\u592b|\u3084\u3070\u3044|\u307e\u3058|\u306a\u3093\u304b|\u3042\u306e|\u305d\u306e|\u3042\u308c|\u3082\u3046|\u307b\u3093\u3068)(?:[\s\!\?\u3001\u3002\uff01\uff1f]+)?$"
)
HEADLINE_KEYWORD_RE = re.compile(
    r"(?:\u3084\u3070|\u307e\u3058|\u795e|\u7b11|\u7206\u7b11|\u885d\u6483|\u30db\u30e9\u30fc|\u6016|\u3059\u3054|\u5f37|\u4e0a\u624b|\u3069\u3046\u3057\u3066|\u306a\u3093\u3067)"
)
HEADLINE_META_RE = re.compile(
    r"(?:\u914d\u4fe1|\u8996\u8074\u8005|\u30c1\u30e3\u30c3\u30c8\u6b04|\u30b3\u30e1\u30f3\u30c8|\u30b5\u30d6\u30b9\u30af|\u30d5\u30a9\u30ed\u30fc|URL|IP|YouTube|\u3064\u3079|\u4e8b\u696d\u90e8|\u5e74\u91d1)"
)
HEADLINE_SENSITIVE_RE = re.compile(
    r"(?:\u9b31\u75c5|\u3046\u3064\u75c5|[\u3040-\u30ff\u4e00-\u9fffA-Za-z]*\u75c5|\u4f11\u8077|\u7247\u89aa|\u81ea\u4e3b\u5bfe\u8c61|\u6b53\u8fce\u914d\u4fe1|\u6b7b\u306b\u305d\u3046|\u6b7b\u306c\u307e\u3067)"
)
HEADLINE_LOW_SIGNAL_RE = re.compile(
    r"^(?:\u3053\u3053|\u305d\u3053|\u3053\u308c|\u305d\u308c|\u3042\u308c|\u306a\u3093\u304b|\u307f\u3093\u306a|\u3061\u3087\u3063\u3068)"
)
HEADLINE_BROKEN_PHRASE_RE = re.compile(
    r"(?:\u306e\u3059\u3054\u3055$|\u306e\u3059\u3054\u3044\u306a$|\u30bf\u30a4\u30e1\u30f3\u30c8|\u751f\u6d3b\u611f$|\u6c17\u6301\u3061\u304c\u751f\u307e\u308c\u307e\u3059$)"
)
HEADLINE_FUNCTION_WORD_RE = re.compile(r"(?:\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068|\u3082|\u3078|\u3084|\u304b|\u306a|\u306d)")
HEADLINE_ALLOWED_CHARS_RE = hlv.HEADLINE_ALLOWED_CHARS_RE
HEADLINE_NOUN_LIST_ONLY_RE = HEADLINE_ALLOWED_CHARS_RE
REFLECTIVE_HEADLINE_TOKENS = hlv.REFLECTIVE_HEADLINE_TOKENS
SOFT_DROP_HEADLINE_TOKENS = hlv.SOFT_DROP_HEADLINE_TOKENS
SOFT_HEADLINE_ISSUES = hlv.SOFT_HEADLINE_ISSUES
SOURCE_CLAUSE_EXTRA_CHARS = hpp.SOURCE_CLAUSE_EXTRA_CHARS
PREPROCESS_CONTEXT = hlp.merge_preprocess_context(
    headline_max_chars=HEADLINE_MAX_CHARS,
    streamer_id=HEADLINE_STREAMER_ID,
)
SOURCE_SENTENCE_SPLIT_RE = PREPROCESS_CONTEXT.patterns.sentence_split_re
SOURCE_INTERJECTION_RE = PREPROCESS_CONTEXT.patterns.interjection_re
SOURCE_TRAILING_CHATTER_RE = PREPROCESS_CONTEXT.patterns.trailing_chatter_re
SOURCE_LOW_SIGNAL_CLAUSE_RE = PREPROCESS_CONTEXT.patterns.low_signal_re
SOURCE_CLAUSE_MAX_CHARS = PREPROCESS_CONTEXT.source_clause_max_chars
SOURCE_ONLY_GREET_RE = re.compile(
    r"^(?:hello|hi|hey|thanks|ok|okay|yeah|hmm|wow|lol|lmao|gg|www+|grass+|nice)[\s,.!?\"']*$",
    re.IGNORECASE,
)
SOURCE_INTERJECTION_TOKEN_RE = re.compile(
    r"(?:uh+|um+|hmm+|like|you know|well|yeah|ok|wow|lol|www+|grass+)",
    re.IGNORECASE,
)
SOURCE_CONTENT_TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}|[\u30a1-\u30ff]{3,}|[\u4e00-\u9fff]{2,}")
SOURCE_GREETING_ONLY_RE = re.compile(
    r"^(?:"
    r"\u3053\u3093\u306b\u3061\u306f|\u3053\u3093\u3070\u3093\u306f|\u304a\u306f\u3088\u3046|\u3069\u3046\u3082|"
    r"\u3042\u308a\u304c\u3068(?:\u3046)?|\u3088\u308d\u3057\u304f|"
    r"\u304a\u3064\u304b\u308c|\u305f\u3060\u3044\u307e|"
    r"hello|hi|hey|thanks|thank you|ok|okay|yeah|hmm|wow|lol|lmao|gg|www+|nice"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)
SOURCE_REACTION_ONLY_RE = re.compile(
    r"^(?:"
    r"\u3084\u3070\u3044|\u307e\u3058|\u3048\u3050\u3044|\u3059\u3054\u3044|"
    r"\u3046\u308f|\u3048\u3063|\u3042\u3063|\u7b11+|w+|www+|"
    r"wow|omg|lol|gg|nice|hmm|uh|um"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)
SOURCE_CALL_ONLY_RE = re.compile(
    r"^(?:"
    r"\u307f\u3093\u306a|\u8ab0\u304b|\u3060\u308c\u304b|\u304a\u3044|"
    r"\u3061\u3087\u3063\u3068|\u805e\u3044\u3066|\u898b\u3066|\u6765\u3066|"
    r"chat|guys|everyone"
    r")(?:[\s\u3000,.\u3001\u3002!?\uff01\uff1f\u30fc\u301cw]*)$",
    re.IGNORECASE,
)
SOURCE_CONTENT_WORD_RE = re.compile(r"[A-Za-z]{3,}|[\u30a1-\u30ff]{3,}|[\u4e00-\u9fff]{2,}")
SOURCE_SUBJECT_HINT_RE = re.compile(r"(?:[\u4e00-\u9fff]{2,}|[\u30a1-\u30ff]{3,}|[A-Za-z][A-Za-z0-9]{2,})")
SOURCE_ACTION_HINT_RE = re.compile(
    r"(?:"
    r"\u4f7f(?:\u3063\u3066\u3082\u3089(?:\u3063\u305f|\u3048\u305f)|\u308f\u308c(?:\u305f|\u308b)|\u3063(?:\u305f|\u3066)|\u3046)|"
    r"\u6620(?:\u3063(?:\u305f|\u3066)|\u308b)|"
    r"\u7d39\u4ecb(?:\u3055\u308c(?:\u305f|\u308b)|\u3057(?:\u305f|\u3066)|\u3059\u308b)|"
    r"\u547c(?:\u3070\u308c(?:\u305f|\u308b)|\u3093(?:\u3060|\u3067)|\u3076)|"
    r"\u898b\u3064\u3051(?:\u305f|\u3066|\u308b)|"
    r"\u6c17\u3065(?:\u3044\u305f|\u3044\u3066|\u304f)|"
    r"\u843d\u3061(?:\u305f|\u3066|\u308b)|"
    r"\u58ca\u308c(?:\u305f|\u3066|\u308b)|"
    r"\u53d6\u308c(?:\u305f|\u3066|\u308b)|"
    r"\u51fa(?:\u305f|\u3066|\u308b)|"
    r"\u5f53\u305f(?:\u3063\u305f|\u3063\u3066|\u308b)|"
    r"\u6d88\u3048(?:\u305f|\u3066|\u308b)|"
    r"\u56de\u5fa9(?:\u3057(?:\u305f|\u3066|\u306a\u3044)|\u3059\u308b)|"
    r"\u3057\u305f|\u3057\u3066|\u3059\u308b|\u3055\u308c\u305f|\u306a\u308b|"
    r"\u306a\u3063\u305f|\u884c(?:\u3063\u305f|\u3063\u3066|\u304f)|\u6765(?:\u305f|\u3066|\u308b)|"
    r"\u5012\u3059|\u52dd(?:\u3063\u305f|\u3063\u3066|\u3064)|\u8ca0\u3051(?:\u305f|\u3066|\u308b)|"
    r"\u53d6\u308b|\u62fe\u3046|\u958b(?:\u304f|\u3044\u305f)|\u30df\u30b9\u3059\u308b|"
    r"clear|cleared|start|started|win|won|lose|lost|killed|drop|dropped"
    r")",
    re.IGNORECASE,
)
SOURCE_TOKEN_SPLIT_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9_+\-]{1,}|[0-9]{2,}|[\u4e00-\u9fff]{1,4}[\u3040-\u309f]{0,3}|[\u30a1-\u30ff]{2,}|[\u3040-\u309f]{2,}"
)
SOURCE_STOPWORD_TOKENS = {
    "\u306e",
    "\u306b",
    "\u306f",
    "\u3092",
    "\u304c",
    "\u3068",
    "\u3067",
    "\u3082",
    "\u3063\u3066",
    "\u305f",
    "\u3066",
    "\u3060",
    "\u306a",
    "\u3067\u3059",
    "\u307e\u3059",
    "\u3057\u305f",
    "\u3057\u3066",
    "\u3059\u308b",
    "\u306a\u308b",
    "\u3042\u308b",
    "\u3044\u308b",
    "\u3053\u3068",
    "\u305d\u308c",
    "\u3053\u308c",
    "\u3042\u308c",
    "\u3053\u306e",
    "\u305d\u306e",
    "\u3042\u306e",
    "\u306a\u3093\u304b",
    "\u3082\u3046",
    "\u3061\u3087\u3063\u3068",
    "\u305d\u308d\u305d\u308d",
    "\u3057\u3070\u3089\u304f",
    "\u5168\u7136",
    "\u3051\u3069",
    "\u3067\u3082",
    "\u304b\u3089",
    "\u306e\u3067",
}
EXACT_ALIAS_PARTICLE_SUFFIXES = {
    "\u306f",
    "\u304c",
    "\u3092",
    "\u306b",
    "\u3078",
    "\u3068",
    "\u3067",
    "\u3084",
    "\u3082",
    "\u304b",
    "\u306e",
    "\u306d",
    "\u3088",
    "\u306a",
    "\u308f",
    "\u304b\u3089",
    "\u307e\u3067",
    "\u3060\u3051",
    "\u3057\u304b",
    "\u3088\u308a",
    "\u306a\u3089",
    "\u3063\u3066",
    "\u3067\u306f",
    "\u306b\u306f",
    "\u3068\u306f",
    "\u3078\u306f",
    "\u3067\u3082",
    "\u3068\u3082",
    "\u3068\u304b",
}
TITLE_ENDING_FUNCTION_RE = re.compile(
    r"(?:\u3060|\u3067\u3059|\u3059\u308b|\u3057\u305f|\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068)$"
)
HEADLINE_CONVERSATIONAL_END_RE = re.compile(
    r"(?:\u3093\u3060\u3051\u3069|\u3051\u3069|\u3068\u601d\u3063\u3066\u305f\u3089|\u3063\u307d\u3044|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u305f\u3093\u3060\u306a)(?:[\s\u3001\u3002!\uff01?\uff1f\u2026\u301c\uff5e]*)$"
)
HEADLINE_CONVERSATIONAL_PHRASE_RE = re.compile(
    r"(?:\u3093\u3060\u3051\u3069|\u3051\u3069|\u3068\u601d\u3063\u3066\u305f\u3089|\u3063\u307d\u3044|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u305f\u3093\u3060\u306a)"
)
HEADLINE_CONVERSATIONAL_FRAGMENT_RE = re.compile(
    r"(?:^|[\s\u3001\u3002])(\u3068\u3044\u3046\u304b|\u306a\u3093\u304b)(?:[\s\u3001\u3002]|$)"
)
HEADLINE_IMPRESSION_FRAGMENT_RE = re.compile(
    r"(?:\u9762\u767d\u304b\u3063\u305f|\u308f\u304b\u3089\u306a\u3044|\u3069\u3046\u3068\u304b|\u306a\u3093\u3060\u308d\u3046)"
)
HEADLINE_FIRST_PERSON_PRONOUN_RE = re.compile(
    r"(?:^|[\s\u3001\u3002])(\u79c1|\u308f\u305f\u3057|\u4ffa|\u50d5|\u3046\u3061)(?:\u306f|\u304c|\u3082|\u3063\u3066)?"
)
HEADLINE_CHANGE_HINT_RE = re.compile(
    r"(?:\u5909\u308f(?:\u308b|\u3063\u305f)|\u5897\u3048(?:\u308b|\u305f)|\u6e1b(?:\u308b|\u3063\u305f)|\u58ca\u308c(?:\u308b|\u305f)|\u843d\u3061(?:\u308b|\u305f)|"
    r"\u4e0a\u304c(?:\u308b|\u3063\u305f)|\u4e0b\u304c(?:\u308b|\u3063\u305f)|\u5fa9\u6d3b|\u5fa9\u5e30|\u6d88\u3048(?:\u308b|\u305f)|\u51fa\u73fe|\u899a\u9192|\u9006\u8ee2|"
    r"\u9014\u5207\u308c(?:\u308b|\u305f)|\u518d\u958b(?:\u3059\u308b|\u3057\u305f)|\u623b(?:\u308b|\u3063\u305f)|\u6b62(?:\u307e\u308b|\u307e\u3063\u305f)|\u5d29\u308c(?:\u308b|\u305f))"
)
HEADLINE_EVENT_SUMMARY_RE = re.compile(
    r"(?:\u3092|\u304c|\u3067|\u306b).*(?:\u3057\u305f|\u3059\u308b|\u306a\u308b|\u306a\u3063\u305f|\u767a\u751f|\u5224\u660e|\u6210\u529f|\u5931\u6557|\u958b\u59cb|\u7d42\u4e86|\u5fa9\u6d3b|\u6483\u7834|\u7a81\u7834|\u5230\u9054)"
)
SOURCE_INCOMPLETE_END_RE = re.compile(
    r"(?:\u3051\u3069|\u3051\u3069\u3082|\u3051\u308c\u3069|\u3051\u308c\u3069\u3082|"
    r"\u3068\u304b|\u3063\u3066|\u3066|\u3067|\u3057|\u304b\u3089|\u306e\u3067|\u306a|"
    r"but|so|and|because)$",
    re.IGNORECASE,
)
SOURCE_NOISE_EDGE_RE = re.compile(
    r"^(?:\u3048[\u30fc\u301c]*|\u3042\u306e[\u30fc\u301c]*|\u305d\u306e[\u30fc\u301c]*|"
    r"\u306a\u3093\u304b|\u307e\u3042|\u3046\u30fc\u3093|\u3048\u3063\u3068|"
    r"\u3066\u3044\u3046\u304b|uh+|um+|hmm+|like|you know|well)"
    r"(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]+|$)",
    re.IGNORECASE,
)
SOURCE_REPEAT_WORD_RE = re.compile(
    r"\b(?P<w>[A-Za-z0-9]{2,}|[\u3040-\u30ff\u4e00-\u9fff]{1,6})(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]*\1){2,}",
    re.IGNORECASE,
)
SOURCE_INTERJECTION_INLINE_RE = re.compile(
    r"(?:\b(?:uh+|um+|hmm+|like|you know|well|yeah|ok|wow)\b|"
    r"(?:\u3048[\u30fc\u301c]*|\u3042\u306e[\u30fc\u301c]*|\u305d\u306e[\u30fc\u301c]*|"
    r"\u306a\u3093\u304b|\u307e\u3042|\u3046\u30fc\u3093|\u3048\u3063\u3068))"
    r"(?:[\s\u3000,\u3001\u3002.!?\uff01\uff1f\u30fc\u301c]*)",
    re.IGNORECASE,
)
SOURCE_SENTENCE_END_RE = re.compile(r"[\u3002.!?\uff01\uff1f]")
def _iter_source_tokens(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    if not normalized:
        return []
    tokenizer = hlv.resolve_tokenizer()
    raw_tokens = hlv.tokenize_text(normalized, tokenizer=tokenizer)
    tokens: list[str] = []
    for raw in raw_tokens:
        cleaned = sanitize_headline(raw)
        if not cleaned:
            continue
        if tokenizer.is_fallback:
            subtokens = SOURCE_TOKEN_SPLIT_RE.findall(cleaned)
            if subtokens:
                tokens.extend(subtokens)
                continue
        tokens.append(cleaned)
    if not tokens:
        tokens = SOURCE_TOKEN_SPLIT_RE.findall(normalized)
    return [sanitize_headline(token) for token in tokens if sanitize_headline(token)]


def _is_content_token(token: str) -> bool:
    value = sanitize_headline(token)
    if not value:
        return False
    lowered = value.lower()
    if lowered in SOURCE_STOPWORD_TOKENS:
        return False
    if HEADLINE_META_RE.search(value) or HEADLINE_SENSITIVE_RE.search(value):
        return False
    if SOURCE_CONTENT_WORD_RE.search(value):
        return True
    return len(value) >= 2 and bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9]", value))


def _count_subject_hints(text: str) -> int:
    return sum(1 for token in _iter_source_tokens(text) if _is_content_token(token) and SOURCE_SUBJECT_HINT_RE.search(token))


def _count_action_hints(text: str) -> int:
    tokens = _iter_source_tokens(text)
    if not tokens:
        return 0
    count = sum(1 for token in tokens if SOURCE_ACTION_HINT_RE.search(token))
    if count > 0:
        return count
    return len(SOURCE_ACTION_HINT_RE.findall(normalize_source_text(text)))


SOURCE_DEFAULT_CONFIG: dict[str, Any] = {
    "max_source_sentences": 2,
    "max_sentence_chars": max(20, HEADLINE_MAX_CHARS + 20),
    "max_source_chars": max(40, HEADLINE_MAX_CHARS * 3),
    "min_content_words": 2,
    "max_unknown_ratio": 0.55,
}

SOURCE_SELECTION_CHATTER_RE = re.compile(
    r"(?:\u30b3\u30e1\u30f3\u30c8|\u8996\u8074\u8005|\u914d\u4fe1|\u96d1\u8ac7|\u98ef|\u7720\u3044|\u4ed5\u4e8b|\u5b66\u6821|LINE|Twitter|X)",
    re.IGNORECASE,
)
SOURCE_SELECTION_COLLOQUIAL_TAIL_RE = re.compile(
    r"(?:\u3051\u3069|\u3051\u308c\u3069|\u304b\u306a|\u304b\u3082|\u3068\u3044\u3046\u304b|\u306a\u3093\u304b|\u3060\u3063\u3051|\u3060\u3088\u306d|\u307f\u305f\u3044\u306a)$",
    re.IGNORECASE,
)
SOURCE_SELECTION_SUSPICIOUS_RE = re.compile(
    r"(?:[A-Za-z]{1,2}\d{2,}|[\-~_=]{3,}|[\u3041-\u3093\u30a1-\u30ff\u4e00-\u9fff]{1,2}(?:\s+[\u3041-\u3093\u30a1-\u30ff\u4e00-\u9fff]{1,2}){3,})"
)



@dataclass
class SegmentTarget:
    video: dict[str, Any]
    item: dict[str, Any]
    start_sec: int
    end_sec: int
    needs_transcript: bool
    needs_headline: bool


def make_source_selection_context(
    target: SegmentTarget,
    *,
    options: RunOptions,
    transcript_pass: str,
    print_details: bool,
) -> SourceSelectionContext:
    activity_map = target.video.get("activity_map")
    return SourceSelectionContext(
        item_id=str(target.item.get("id") or "").strip(),
        transcript_pass=str(transcript_pass or "unknown").strip() or "unknown",
        scene_start_sec=_to_int(target.item.get("start_sec")),
        scene_end_sec=_to_int(target.item.get("end_sec")),
        transcript_window_start_sec=int(target.start_sec),
        transcript_window_end_sec=int(target.end_sec),
        activity_map=activity_map if isinstance(activity_map, dict) else None,
        sentence_limit=max(1, min(2, int(options.source_sentence_limit))),
        use_game_term_dictionary=bool(options.use_game_term_dictionary),
        print_details=bool(print_details),
    )


@dataclass
class TranscriptResult:
    text: str
    language: str
    language_probability: float | None
    segments: list[dict[str, Any]] | None = None
    source_text: str | None = None
    normalized_text: str | None = None


@dataclass(frozen=True)
class TranscribePassConfig:
    model: str
    preprocess_profile: str
    vad_filter: bool
    word_timestamps: bool
    condition_on_previous_text: bool = False
    beam_size: int = 1
    vad_parameters: dict[str, Any] | None = None
    extra_padding_sec: int = 0


@dataclass(frozen=True)
class RetranscribeConfig:
    enabled: bool
    selection_mode: str
    top_n: int
    low_info_token_threshold: int
    suspicious_ratio_threshold: float


@dataclass
class RunSummary:
    transcript_success: int = 0
    transcript_skipped: int = 0
    headline_success: int = 0
    headline_skipped: int = 0


@dataclass
class HeadlineResult:
    text: str
    model: str
    source: str
    generation_mode: str = "llm_ranked"
    confidence: str = "medium"
    notes: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceValidationResult:
    accepted: bool
    reasons: list[str]
    content_word_count: int
    subject_hint_count: int
    action_hint_count: int
    unknown_ratio: float


@dataclass(frozen=True)
class SourceSentenceCandidate:
    index: int
    text: str
    normalized: str
    start_sec: float | None
    end_sec: float | None
    has_word_timestamps: bool
    game_term_hits: tuple[str, ...]
    score: float
    breakdown: dict[str, float]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SourceSelectionContext:
    item_id: str
    transcript_pass: str
    scene_start_sec: int | None
    scene_end_sec: int | None
    transcript_window_start_sec: int | None
    transcript_window_end_sec: int | None
    activity_map: dict[str, Any] | None
    sentence_limit: int
    use_game_term_dictionary: bool
    print_details: bool


@dataclass(frozen=True)
class SourceSelectionResult:
    candidates: tuple[SourceSentenceCandidate, ...]
    selected: tuple[SourceSentenceCandidate, ...]


@dataclass(frozen=True)
class HeadlineCandidate:
    headline: str
    used_terms: list[str]
    confidence: float
    reason: str
    can_publish: bool = True
    generation_mode: str = ""
    notes: str = ""


@dataclass(frozen=True)
class HeadlineScore:
    total: float
    breakdown: dict[str, float]
    reasons: list[str]


class WhisperTranscriber:
    def __init__(self) -> None:
        self._model_cache = tx_whisper.FasterWhisperModelCache(
            device=TRANSCRIPT_DEVICE,
            compute_type=TRANSCRIPT_COMPUTE_TYPE,
        )

    def transcribe(
        self,
        media_path: Path,
        *,
        model_name: str | None = None,
        vad_filter: bool = True,
        word_timestamps: bool = False,
        condition_on_previous_text: bool = False,
        beam_size: int = 1,
        vad_parameters: dict[str, Any] | None = None,
    ) -> TranscriptResult:
        return tx_whisper.transcribe_media(
            media_path,
            model_cache=self._model_cache,
            model_name=(model_name or TRANSCRIPT_MODEL).strip() or TRANSCRIPT_MODEL,
            result_factory=TranscriptResult,
            optional_float=_to_optional_float,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            condition_on_previous_text=condition_on_previous_text,
            beam_size=beam_size,
            vad_parameters=vad_parameters,
        )




def main(argv: list[str] | None = None) -> None:
    options, headline_source_config = _setup_execution(argv)
    collected = _collect_targets_and_check_preconditions(options=options)
    if collected is None:
        return
    videos, headline_generator, targets = collected

    _print_run_options(options)
    if _print_dry_run_targets(targets, options=options):
        return

    (
        transcriber,
        transcript_prereq_error,
        first_pass_config,
        second_pass_config,
        retranscribe_config,
    ) = _setup_transcription_components(targets, options=options)
    summary = RunSummary()

    first_pass_results = _run_first_pass_transcription_loop(
        targets,
        transcriber=transcriber,
        transcript_prereq_error=transcript_prereq_error,
        first_pass_config=first_pass_config,
        headline_source_config=headline_source_config,
        options=options,
        summary=summary,
    )
    first_pass_results = _run_second_pass_retranscription_loop(
        targets,
        first_pass_results=first_pass_results,
        transcriber=transcriber,
        second_pass_config=second_pass_config,
        retranscribe_config=retranscribe_config,
        headline_source_config=headline_source_config,
        options=options,
    )
    _run_headline_generation_loop(
        targets,
        first_pass_results=first_pass_results,
        headline_generator=headline_generator,
        headline_source_config=headline_source_config,
        options=options,
        summary=summary,
    )
    _finalize_and_save_outputs(videos, targets)
    _print_summary(summary)


def _setup_execution(argv: list[str] | None = None) -> tuple[RunOptions, dict[str, Any]]:
    load_local_env(ENV_PATH)
    settings = PipelineSettings.from_env(os.environ)
    apply_pipeline_settings(settings)
    refresh_runtime_configuration()
    options = build_run_options(parse_cli_args(argv), settings)
    set_active_term_dictionary(options.use_game_term_dictionary)
    headline_source_config = build_headline_source_config(
        source_sentence_limit=options.source_sentence_limit,
        print_source_selection=options.print_source_selection,
        use_game_term_dictionary=options.use_game_term_dictionary,
    )
    return options, headline_source_config


def _collect_targets_and_check_preconditions(
    *,
    options: RunOptions,
) -> tuple[list[dict[str, Any]], hlg.ResilientHeadlineGenerator | None, list[SegmentTarget]] | None:
    if not CACHE_PATH.exists():
        print(f"warn: no processed cache found at {CACHE_PATH}")
        return None

    videos = load_processed_videos()
    headline_generator = build_headline_generator()
    target_vod_ids = resolve_target_vod_ids(videos, options=options)
    if options.only_vod_id:
        print(f"info: transcript target vod scope=explicit vod_id={options.only_vod_id}")
    elif target_vod_ids is None:
        print("info: transcript target vod scope=all")
    else:
        joined_vod_ids = ",".join(target_vod_ids) if target_vod_ids else "none"
        print(f"info: transcript target vod scope=recent_public vod_ids={joined_vod_ids}")
    targets = collect_targets(
        videos,
        headline_enabled=headline_generator is not None,
        options=options,
        target_vod_ids=target_vod_ids,
    )
    if not targets:
        print("No transcript/headline work items found.")
        return None
    return videos, headline_generator, targets


def _print_run_options(options: RunOptions) -> None:
    print(
        "info: run options "
        f"headline_only={options.headline_only} force_transcript_refresh={options.force_transcript_refresh} "
        f"force_headline_refresh={options.force_headline_refresh} max_segments={options.max_segments} "
        f"item_id={options.only_item_id or 'all'} vod_id={options.only_vod_id or 'all'} "
        f"print_headline_results={options.print_headline_results} print_source_selection={options.print_source_selection} "
        f"source_sentence_limit={options.source_sentence_limit} use_game_term_dictionary={options.use_game_term_dictionary} "
        f"second_pass_selection_mode={options.second_pass_selection_mode} second_pass_top_n={options.second_pass_top_n} "
        f"second_pass_extra_padding_sec={options.second_pass_extra_padding_sec} second_pass_word_timestamps={options.second_pass_word_timestamps} "
        f"second_pass_preprocess_profile={options.second_pass_preprocess_profile} "
        f"target_scope={TRANSCRIPT_TARGET_SCOPE} recent_analyzed_window_hours={TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS}"
    )


def _print_dry_run_targets(targets: list[SegmentTarget], *, options: RunOptions) -> bool:
    if not options.dry_run:
        return False
    print(f"dry-run: {len(targets)} segments would be processed")
    for target in targets:
        print(
            "dry-run target "
            f"{target.video.get('vod_id', 'unknown')}:{target.item.get('id', 'segment')} "
            f"transcript={target.needs_transcript} headline={target.needs_headline}"
        )
    return True


def _setup_transcription_components(
    targets: list[SegmentTarget],
    *,
    options: RunOptions,
) -> tuple[
    WhisperTranscriber | None,
    str | None,
    TranscribePassConfig,
    TranscribePassConfig,
    RetranscribeConfig,
]:
    transcriber: WhisperTranscriber | None = None
    transcript_prereq_error = detect_transcription_prerequisite_error(targets)
    if transcript_prereq_error:
        print(f"warn: {transcript_prereq_error}")
    elif any(target.needs_transcript for target in targets):
        transcriber = WhisperTranscriber()

    return (
        transcriber,
        transcript_prereq_error,
        build_first_pass_config(),
        build_second_pass_config(options=options),
        build_retranscribe_config(options=options),
    )


def _run_first_pass_transcription_loop(
    targets: list[SegmentTarget],
    *,
    transcriber: WhisperTranscriber | None,
    transcript_prereq_error: str | None,
    first_pass_config: TranscribePassConfig,
    headline_source_config: dict[str, Any],
    options: RunOptions,
    summary: RunSummary,
) -> dict[str, TranscriptResult]:
    first_pass_results: dict[str, TranscriptResult] = {}

    for index, target in enumerate(targets, start=1):
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        if not target.needs_transcript:
            continue
        print(f"transcribe-pass1 {index}/{len(targets)} {label}")
        log_item_snapshot("before_transcript", label, target.item)
        if transcript_prereq_error or transcriber is None:
            reason = transcript_prereq_error or "transcriber is not available"
            has_existing_transcript = bool(str(target.item.get("transcript") or "").strip())
            has_existing_segments = bool(target.item.get("transcript_segments"))
            if has_existing_transcript or has_existing_segments:
                print(
                    f"warn: transcript failed for {label} ({reason}); "
                    "preserving existing transcript/transcript_segments"
                )
                summary.transcript_skipped += 1
                log_item_snapshot("after_transcript_error", label, target.item)
                continue
            clear_transcript_artifacts(target.item)
            cleared_headline = clear_headline_artifacts(target.item)
            target.item["transcript_status"] = "error"
            target.item["transcript_error"] = reason[:300]
            target.item["transcript_generated_at"] = now_iso()
            summary.transcript_skipped += 1
            print(f"warn: transcript failed for {label} ({reason})")
            if cleared_headline:
                print(f"info: cleared stale headline fields label={label} fields={cleared_headline}")
            log_item_snapshot("after_transcript_error", label, target.item)
            continue
        try:
            result = transcribe_target(target, transcriber, config=first_pass_config)
        except Exception as exc:
            has_existing_transcript = bool(str(target.item.get("transcript") or "").strip())
            has_existing_segments = bool(target.item.get("transcript_segments"))
            if has_existing_transcript or has_existing_segments:
                print(
                    f"warn: transcript failed for {label} ({exc}); "
                    "preserving existing transcript/transcript_segments"
                )
                summary.transcript_skipped += 1
                log_item_snapshot("after_transcript_error", label, target.item)
                continue
            clear_transcript_artifacts(target.item)
            cleared_headline = clear_headline_artifacts(target.item)
            target.item["transcript_status"] = "error"
            target.item["transcript_error"] = str(exc)[:300]
            target.item["transcript_generated_at"] = now_iso()
            summary.transcript_skipped += 1
            print(f"warn: transcript failed for {label} ({exc})")
            if cleared_headline:
                print(f"info: cleared stale headline fields label={label} fields={cleared_headline}")
            log_item_snapshot("after_transcript_error", label, target.item)
            continue

        if TERM_NORMALIZATION_ENABLED:
            normalized = normalize_transcript_terms(result.text, ACTIVE_TERM_DICTIONARY, TERM_NORMALIZATION_CONFIG)
            result.normalized_text = normalized.text
            if normalized.replacements:
                for row in normalized.replacements[:20]:
                    print(
                        "debug: term normalization "
                        f"item={target.item.get('id')} category={row.category} "
                        f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                    )
            result.text = normalized.text

        item_id = str(target.item.get("id") or "")
        first_pass_results[item_id] = result
        target.item["_active_transcript_model"] = first_pass_config.model
        apply_transcript_result(target.item, target, result)
        target.item["transcript_pass"] = "first"
        if target.item.get("transcript_status") == "ok":
            first_pass_context = make_source_selection_context(
                target,
                options=options,
                transcript_pass="first",
                print_details=False,
            )
            target.item["transcript_source_text"] = build_headline_source_text(
                result,
                headline_source_config,
                selection_context=first_pass_context,
            )
        else:
            target.item.pop("transcript_source_text", None)
        if result.text:
            summary.transcript_success += 1
        else:
            summary.transcript_skipped += 1
        log_item_snapshot("after_transcript", label, target.item)

    return first_pass_results


def _run_second_pass_retranscription_loop(
    targets: list[SegmentTarget],
    *,
    first_pass_results: dict[str, TranscriptResult],
    transcriber: WhisperTranscriber | None,
    second_pass_config: TranscribePassConfig,
    retranscribe_config: RetranscribeConfig,
    headline_source_config: dict[str, Any],
    options: RunOptions,
) -> dict[str, TranscriptResult]:
    if transcriber is None:
        return first_pass_results

    first_pass_results = maybe_retranscribe_top_candidates(
        targets,
        first_pass_results,
        transcriber,
        retranscribe_config,
        options=options,
    )
    for target in targets:
        item_id = str(target.item.get("id") or "")
        result = first_pass_results.get(item_id)
        if not result or not target.needs_transcript:
            continue
        if target.item.get("_second_pass_applied"):
            target.item["_active_transcript_model"] = second_pass_config.model
            target.item["transcript_pass"] = "second"
        apply_transcript_result(target.item, target, result)
        if target.item.get("transcript_status") == "ok":
            transcript_pass = str(target.item.get("transcript_pass") or "second")
            second_pass_context = make_source_selection_context(
                target,
                options=options,
                transcript_pass=transcript_pass,
                print_details=False,
            )
            target.item["transcript_source_text"] = build_headline_source_text(
                result,
                headline_source_config,
                selection_context=second_pass_context,
            )
        else:
            target.item.pop("transcript_source_text", None)

    return first_pass_results


@dataclass(frozen=True)
class HeadlineLoopInputs:
    transcript_status: str
    transcript_text_raw: str


@dataclass(frozen=True)
class HeadlinePreparedInputs:
    transcript_text: str
    prepared_source_text: str
    source_selection_debug: dict[str, Any]


@dataclass(frozen=True)
class HeadlineSourceStrategy:
    source_validation: SourceValidationResult
    initial_mode: str
    default_confidence: str
    quality_penalty: float


@dataclass(frozen=True)
class HeadlineGenerationOutcome:
    headline: HeadlineResult
    generation_reason: str


def _collect_headline_loop_inputs(target: SegmentTarget, *, label: str) -> HeadlineLoopInputs:
    transcript_status = str(target.item.get("transcript_status") or "").strip().lower()
    transcript_text_raw = str(target.item.get("transcript") or "").strip()
    print(
        "debug: headline gate check "
        f"label={label} needs_headline={target.needs_headline} transcript_status={transcript_status or 'none'} "
        f"has_transcript={bool(transcript_text_raw)}"
    )
    return HeadlineLoopInputs(
        transcript_status=transcript_status,
        transcript_text_raw=transcript_text_raw,
    )


def _is_headline_generation_ready(target: SegmentTarget, inputs: HeadlineLoopInputs) -> bool:
    return bool(target.needs_headline and inputs.transcript_status == "ok" and inputs.transcript_text_raw)


def _normalize_transcript_for_headline_generation(
    target: SegmentTarget,
    *,
    transcript_text_raw: str,
) -> str:
    transcript_text = transcript_text_raw
    if TERM_NORMALIZATION_ENABLED:
        normalized_cached = normalize_transcript_terms(
            transcript_text,
            ACTIVE_TERM_DICTIONARY,
            TERM_NORMALIZATION_CONFIG,
        )
        if normalized_cached.replacements:
            for row in normalized_cached.replacements[:20]:
                print(
                    "debug: term normalization (headline-only cached) "
                    f"item={target.item.get('id')} category={row.category} "
                    f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                )
        transcript_text = normalized_cached.text
    return transcript_text


def _build_headline_source_text_inputs(
    target: SegmentTarget,
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_source_config: dict[str, Any],
    options: RunOptions,
    transcript_text: str,
) -> tuple[str, dict[str, Any]]:
    source_result = TranscriptResult(
        text=transcript_text,
        language=str(target.item.get("transcript_language") or ""),
        language_probability=_to_optional_float(target.item.get("transcript_language_probability")),
        segments=(first_pass_results.get(str(target.item.get("id") or "")) or TranscriptResult("", "", None)).segments,
    )
    source_result.normalized_text = transcript_text
    source_selection_context = make_source_selection_context(
        target,
        options=options,
        transcript_pass=str(target.item.get("transcript_pass") or "cached"),
        print_details=bool(options.print_headline_results or options.print_source_selection),
    )
    source_selection_debug: dict[str, Any] = {}
    prepared_source_text = build_headline_source_text(
        source_result,
        headline_source_config,
        selection_context=source_selection_context,
        selection_result_out=source_selection_debug,
    )
    target.item["headline_source_text"] = prepared_source_text
    return prepared_source_text, source_selection_debug


def _prepare_headline_generation_inputs(
    target: SegmentTarget,
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_source_config: dict[str, Any],
    options: RunOptions,
    transcript_text_raw: str,
) -> HeadlinePreparedInputs:
    transcript_text = _normalize_transcript_for_headline_generation(
        target,
        transcript_text_raw=transcript_text_raw,
    )
    prepared_source_text, source_selection_debug = _build_headline_source_text_inputs(
        target,
        first_pass_results=first_pass_results,
        headline_source_config=headline_source_config,
        options=options,
        transcript_text=transcript_text,
    )
    return HeadlinePreparedInputs(
        transcript_text=transcript_text,
        prepared_source_text=prepared_source_text,
        source_selection_debug=source_selection_debug,
    )


def _validate_headline_source_and_decide_mode(
    item: dict[str, Any],
    *,
    prepared_source_text: str,
    headline_source_config: dict[str, Any],
) -> HeadlineSourceStrategy:
    source_validation = is_valid_headline_source_text(prepared_source_text, headline_source_config)
    initial_mode, default_confidence, quality_penalty = decide_headline_generation_strategy(source_validation)
    item["headline_source_validation"] = {
        "accepted": source_validation.accepted,
        "reasons": source_validation.reasons,
        "content_word_count": source_validation.content_word_count,
        "subject_hint_count": source_validation.subject_hint_count,
        "action_hint_count": source_validation.action_hint_count,
        "unknown_ratio": round(source_validation.unknown_ratio, 3),
        "headline_quality_penalty": round(quality_penalty, 3),
        "recommended_mode": initial_mode,
    }
    item["headline_quality_penalty"] = round(quality_penalty, 3)
    return HeadlineSourceStrategy(
        source_validation=source_validation,
        initial_mode=initial_mode,
        default_confidence=default_confidence,
        quality_penalty=quality_penalty,
    )


def _execute_headline_generator(
    target: SegmentTarget,
    *,
    label: str,
    headline_generator: hlg.ResilientHeadlineGenerator | None,
    headline_source_config: dict[str, Any],
    transcript_text: str,
    prepared_source_text: str,
    source_validation: SourceValidationResult,
    initial_mode: str,
) -> HeadlineGenerationOutcome:
    video_title = str(target.video.get("title") or "").strip()
    if initial_mode == "fallback_extractive":
        headline = build_fallback_extractive_result(
            prepared_source_text=prepared_source_text,
            transcript=transcript_text,
            video_title=video_title,
            reason="source_too_weak_for_llm",
            source_config=headline_source_config,
        )
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_by_source_strategy",
        )

    try:
        headline = headline_generator.generate(
            video_title=video_title,
            start_time=str(target.item.get("start_time") or format_section_time(target.start_sec)).strip(),
            end_time=str(target.item.get("end_time") or format_section_time(target.end_sec)).strip(),
            transcript=transcript_text,
            prepared_transcript=prepared_source_text,
            source_validation=source_validation,
        )
    except Exception as exc:
        print(f"warn: headline generation failed; using fallback label={label} reason={exc}")
        headline = build_fallback_extractive_result(
            prepared_source_text=prepared_source_text,
            transcript=transcript_text,
            video_title=video_title,
            reason=f"llm_error:{exc}",
            source_config=headline_source_config,
        )
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_after_llm_error",
        )

    if initial_mode == "weak_llm" and headline.generation_mode == "llm_ranked":
        headline.generation_mode = "weak_llm"
        if headline.confidence == "high":
            headline.confidence = "medium"
    return HeadlineGenerationOutcome(
        headline=headline,
        generation_reason=f"llm_mode={headline.generation_mode}",
    )


def _apply_headline_post_filter_fallback(
    target: SegmentTarget,
    *,
    label: str,
    outcome: HeadlineGenerationOutcome,
    headline_source_config: dict[str, Any],
    transcript_text: str,
    prepared_source_text: str,
) -> HeadlineGenerationOutcome:
    final_validation = validate_final_headline_japanese(
        outcome.headline.text,
        source_text=prepared_source_text or transcript_text,
    )
    if is_publishable_headline(outcome.headline.text, source_text=prepared_source_text or transcript_text):
        return outcome

    print(
        "info: post-filter rejected headline; using fallback extractive "
        f"label={label} reasons={final_validation.reasons} headline={outcome.headline.text}"
    )
    headline = build_fallback_extractive_result(
        prepared_source_text=prepared_source_text,
        transcript=transcript_text,
        video_title=str(target.video.get("title") or "").strip(),
        reason=f"post_filter:{','.join(final_validation.reasons)}",
        source_config=headline_source_config,
    )
    fallback_validation = validate_final_headline_japanese(
        headline.text,
        source_text=prepared_source_text or transcript_text,
    )
    if is_publishable_headline(headline.text, source_text=prepared_source_text or transcript_text) and headline.text != DEFAULT_HEADLINE_TEXT:
        return HeadlineGenerationOutcome(
            headline=headline,
            generation_reason="fallback_after_post_filter",
        )

    safe_headline = build_tag_based_fallback_headline(target.item.get("tags"))
    print(
        "info: extractive fallback rejected; using tag fallback "
        f"label={label} reasons={fallback_validation.reasons} headline={headline.text} "
        f"fallback={safe_headline}"
    )
    return HeadlineGenerationOutcome(
        headline=HeadlineResult(
            text=safe_headline,
            model=LOCAL_HEADLINE_MODEL,
            source="tags",
            generation_mode="fallback_tag",
            confidence="low",
            notes=f"extractive_post_filter:{','.join(fallback_validation.reasons)}",
        ),
        generation_reason="fallback_tag_after_post_filter",
    )


def _resolve_headline_status(headline: HeadlineResult, source_validation: SourceValidationResult) -> str:
    if headline.generation_mode in {"fallback_extractive", "fallback_tag"}:
        return headline.generation_mode
    if not source_validation.accepted or headline.generation_mode in {"weak_llm", "weak_generated"}:
        return "weak_generated"
    return "ok"


def _apply_generated_headline_to_item(
    item: dict[str, Any],
    *,
    headline: HeadlineResult,
    status: str,
    default_confidence: str,
) -> str:
    item["headline"] = headline.text
    item["headline_source"] = headline.source
    item["headline_model"] = headline.model
    item["headline_status"] = status
    item["headline_generation_mode"] = headline.generation_mode
    item["headline_confidence"] = headline.confidence or default_confidence
    item["headline_generated_at"] = now_iso()
    item.pop("headline_error", None)
    item.pop("headline_skip_reason", None)
    return str(item.get("headline_confidence") or default_confidence)


def _apply_skipped_headline_to_item(
    target: SegmentTarget,
    *,
    label: str,
    transcript_status: str,
    options: RunOptions,
) -> None:
    if not target.needs_headline:
        return

    cleared = clear_headline_artifacts(target.item)
    if cleared:
        print(f"info: cleared stale headline fields label={label} fields={cleared}")
    if transcript_status == "error":
        reason = str(target.item.get("transcript_error") or "transcript_status_error").strip() or "transcript_status_error"
        target.item["headline_status"] = "skipped_transcript_error"
        target.item["headline_skip_reason"] = reason[:300]
        print(f"info: skipped headline due to transcript error label={label} reason={reason}")
    else:
        target.item["headline_status"] = "skipped_no_transcript"
        if transcript_status:
            target.item["headline_skip_reason"] = f"transcript_status={transcript_status}"[:300]
        else:
            target.item["headline_skip_reason"] = "missing_transcript"
        print(
            "info: skipped headline due to missing transcript "
            f"label={label} transcript_status={transcript_status or 'none'}"
        )
    target.item["headline_generated_at"] = now_iso()
    if options.print_headline_results:
        print_headline_result(
            label=label,
            item=target.item,
            source_text=str(target.item.get("headline_source_text") or "").strip(),
            source_validation=None,
            headline_result=None,
            generation_reason=str(target.item.get("headline_skip_reason") or "skipped").strip() or "skipped",
        )


def _log_headline_success_and_update_summary(
    target: SegmentTarget,
    *,
    label: str,
    status: str,
    final_confidence: str,
    strategy: HeadlineSourceStrategy,
    outcome: HeadlineGenerationOutcome,
    prepared_inputs: HeadlinePreparedInputs,
    options: RunOptions,
    summary: RunSummary,
) -> None:
    print(
        "info: headline finalized "
        f"label={label} status={status} mode={outcome.headline.generation_mode} confidence={final_confidence} "
        f"reason={outcome.generation_reason} source_validation_reasons={strategy.source_validation.reasons or 'none'}"
    )
    if options.print_headline_results:
        print_headline_result(
            label=label,
            item=target.item,
            source_text=prepared_inputs.prepared_source_text,
            source_validation=strategy.source_validation,
            headline_result=outcome.headline,
            generation_reason=outcome.generation_reason,
            source_selection=prepared_inputs.source_selection_debug.get("selection")
            if prepared_inputs.source_selection_debug
            else None,
        )
    summary.headline_success += 1


def _update_headline_skip_summary(target: SegmentTarget, summary: RunSummary) -> None:
    summary.headline_skipped += 1 if target.needs_headline else 0


def _run_headline_generation_loop(
    targets: list[SegmentTarget],
    *,
    first_pass_results: dict[str, TranscriptResult],
    headline_generator: hlg.ResilientHeadlineGenerator | None,
    headline_source_config: dict[str, Any],
    options: RunOptions,
    summary: RunSummary,
) -> None:
    for index, target in enumerate(targets, start=1):
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        started = time.perf_counter()
        inputs = _collect_headline_loop_inputs(target, label=label)

        if not target.needs_transcript:
            summary.transcript_skipped += 1

        if _is_headline_generation_ready(target, inputs):
            prepared_inputs = _prepare_headline_generation_inputs(
                target,
                first_pass_results=first_pass_results,
                headline_source_config=headline_source_config,
                options=options,
                transcript_text_raw=inputs.transcript_text_raw,
            )
            strategy = _validate_headline_source_and_decide_mode(
                target.item,
                prepared_source_text=prepared_inputs.prepared_source_text,
                headline_source_config=headline_source_config,
            )
            print(f"headline {index}/{len(targets)} {label}")
            if not strategy.source_validation.accepted:
                print(
                    "info: source validation accepted=false but continue headline generation "
                    f"label={label} reasons={strategy.source_validation.reasons} mode={strategy.initial_mode} "
                    f"penalty={strategy.quality_penalty:.2f}"
                )

            outcome = _execute_headline_generator(
                target,
                label=label,
                headline_generator=headline_generator,
                headline_source_config=headline_source_config,
                transcript_text=prepared_inputs.transcript_text,
                prepared_source_text=prepared_inputs.prepared_source_text,
                source_validation=strategy.source_validation,
                initial_mode=strategy.initial_mode,
            )
            outcome = _apply_headline_post_filter_fallback(
                target,
                label=label,
                outcome=outcome,
                headline_source_config=headline_source_config,
                transcript_text=prepared_inputs.transcript_text,
                prepared_source_text=prepared_inputs.prepared_source_text,
            )
            status = _resolve_headline_status(outcome.headline, strategy.source_validation)
            final_confidence = _apply_generated_headline_to_item(
                target.item,
                headline=outcome.headline,
                status=status,
                default_confidence=strategy.default_confidence,
            )
            _log_headline_success_and_update_summary(
                target,
                label=label,
                status=status,
                final_confidence=final_confidence,
                strategy=strategy,
                outcome=outcome,
                prepared_inputs=prepared_inputs,
                options=options,
                summary=summary,
            )
        else:
            _apply_skipped_headline_to_item(
                target,
                label=label,
                transcript_status=inputs.transcript_status,
                options=options,
            )
            _update_headline_skip_summary(target, summary)

        elapsed = time.perf_counter() - started
        print(f"done {label} ({elapsed:.1f}s)")


def _finalize_and_save_outputs(videos: list[dict[str, Any]], targets: list[SegmentTarget]) -> None:
    for target in targets:
        target.item.pop("_second_pass_zscore_rank", None)
        target.item.pop("_second_pass_applied", None)
        target.item.pop("_active_transcript_model", None)
    now = datetime.now().astimezone()
    write_processed_cache(videos, now)
    write_public_data(videos, now)


def _print_summary(summary: RunSummary) -> None:
    print(
        "summary: "
        f"transcript_success={summary.transcript_success} transcript_skipped={summary.transcript_skipped} "
        f"headline_success={summary.headline_success} headline_skipped={summary.headline_skipped}"
    )


def build_headline_generator() -> hlg.ResilientHeadlineGenerator:
    settings = hlg.HeadlineGenerationSettings(
        headline_source_config=HEADLINE_SOURCE_CONFIG,
        headline_max_attempts=HEADLINE_MAX_ATTEMPTS,
        gemini_timeout_sec=GEMINI_TIMEOUT_SEC,
        groq_timeout_sec=GROQ_TIMEOUT_SEC,
        groq_responses_url=GROQ_RESPONSES_URL,
        nvidia_timeout_sec=NVIDIA_TIMEOUT_SEC,
        nvidia_api_url=NVIDIA_API_URL,
        local_headline_model=LOCAL_HEADLINE_MODEL,
    )
    callbacks = hlg.HeadlineGenerationCallbacks(
        build_headline_source_text=build_headline_source_text,
        build_remote_headline_prompt=build_remote_headline_prompt,
        parse_headline_candidates_output=parse_headline_candidates_output,
        choose_best_headline=choose_best_headline,
        ensure_usable_remote_headline=ensure_usable_remote_headline,
        score_headline_candidate_with_source=score_headline_candidate_with_source,
        headline_confidence_label=headline_confidence_label,
        compute_source_quality_penalty=compute_source_quality_penalty,
        build_headline_response_schema=build_headline_response_schema,
        extract_gemini_output_text=extract_gemini_output_text,
        extract_response_output_text=extract_response_output_text,
        read_http_error_detail=read_http_error_detail,
        classify_gemini_http_error=classify_gemini_http_error,
        is_temporary_transport_error=is_temporary_transport_error,
        build_extractive_headline=build_extractive_headline,
        validate_headline_result=validate_headline_result,
        choose_best_remote_headline=choose_best_remote_headline,
        make_headline_result=HeadlineResult,
    )
    return hlg.build_headline_generator(
        gemini_api_key=GEMINI_API_KEY,
        gemini_model=GEMINI_MODEL,
        gemini_api_url=GEMINI_API_URL,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        nvidia_api_key=NVIDIA_API_KEY,
        nvidia_model=NVIDIA_MODEL,
        settings=settings,
        callbacks=callbacks,
    )


def detect_transcription_prerequisite_error(targets: list[SegmentTarget]) -> str | None:
    if not any(target.needs_transcript for target in targets):
        return None
    if shutil.which("ffmpeg") is None:
        return "ffmpeg is not installed; skipping transcript generation"
    if not yt_dlp_available():
        return "yt-dlp is not installed; skipping transcript generation"
    return None


def apply_transcript_result(item: dict[str, Any], target: SegmentTarget, result: TranscriptResult) -> None:
    tx_persistence.apply_transcript_result(
        item,
        target,
        result,
        transcript_model=TRANSCRIPT_MODEL,
        now_iso=now_iso,
    )




def clear_transcript_artifacts(item: dict[str, Any]) -> list[str]:
    return tx_persistence.clear_transcript_artifacts(item)


def clear_headline_artifacts(item: dict[str, Any]) -> list[str]:
    return tx_persistence.clear_headline_artifacts(item)


def log_item_snapshot(stage: str, label: str, item: dict[str, Any]) -> None:
    tx_persistence.log_item_snapshot(stage, label, item)

def print_headline_result(
    *,
    label: str,
    item: dict[str, Any],
    source_text: str,
    source_validation: SourceValidationResult | None,
    headline_result: HeadlineResult | None,
    generation_reason: str,
    source_selection: SourceSelectionResult | None = None,
) -> None:
    metadata = dict((headline_result.metadata or {}) if headline_result else {})
    comparison = metadata.get("comparison") if isinstance(metadata.get("comparison"), dict) else {}
    provider_candidates = comparison.get("provider_candidates") if isinstance(comparison, dict) else {}

    if not provider_candidates:
        raw_provider = str(metadata.get("provider") or (headline_result.source if headline_result else "")).strip().lower()
        raw_rows = metadata.get("provider_candidates") or []
        if raw_provider and raw_rows:
            provider_candidates = {
                raw_provider: [
                    str((row or {}).get("headline") or "").strip()
                    for row in raw_rows
                    if str((row or {}).get("headline") or "").strip()
                ]
            }

    source_validation_info = source_validation
    if source_validation_info is None:
        row = item.get("headline_source_validation") or {}
        if isinstance(row, dict):
            source_validation_info = SourceValidationResult(
                accepted=bool(row.get("accepted", False)),
                reasons=[str(reason) for reason in (row.get("reasons") or [])],
                content_word_count=int(row.get("content_word_count") or 0),
                subject_hint_count=int(row.get("subject_hint_count") or 0),
                action_hint_count=int(row.get("action_hint_count") or 0),
                unknown_ratio=float(row.get("unknown_ratio") or 0.0),
            )

    selected_score = "n/a"
    if isinstance(comparison, dict) and comparison.get("selected_score") is not None:
        selected_score = str(comparison.get("selected_score"))

    print("headline-result ----------------------------------------")
    print(f"item_id: {item.get('id', 'unknown')} label: {label}")
    print(f"transcript_pass: {item.get('transcript_pass') or 'unknown'}")
    print(f"headline_source_text: {source_text or 'none'}")
    if source_selection is not None:
        selected_sentences = [row.normalized for row in source_selection.selected]
        print(f"selected_source_sentences: {selected_sentences or 'none'}")
        print(f"source_candidate_count: {len(source_selection.candidates)}")
    if source_validation_info is not None:
        print(
            "source_validation: "
            f"accepted={source_validation_info.accepted} reasons={source_validation_info.reasons or 'none'} "
            f"content_words={source_validation_info.content_word_count} "
            f"subject_hints={source_validation_info.subject_hint_count} "
            f"action_hints={source_validation_info.action_hint_count} "
            f"unknown_ratio={source_validation_info.unknown_ratio:.3f}"
        )
    else:
        print("source_validation: none")

    if isinstance(provider_candidates, dict) and provider_candidates:
        for provider, rows in provider_candidates.items():
            printable = [str(row) for row in rows if str(row).strip()]
            print(f"provider_candidates[{provider}]: {printable or 'none'}")
    else:
        print("provider_candidates: none")

    print(f"final_headline: {item.get('headline') or (headline_result.text if headline_result else '') or 'none'}")
    print(f"selection_reason: {generation_reason} selected_score={selected_score}")
    print(f"headline_status: {item.get('headline_status') or 'none'}")
    print(f"headline_generation_mode: {item.get('headline_generation_mode') or (headline_result.generation_mode if headline_result else 'none')}")
    print(f"headline_confidence: {item.get('headline_confidence') or (headline_result.confidence if headline_result else 'none')}")
    print(f"headline_source: {item.get('headline_source') or (headline_result.source if headline_result else 'none')}")
    print(f"headline_model: {item.get('headline_model') or (headline_result.model if headline_result else 'none')}")
    fallback_reason = ''
    if headline_result is None:
        fallback_reason = str(item.get('headline_skip_reason') or '').strip()
    elif (item.get('headline_generation_mode') or headline_result.generation_mode) == 'fallback_extractive':
        fallback_reason = str(headline_result.notes or '').strip()
    if fallback_reason:
        print(f"fallback_reason: {fallback_reason}")
    print("--------------------------------------------------------")


def load_processed_videos() -> list[dict[str, Any]]:
    return tio.load_processed_videos(CACHE_PATH)


def parse_timezone_aware_iso_datetime(value: Any) -> datetime | None:
    return tx_targets.parse_timezone_aware_iso_datetime(value)


def load_latest_public_vod_ids(limit: int = 1) -> list[str]:
    if limit <= 0 or not OUT_PATH.exists():
        return []
    try:
        payload = json.loads(OUT_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []

    public_vod_ids: list[str] = []
    for video in payload.get("videos") or []:
        vod_id = str(video.get("vod_id") or video.get("id") or "").strip()
        if not vod_id or vod_id in public_vod_ids:
            continue
        public_vod_ids.append(vod_id)
        if len(public_vod_ids) >= limit:
            break
    return public_vod_ids


def collect_recently_analyzed_vod_ids(videos: list[dict[str, Any]], *, now: datetime) -> list[str]:
    return tx_targets.collect_recently_analyzed_vod_ids(
        videos,
        now=now,
        window_hours=TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS,
    )


def dedupe_preserving_order(values: list[str]) -> list[str]:
    return tx_targets.dedupe_preserving_order(values)


def resolve_target_vod_ids(videos: list[dict[str, Any]], *, options: RunOptions) -> list[str] | None:
    if options.only_vod_id:
        return [options.only_vod_id]

    if TRANSCRIPT_TARGET_SCOPE in {"all", "full"}:
        return None

    now = datetime.now().astimezone()
    target_vod_ids = dedupe_preserving_order(
        load_latest_public_vod_ids(limit=1) + collect_recently_analyzed_vod_ids(videos, now=now)
    )
    if target_vod_ids:
        return target_vod_ids

    for video in videos:
        vod_id = str(video.get("vod_id") or "").strip()
        if vod_id:
            return [vod_id]
    return []


def collect_targets(
    videos: list[dict[str, Any]],
    *,
    headline_enabled: bool,
    options: RunOptions,
    target_vod_ids: list[str] | None = None,
) -> list[SegmentTarget]:
    target_vod_id_set = set(target_vod_ids) if target_vod_ids is not None else None
    targets: list[SegmentTarget] = []
    for video in videos:
        vod_id = str(video.get("vod_id") or "").strip()
        if target_vod_id_set is not None and vod_id not in target_vod_id_set:
            continue
        if options.only_vod_id and vod_id != options.only_vod_id:
            continue
        vod_url = str(video.get("vod_url") or "").strip()
        for item in video.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if options.only_item_id and item_id != options.only_item_id:
                continue
            needs_screenshot = should_generate_segment_screenshot(item, vod_id=vod_id)
            needs_transcript = False
            if not options.headline_only:
                needs_transcript = bool(vod_url) and (
                    should_generate_transcript(item, options=options) or needs_screenshot
                )
            needs_headline = should_generate_headline(
                item,
                headline_enabled=headline_enabled,
                needs_transcript=needs_transcript,
                options=options,
            )
            if not needs_transcript and not needs_headline:
                continue
            base_start = _to_int(item.get("start_sec"))
            base_end = _to_int(item.get("end_sec"))
            if base_start is None or base_end is None:
                continue
            start_sec = max(0, base_start - TRANSCRIPT_PADDING_SEC)
            end_sec = max(base_end + TRANSCRIPT_PADDING_SEC, start_sec + 30)
            if end_sec - start_sec > TRANSCRIPT_MAX_DURATION_SEC:
                end_sec = start_sec + TRANSCRIPT_MAX_DURATION_SEC
            targets.append(
                SegmentTarget(
                    video=video,
                    item=item,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    needs_transcript=needs_transcript,
                    needs_headline=needs_headline,
                )
            )
            if len(targets) >= options.max_segments:
                return targets
    return targets


def should_generate_transcript(item: dict[str, Any], *, options: RunOptions) -> bool:
    if options.force_transcript_refresh:
        return True
    transcript = str(item.get("transcript") or "").strip()
    status = str(item.get("transcript_status") or "").strip().lower()
    if transcript and status in {"ok", "empty"}:
        return False
    if status == "error" and not TRANSCRIPT_RETRY_ERRORS:
        return False
    return True


def should_generate_segment_screenshot(item: dict[str, Any], *, vod_id: str) -> bool:
    if not SEGMENT_SCREENSHOT_GENERATION_ENABLED:
        return False
    segment_id = str(item.get("id") or "").strip()
    if not vod_id or not segment_id:
        return False
    screenshot_url = str(item.get("screenshot_url") or "").strip()
    if not screenshot_url:
        screenshot_url = build_segment_screenshot_public_path(vod_id, segment_id)
        item["screenshot_url"] = screenshot_url
    if not screenshot_url.startswith("/data/segment-thumbnails/"):
        return False

    output_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if not output_path.exists():
        return True
    try:
        return output_path.stat().st_size <= 0
    except OSError:
        return True


def should_generate_headline(
    item: dict[str, Any],
    *,
    headline_enabled: bool,
    needs_transcript: bool,
    options: RunOptions,
) -> bool:
    if not headline_enabled:
        return False
    transcript = str(item.get("transcript") or "").strip()
    if options.force_headline_refresh:
        return needs_transcript or bool(transcript)
    headline = str(item.get("headline") or "").strip()
    status = str(item.get("headline_status") or "").strip().lower()
    if headline and status == "ok":
        return False
    if status == "error" and not HEADLINE_RETRY_ERRORS:
        return False
    return needs_transcript or bool(transcript)


def build_first_pass_config() -> TranscribePassConfig:
    vad_parameters: dict[str, Any] | None = None
    if TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS is not None:
        vad_parameters = {"min_silence_duration_ms": TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS}
    return TranscribePassConfig(
        model=TRANSCRIPT_MODEL,
        preprocess_profile=TRANSCRIPT_PREPROCESS_PROFILE,
        vad_filter=TRANSCRIPT_VAD_FILTER,
        word_timestamps=False,
        condition_on_previous_text=TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT,
        beam_size=TRANSCRIPT_BEAM_SIZE,
        vad_parameters=vad_parameters,
        extra_padding_sec=0,
    )


def build_second_pass_config(*, options: RunOptions | None = None) -> TranscribePassConfig:
    preprocess_profile = TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE
    word_timestamps = TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS
    extra_padding_sec = TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC
    if options is not None:
        preprocess_profile = options.second_pass_preprocess_profile
        word_timestamps = options.second_pass_word_timestamps
        extra_padding_sec = options.second_pass_extra_padding_sec
    return TranscribePassConfig(
        model=TRANSCRIPT_SECOND_PASS_MODEL,
        preprocess_profile=preprocess_profile,
        vad_filter=True,
        word_timestamps=word_timestamps,
        beam_size=1,
        extra_padding_sec=extra_padding_sec,
    )


def build_retranscribe_config(*, options: RunOptions | None = None) -> RetranscribeConfig:
    selection_mode = TRANSCRIPT_SECOND_PASS_SELECTION_MODE
    top_n = max(0, TRANSCRIPT_SECOND_PASS_TOP_N)
    if options is not None:
        selection_mode = options.second_pass_selection_mode
        top_n = max(0, options.second_pass_top_n)
    return RetranscribeConfig(
        enabled=TRANSCRIPT_SECOND_PASS_ENABLED and top_n > 0,
        selection_mode=selection_mode,
        top_n=top_n,
        low_info_token_threshold=TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD,
        suspicious_ratio_threshold=TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD,
    )


def build_audio_preprocess_filters(profile: str) -> str:
    normalized = (profile or "none").strip().lower()
    if normalized == "none":
        return ""
    filters = ["highpass=f=80", "lowpass=f=7600", "loudnorm=I=-16:LRA=11:TP=-1.5"]
    if normalized == "light_denoise":
        filters.append(f"afftdn=nf={TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH}:tn=1")
    return ",".join(filters)


def build_preprocess_ffmpeg_command(input_path: Path, output_path: Path, *, profile: str) -> list[str]:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-sn",
        "-dn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    filters = build_audio_preprocess_filters(profile)
    if filters:
        command.extend(["-af", filters])
    command.append(str(output_path))
    return command


def preprocess_clip_audio(input_path: Path, output_path: Path, profile: str = "light") -> Path:
    command = build_preprocess_ffmpeg_command(input_path, output_path, profile=profile)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise RuntimeError(f"ffmpeg preprocess failed ({profile}): {stderr[:300]}")
    return output_path


def _prepare_audio_for_transcribe(media_path: Path, *, profile: str) -> Path:
    if (profile or "none").strip().lower() == "none":
        return media_path
    output_path = media_path.with_name(f"preprocessed_{profile}.wav")
    print(f"debug: transcript preprocess enabled profile={profile} input={media_path.name}")
    return preprocess_clip_audio(media_path, output_path, profile=profile)


def transcribe_clip_first_pass(
    clip_audio_path: Path,
    config: TranscribePassConfig,
    transcriber: WhisperTranscriber,
) -> TranscriptResult:
    prepared_path = _prepare_audio_for_transcribe(clip_audio_path, profile=config.preprocess_profile)
    return transcriber.transcribe(
        prepared_path,
        model_name=config.model,
        vad_filter=config.vad_filter,
        word_timestamps=config.word_timestamps,
        condition_on_previous_text=config.condition_on_previous_text,
        beam_size=config.beam_size,
        vad_parameters=config.vad_parameters,
    )


def transcribe_clip_second_pass(
    clip_audio_path: Path,
    config: TranscribePassConfig,
    transcriber: WhisperTranscriber,
) -> TranscriptResult:
    prepared_path = _prepare_audio_for_transcribe(clip_audio_path, profile=config.preprocess_profile)
    return transcriber.transcribe(
        prepared_path,
        model_name=config.model,
        vad_filter=config.vad_filter,
        word_timestamps=config.word_timestamps,
        beam_size=config.beam_size,
    )


def transcript_quality_metrics(text: str) -> dict[str, float]:
    return tv.transcript_quality_metrics(
        text,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def _score_retranscribe_priority(item: dict[str, Any], transcript_result: TranscriptResult, config: RetranscribeConfig) -> float:
    return tv.score_retranscribe_priority(
        item,
        transcript_result.text,
        config,
        to_int=_to_int,
        to_optional_float=_to_optional_float,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def should_retranscribe_clip(
    item: dict[str, Any],
    transcript_result: TranscriptResult,
    config: RetranscribeConfig,
) -> bool:
    return tv.should_retranscribe_clip(
        item,
        transcript_result.text,
        config,
        to_int=_to_int,
        to_optional_float=_to_optional_float,
        content_token_re=SOURCE_CONTENT_TOKEN_RE,
        interjection_token_re=SOURCE_INTERJECTION_TOKEN_RE,
    )


def _annotate_zscore_rank(targets: list[SegmentTarget]) -> None:
    tv.annotate_zscore_rank(targets, to_optional_float=_to_optional_float)


def _maybe_extend_window(target: SegmentTarget, extra_padding_sec: int) -> tuple[int, int]:
    if extra_padding_sec <= 0:
        return target.start_sec, target.end_sec
    start_sec = max(0, target.start_sec - extra_padding_sec)
    end_sec = target.end_sec + extra_padding_sec
    if end_sec - start_sec > TRANSCRIPT_MAX_DURATION_SEC:
        end_sec = start_sec + TRANSCRIPT_MAX_DURATION_SEC
    return start_sec, end_sec


def _resolve_segment_screenshot_seek_sec(*, item: dict[str, Any], clip_start_sec: int, clip_end_sec: int) -> float:
    segment_start = _to_int(item.get("start_sec"))
    seek_sec = 0.0
    if segment_start is not None:
        seek_sec = max(0.0, float(segment_start - clip_start_sec) + SEGMENT_SCREENSHOT_CAPTURE_OFFSET_SEC)
    clip_duration = max(0.0, float(clip_end_sec - clip_start_sec))
    max_seek_sec = max(0.0, clip_duration - 0.5)
    return min(seek_sec, max_seek_sec)


def _capture_segment_screenshot(
    *,
    output_path: Path,
    media_path: Path,
    seek_sec: float,
) -> None:
    tx_screenshot.capture_segment_screenshot(
        output_path=output_path,
        media_path=media_path,
        seek_sec=seek_sec,
        width=SEGMENT_SCREENSHOT_WIDTH,
        height=SEGMENT_SCREENSHOT_HEIGHT,
        quality=SEGMENT_SCREENSHOT_QUALITY,
        timeout_sec=SEGMENT_SCREENSHOT_TIMEOUT_SEC,
    )


def maybe_generate_segment_screenshot(
    target: SegmentTarget,
    *,
    media_path: Path,
    clip_start_sec: int,
    clip_end_sec: int,
) -> None:
    if shutil.which("ffmpeg") is None:
        return

    item = target.item
    video = target.video
    vod_id = str(video.get("vod_id") or "").strip()
    segment_id = str(item.get("id") or "").strip()
    if not vod_id or not segment_id:
        return

    screenshot_url = str(item.get("screenshot_url") or "").strip()
    if not screenshot_url:
        screenshot_url = build_segment_screenshot_public_path(vod_id, segment_id)
        item["screenshot_url"] = screenshot_url

    if not screenshot_url.startswith("/data/segment-thumbnails/"):
        return

    output_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    if not SEGMENT_SCREENSHOT_GENERATION_ENABLED:
        return

    seek_sec = _resolve_segment_screenshot_seek_sec(
        item=item,
        clip_start_sec=clip_start_sec,
        clip_end_sec=clip_end_sec,
    )
    _capture_segment_screenshot(output_path=output_path, media_path=media_path, seek_sec=seek_sec)
    item["screenshot_url"] = build_segment_screenshot_public_path(vod_id, segment_id)
    print(f"info: screenshot generated item={segment_id} path={output_path}")


def transcribe_target(
    target: SegmentTarget,
    transcriber: WhisperTranscriber,
    *,
    config: TranscribePassConfig | None = None,
) -> TranscriptResult:
    vod_url = str(target.video.get("vod_url") or "").strip()
    if not vod_url:
        raise RuntimeError("missing vod_url")

    active_config = config or build_first_pass_config()
    start_sec, end_sec = _maybe_extend_window(target, active_config.extra_padding_sec)
    with tempfile.TemporaryDirectory(prefix="vod-segment-") as tmp_dir:
        media_path = download_segment_media(vod_url, start_sec, end_sec, Path(tmp_dir))
        try:
            maybe_generate_segment_screenshot(
                target,
                media_path=media_path,
                clip_start_sec=start_sec,
                clip_end_sec=end_sec,
            )
        except Exception as exc:
            segment_id = str(target.item.get("id") or "segment")
            print(f"warn: screenshot generation failed for {segment_id} ({exc})")
        if active_config.word_timestamps:
            result = transcribe_clip_second_pass(media_path, active_config, transcriber)
        else:
            result = transcribe_clip_first_pass(media_path, active_config, transcriber)
        result.source_text = result.source_text or result.text
        return result


def maybe_retranscribe_top_candidates(
    targets: list[SegmentTarget],
    first_pass_results: dict[str, TranscriptResult],
    transcriber: WhisperTranscriber,
    config: RetranscribeConfig,
    *,
    options: RunOptions | None = None,
) -> dict[str, TranscriptResult]:
    if not config.enabled:
        print("debug: second-pass retranscribe disabled")
        return first_pass_results

    _annotate_zscore_rank(targets)
    eligible: list[tuple[float, SegmentTarget]] = []
    for target in targets:
        label = str(target.item.get("id") or "")
        result = first_pass_results.get(label)
        if not result or not result.text:
            continue
        if not should_retranscribe_clip(target.item, result, config):
            continue
        priority = _score_retranscribe_priority(target.item, result, config)
        eligible.append((priority, target))

    selected = [target for _, target in sorted(eligible, key=lambda row: row[0], reverse=True)[: config.top_n]]
    if not selected:
        print("debug: second-pass retranscribe no targets selected")
        return first_pass_results

    second_pass_config = build_second_pass_config(options=options)
    for target in selected:
        label = f'{target.video.get("vod_id", "unknown")}:{target.item.get("id", "segment")}'
        item_id = str(target.item.get("id") or "")
        before = first_pass_results.get(item_id)
        print(
            "info: second-pass target "
            f"label={label} mode={config.selection_mode} rank={target.item.get('rank')} "
            f"zrank={target.item.get('_second_pass_zscore_rank')} profile={second_pass_config.preprocess_profile}"
        )
        try:
            after = transcribe_target(target, transcriber, config=second_pass_config)
        except Exception as exc:
            print(f"warn: second-pass failed for {label} ({exc})")
            continue

        if TERM_NORMALIZATION_ENABLED:
            normalized = normalize_transcript_terms(after.text, ACTIVE_TERM_DICTIONARY, TERM_NORMALIZATION_CONFIG)
            after.normalized_text = normalized.text
            after.text = normalized.text
            for row in normalized.replacements[:20]:
                print(
                    "debug: second-pass term normalization "
                    f"item={target.item.get('id')} category={row.category} "
                    f"from={row.original} to={row.replacement} sim={row.similarity:.1f}"
                )

        if after.text:
            first_pass_results[item_id] = after
            target.item["_second_pass_applied"] = True
            similarity = text_similarity(before.text if before else "", after.text)
            print(
                "info: second-pass transcript updated "
                f"label={label} similarity={similarity:.2f} "
                f"before_len={len((before.text if before else '').strip())} after_len={len(after.text.strip())}"
            )

    return first_pass_results


def download_segment_media(vod_url: str, start_sec: int, end_sec: int, work_dir: Path) -> Path:
    return tx_audio.download_segment_media(
        vod_url=vod_url,
        start_label=format_section_time(start_sec),
        end_label=format_section_time(end_sec),
        work_dir=work_dir,
        python_executable=sys.executable,
        timeout_sec=TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC,
    )


def yt_dlp_available() -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def format_section_time(value: int) -> str:
    hours = value // 3600
    minutes = (value % 3600) // 60
    seconds = value % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def extract_response_output_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get("output_text") or "").strip()
    if output_text:
        return output_text

    parts: list[str] = []
    for output in payload.get("output") or []:
        for content in output.get("content") or []:
            if content.get("type") == "output_text":
                text = str(content.get("text") or "").strip()
                if text:
                    parts.append(text)
    return " ".join(parts).strip()


def extract_gemini_output_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in payload.get("candidates") or []:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = str(part.get("text") or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def _merge_source_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(SOURCE_DEFAULT_CONFIG)
    if config:
        merged.update(config)
    return merged


def _split_source_sentences_for_headline(text: str) -> list[str]:
    normalized = normalize_source_text(text)
    if not normalized:
        return []

    if SOURCE_SENTENCE_END_RE.search(normalized):
        return [part.strip() for part in re.split(r"[?.!???]+", normalized) if part.strip()]

    chunks: list[str] = []
    current = normalized
    while len(current) > max(12, HEADLINE_MAX_CHARS + 10):
        window = current[: max(12, HEADLINE_MAX_CHARS + 10)]
        split_idx = max(window.rfind("?"), window.rfind(" "), window.rfind("??"), window.rfind("?"))
        if split_idx < 8:
            split_idx = max(12, HEADLINE_MAX_CHARS + 8)
        chunks.append(current[:split_idx].strip(" ??.!???"))
        current = current[split_idx:].strip()
    if current:
        chunks.append(current.strip(" ??.!???"))
    return [chunk for chunk in chunks if chunk]


def clean_source_sentence(sentence: str, config: dict[str, Any] | None = None) -> str:
    del config
    cleaned = normalize_source_text(sentence)
    if not cleaned:
        return ""

    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = SOURCE_NOISE_EDGE_RE.sub("", cleaned).strip()

    cleaned = SOURCE_INTERJECTION_INLINE_RE.sub("", cleaned)
    cleaned = SOURCE_REPEAT_WORD_RE.sub(r"\g<w>", cleaned)
    cleaned = re.sub(r"([?-??-??-?A-Za-z0-9])(?:[?,\s]+\1){1,}", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ??.!???")
    return cleaned


def normalize_headline_source_text(text: str, config: dict[str, Any] | None = None) -> str:
    merged = _merge_source_config(config)
    parts = _split_source_sentences_for_headline(text)
    cleaned_parts: list[str] = []
    for part in parts:
        cleaned = clean_source_sentence(part, merged)
        if not cleaned:
            continue
        if SOURCE_GREETING_ONLY_RE.fullmatch(cleaned) or SOURCE_REACTION_ONLY_RE.fullmatch(cleaned):
            continue
        if SOURCE_INCOMPLETE_END_RE.search(cleaned) and len(cleaned) < 14:
            continue
        if len(cleaned) > int(merged["max_sentence_chars"]):
            cleaned = smart_truncate(cleaned, int(merged["max_sentence_chars"]))
        if cleaned:
            cleaned_parts.append(cleaned)
        if len(cleaned_parts) >= int(merged["max_source_sentences"]):
            break

    normalized = "?".join(cleaned_parts).strip("? ")
    if normalized and not SOURCE_SENTENCE_END_RE.search(normalized):
        normalized = f"{normalized}?"
    normalized = normalize_source_text(normalized)
    if len(normalized) > int(merged["max_source_chars"]):
        normalized = smart_truncate(normalized, int(merged["max_source_chars"]))
    return normalized


def _count_content_words(text: str) -> int:
    return sum(1 for token in _iter_source_tokens(text) if _is_content_token(token))


def _unknown_token_ratio(text: str) -> float:
    tokens = _iter_source_tokens(text)
    if not tokens:
        return 1.0

    unknown = 0
    for token in tokens:
        if _is_content_token(token):
            continue
        if re.fullmatch(r"[\-?~?wW]+", token):
            unknown += 1
            continue
        if len(token) <= 1:
            unknown += 1
            continue
        if token in SOURCE_STOPWORD_TOKENS:
            unknown += 1
    return unknown / len(tokens)


def is_valid_headline_source_text(
    text: str,
    config: dict[str, Any] | None = None,
) -> SourceValidationResult:
    merged = _merge_source_config(config)
    normalized = normalize_source_text(text)
    reasons: list[str] = []

    if not normalized:
        reasons.append("empty_source")
    if SOURCE_GREETING_ONLY_RE.fullmatch(normalized):
        reasons.append("greeting_only")
    if SOURCE_REACTION_ONLY_RE.fullmatch(normalized):
        reasons.append("reaction_only")
    if SOURCE_CALL_ONLY_RE.fullmatch(normalized):
        reasons.append("call_only")

    content_word_count = _count_content_words(normalized)
    if content_word_count < int(merged["min_content_words"]):
        reasons.append("too_few_content_words")

    subject_hint_count = _count_subject_hints(normalized)
    action_hint_count = _count_action_hints(normalized)
    if subject_hint_count == 0:
        reasons.append("missing_subject_hint")
    if action_hint_count == 0:
        reasons.append("missing_action_hint")

    unknown_ratio = _unknown_token_ratio(normalized)
    if unknown_ratio > float(merged["max_unknown_ratio"]):
        reasons.append("too_many_unknown_tokens")

    meaningful_chars = len(re.findall(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]", normalized))
    symbol_ratio = 1.0 - (meaningful_chars / max(1, len(normalized)))
    if symbol_ratio > 0.45:
        reasons.append("too_many_symbols")

    if SOURCE_REPEAT_WORD_RE.search(normalized):
        reasons.append("repeated_noise_phrase")

    stripped = normalized.rstrip("\u3002.!?\uff01\uff1f").strip()
    if stripped and SOURCE_INCOMPLETE_END_RE.search(stripped):
        reasons.append("incomplete_sentence")

    return SourceValidationResult(
        accepted=not reasons,
        reasons=reasons,
        content_word_count=content_word_count,
        subject_hint_count=subject_hint_count,
        action_hint_count=action_hint_count,
        unknown_ratio=unknown_ratio,
    )


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

FINAL_HEADLINE_SOFT_REASONS = {
    "missing_function_word",
    "too_abstract",
    "literal_or_awkward_predicate",
    "missing_topic_hint",
    "weak_predicate_link",
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


def _collect_used_terms(headline: str, source_text: str) -> list[str]:
    terms = collect_source_terms_for_headline(source_text)
    return [term for term in terms if term in headline][:6]


def _headline_title_structure_bonus(
    headline: str,
    *,
    content_word_count: int,
    subject_hint_count: int,
    action_hint_count: int,
) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []

    has_change_hint = bool(HEADLINE_CHANGE_HINT_RE.search(headline))
    has_event_summary = bool(HEADLINE_EVENT_SUMMARY_RE.search(headline))

    if subject_hint_count >= 1 and action_hint_count >= 1:
        bonus += 2.4
        reasons.append("title_noun_action")
    elif subject_hint_count >= 1 and has_change_hint:
        bonus += 1.9
        reasons.append("title_noun_change")

    if has_event_summary:
        bonus += 1.2
        reasons.append("event_summary_shape")
    elif content_word_count >= 3 and action_hint_count >= 1:
        bonus += 0.8
        reasons.append("event_summary_hint")

    if content_word_count >= 2 and len(headline) <= HEADLINE_MAX_CHARS and not HEADLINE_CONVERSATIONAL_END_RE.search(headline):
        bonus += 0.5
        reasons.append("title_compact_shape")

    return bonus, reasons

def validate_final_headline_japanese(
    headline: str,
    *,
    source_text: str | None = None,
    config: dict[str, Any] | None = None,
) -> SourceValidationResult:
    del config
    value = cleanup_headline_candidate(headline)
    reasons: list[str] = []
    if not value:
        reasons.append("empty_or_cleanup_failed")

    content_word_count = _count_content_words(value)
    subject_hint_count = _count_subject_hints(value)
    action_hint_count = _count_action_hints(value)
    unknown_ratio = _unknown_token_ratio(value)

    if re.search(r"([\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9])(?:\1){2,}", value):
        reasons.append("unnatural_repetition")
    if re.search(r"(?:\u3059\u308b\u3059\u308b|\u306a\u308b\u306a\u308b|\u7684\u306a\u611f\u3058|\u3053\u3068\u306b\u3064\u3044\u3066)$", value):
        reasons.append("literal_or_awkward_predicate")
    if HEADLINE_LOW_SIGNAL_RE.search(value) and content_word_count < 2:
        reasons.append("too_abstract")
    if not hlv.contains_function_like_tokens(value, function_word_re=HEADLINE_FUNCTION_WORD_RE):
        reasons.append("missing_function_word")
    if re.search(r"(?:\u3051\u3069|\u3051\u308c\u3069|\u3051\u308c\u3069\u3082|\u304b\u3089|\u306e\u3067|\u3063\u3066|\u3068\u304b|and|but|so)$", value, re.IGNORECASE):
        reasons.append("incomplete_tail")
    if HEADLINE_CONVERSATIONAL_PHRASE_RE.search(value):
        reasons.append("conversational_phrase")
    if HEADLINE_CONVERSATIONAL_END_RE.search(value):
        reasons.append("conversational_tail")
    if HEADLINE_CONVERSATIONAL_FRAGMENT_RE.search(value):
        reasons.append("conversation_fragment")
    if HEADLINE_IMPRESSION_FRAGMENT_RE.search(value):
        reasons.append("reflective_impression_fragment")
    if HEADLINE_FIRST_PERSON_PRONOUN_RE.search(value) and (
        HEADLINE_IMPRESSION_FRAGMENT_RE.search(value) or HEADLINE_CONVERSATIONAL_PHRASE_RE.search(value) or content_word_count <= 3
    ):
        reasons.append("first_person_casual_fragment")
    if re.search(r"(?:\u3067|\u306b|\u3092|\u304c|\u306f|\u306e|\u3068)$", value):
        reasons.append("dangling_particle")
    if len(value) > max(24, HEADLINE_MAX_CHARS):
        reasons.append("too_long_for_title")
    if subject_hint_count == 0 and content_word_count < 2:
        reasons.append("missing_topic_hint")
    if not TITLE_ENDING_FUNCTION_RE.search(value) and action_hint_count == 0 and content_word_count >= 3:
        reasons.append("weak_predicate_link")

    normalized_source = normalize_source_text(source_text or "")
    if normalized_source:
        similarity = text_similarity(normalize_source_text(value), normalized_source)
        source_len = max(1, len(normalized_source))
        length_ratio = len(value) / source_len
        if similarity >= 0.92:
            reasons.append("near_source_copy")
        elif similarity >= 0.84 and length_ratio >= 0.78:
            reasons.append("insufficient_compression")

    hard_reasons = [reason for reason in reasons if reason not in FINAL_HEADLINE_SOFT_REASONS]
    return SourceValidationResult(
        accepted=not hard_reasons,
        reasons=reasons,
        content_word_count=content_word_count,
        subject_hint_count=subject_hint_count,
        action_hint_count=action_hint_count,
        unknown_ratio=unknown_ratio,
    )


PUBLISH_BLOCKING_HEADLINE_REASONS = {
    "missing_function_word",
    "too_abstract",
    "literal_or_awkward_predicate",
    "missing_topic_hint",
}
PUBLISH_CONVERSATIONAL_EDGE_RE = re.compile(
    r"^(?:あー|えー|いや|まあ|なんか|はい|なんで)|(?:っていう|ってい|というか|して|まして|ませ)$"
)


def is_publishable_headline(headline: str, *, source_text: str | None = None) -> bool:
    value = cleanup_headline_candidate(headline)
    if len(value) < 8 or len(value) > 24:
        return False
    validation = validate_final_headline_japanese(value, source_text=source_text)
    if not validation.accepted:
        return False
    if any(reason in PUBLISH_BLOCKING_HEADLINE_REASONS for reason in validation.reasons):
        return False
    if PUBLISH_CONVERSATIONAL_EDGE_RE.search(value):
        return False
    if "?" in value or "？" in value:
        return False
    if value.endswith("に注目が集まる"):
        return False
    return value != DEFAULT_HEADLINE_TEXT


def headline_confidence_label(*, score_total: float, candidate_confidence: float, penalty: float = 0.0) -> str:
    weighted = score_total + (candidate_confidence * 2.0) - (penalty * 0.8)
    if weighted >= 9.5:
        return "high"
    if weighted >= 5.0:
        return "medium"
    return "low"


def score_headline_candidate_with_source(
    candidate: HeadlineCandidate,
    source_text: str,
    config: dict[str, Any] | None = None,
) -> HeadlineScore:
    active_config = config or {}
    source_validation = active_config.get("source_validation")
    source_penalty = compute_source_quality_penalty(source_validation) if isinstance(source_validation, SourceValidationResult) else 0.0

    headline = cleanup_headline_candidate(candidate.headline)
    if not headline or headline.upper() == "SKIP":
        return HeadlineScore(total=-100.0, breakdown={"skip": -100.0}, reasons=["skip_candidate"])
    if not candidate.can_publish:
        return HeadlineScore(total=-80.0, breakdown={"blocked": -80.0}, reasons=["candidate_not_publishable"])

    source_terms = collect_source_terms_for_headline(source_text)
    used_terms = [term for term in source_terms if term in headline]
    source_game_terms = collect_game_term_hits(source_text)
    headline_game_terms = collect_game_term_hits(headline)
    content_word_count = _count_content_words(headline)
    base = score_headline_candidate(headline)

    reused_term_score = min(5.0, len(used_terms) * 1.3)
    specific_word_score = min(3.5, content_word_count * 0.7)
    game_term_bonus = min(2.8, len(headline_game_terms) * 1.4)
    missing_game_term_penalty = 1.4 if source_game_terms and not headline_game_terms else 0.0
    headline_validation = validate_final_headline_japanese(headline, source_text=source_text)
    naturalness_penalty = float(len([reason for reason in headline_validation.reasons if reason not in FINAL_HEADLINE_SOFT_REASONS])) * 2.2
    soft_naturalness_penalty = float(len([reason for reason in headline_validation.reasons if reason in FINAL_HEADLINE_SOFT_REASONS])) * 0.4
    abstract_penalty = 2.6 if HEADLINE_LOW_SIGNAL_RE.search(headline) and content_word_count < 2 else 0.0
    conversational_tail_penalty = 4.2 if HEADLINE_CONVERSATIONAL_END_RE.search(headline) else 0.0
    conversational_phrase_penalty = 3.0 if HEADLINE_CONVERSATIONAL_PHRASE_RE.search(headline) else 0.0
    conversational_fragment_penalty = 2.2 if HEADLINE_CONVERSATIONAL_FRAGMENT_RE.search(headline) else 0.0
    impression_fragment_penalty = 2.8 if HEADLINE_IMPRESSION_FRAGMENT_RE.search(headline) else 0.0
    first_person_penalty = 2.5 if HEADLINE_FIRST_PERSON_PRONOUN_RE.search(headline) else 0.0

    title_structure_bonus, title_structure_reasons = _headline_title_structure_bonus(
        headline,
        content_word_count=content_word_count,
        subject_hint_count=headline_validation.subject_hint_count,
        action_hint_count=headline_validation.action_hint_count,
    )

    source_similarity = text_similarity(normalize_source_text(headline), normalize_source_text(source_text))
    copied_source_penalty = 3.4 if source_similarity >= 0.93 else (1.2 if source_similarity >= 0.82 else 0.0)

    hallucination_penalty = 0.0
    for token in collect_source_terms_for_headline(headline):
        if token not in source_text and token not in source_terms and len(token) >= 3:
            hallucination_penalty += 0.8

    if 10 <= len(headline) <= min(20, HEADLINE_MAX_CHARS):
        length_score = 1.8
    elif 8 <= len(headline) <= HEADLINE_MAX_CHARS:
        length_score = 0.5
    elif 6 <= len(headline) <= HEADLINE_MAX_CHARS + 4:
        length_score = -0.8
    elif len(headline) < 6:
        length_score = -1.4
    else:
        length_score = -2.0 - ((len(headline) - HEADLINE_MAX_CHARS) * 0.35)

    confidence_bonus = max(0.0, min(1.0, candidate.confidence)) * 1.1
    source_quality_penalty = source_penalty * 0.35

    total = (
        base
        + reused_term_score
        + specific_word_score
        + length_score
        + title_structure_bonus
        + confidence_bonus
        + game_term_bonus
        - missing_game_term_penalty
        - abstract_penalty
        - naturalness_penalty
        - soft_naturalness_penalty
        - conversational_tail_penalty
        - conversational_phrase_penalty
        - conversational_fragment_penalty
        - impression_fragment_penalty
        - first_person_penalty
        - copied_source_penalty
        - hallucination_penalty
        - source_quality_penalty
    )
    return HeadlineScore(
        total=total,
        breakdown={
            "base": base,
            "reuse_terms": reused_term_score,
            "specific_words": specific_word_score,
            "length": length_score,
            "candidate_confidence": confidence_bonus,
            "copy_penalty": -copied_source_penalty,
            "abstract_penalty": -abstract_penalty,
            "naturalness_penalty": -naturalness_penalty,
            "soft_naturalness_penalty": -soft_naturalness_penalty,
            "title_structure_bonus": title_structure_bonus,
            "game_term_bonus": game_term_bonus,
            "missing_game_term_penalty": -missing_game_term_penalty,
            "conversational_tail_penalty": -conversational_tail_penalty,
            "conversational_phrase_penalty": -conversational_phrase_penalty,
            "conversational_fragment_penalty": -conversational_fragment_penalty,
            "impression_fragment_penalty": -impression_fragment_penalty,
            "first_person_penalty": -first_person_penalty,
            "hallucination_penalty": -hallucination_penalty,
            "source_quality_penalty": -source_quality_penalty,
            "source_similarity": source_similarity,
        },
        reasons=[
            f"used_terms={len(used_terms)}",
            f"content_words={content_word_count}",
            f"source_similarity={source_similarity:.2f}",
            f"candidate_mode={candidate.generation_mode or 'unspecified'}",
            f"headline_game_terms={headline_game_terms or []}",
            f"title_structure={','.join(title_structure_reasons) if title_structure_reasons else 'none'}",
        ],
    )


def choose_best_headline(
    candidates: list[HeadlineCandidate],
    source_text: str,
    config: dict[str, Any] | None = None,
) -> HeadlineCandidate:
    if not candidates:
        return HeadlineCandidate(headline="SKIP", used_terms=[], confidence=0.0, reason="no_candidates", can_publish=False)

    scored_rows: list[tuple[HeadlineCandidate, HeadlineScore]] = []
    for candidate in candidates:
        score = score_headline_candidate_with_source(candidate, source_text, config)
        scored_rows.append((candidate, score))
        print(
            "debug: headline candidate scored "
            f"headline={candidate.headline} score={score.total:.2f} breakdown={score.breakdown} reasons={score.reasons}"
        )

    scored_rows.sort(key=lambda row: row[1].total, reverse=True)
    best, best_score = scored_rows[0]
    print(
        "info: headline selected "
        f"headline={best.headline} score={best_score.total:.2f} used_terms={best.used_terms} "
        f"candidate_reason={best.reason} candidate_mode={best.generation_mode or 'unspecified'}"
    )
    return best

def generate_headline_candidates(source_text: str, config: dict[str, Any] | None = None) -> list[HeadlineCandidate]:
    del config
    raw_candidates = collect_headline_candidates(source_text)[:12]
    generated: list[HeadlineCandidate] = []
    seen: set[str] = set()
    flavors = ("summary_lean", "extractive_lean", "safe_lean")

    for idx, text in enumerate(raw_candidates):
        cleaned = cleanup_headline_candidate(text)
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        used_terms = _collect_used_terms(cleaned, source_text)
        generated.append(
            HeadlineCandidate(
                headline=cleaned,
                used_terms=used_terms,
                confidence=0.42 + min(0.5, len(used_terms) * 0.12),
                reason="heuristic_source_window",
                can_publish=True,
                generation_mode=flavors[min(idx, len(flavors) - 1)],
                notes="local_candidate",
            )
        )
        if len(generated) >= 3:
            break
    return generated

def parse_headline_candidates_output(text: str, source_text: str) -> list[HeadlineCandidate]:
    value = str(text or "").strip()
    if not value:
        return generate_headline_candidates(source_text)
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value).strip()

    candidate_payloads: list[dict[str, Any]] = []
    for raw in (value, extract_json_like_fragment(value)):
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows = payload.get("candidates")
            if isinstance(rows, list):
                candidate_payloads.extend(row for row in rows if isinstance(row, dict))
            headline = str(payload.get("headline") or "").strip()
            if headline:
                candidate_payloads.append({"headline": headline, "reason": "legacy_single_headline"})

    parsed: list[HeadlineCandidate] = []
    for row in candidate_payloads:
        headline = cleanup_headline_candidate(str(row.get("headline") or ""))
        if not headline:
            continue
        used_terms_raw = row.get("used_terms") or []
        used_terms = [str(term).strip() for term in used_terms_raw if str(term).strip()]
        if not used_terms:
            used_terms = _collect_used_terms(headline, source_text)
        confidence = _to_optional_float(row.get("confidence"))
        if confidence is None:
            confidence = 0.5
        reason = str(row.get("reason") or row.get("notes") or "llm_candidate").strip() or "llm_candidate"
        generation_mode = str(row.get("generation_mode") or "llm_ranked").strip() or "llm_ranked"
        notes = str(row.get("notes") or "").strip()
        can_publish = bool(row.get("can_publish", True))
        parsed.append(
            HeadlineCandidate(
                headline=headline,
                used_terms=used_terms,
                confidence=max(0.0, min(1.0, confidence)),
                reason=reason,
                can_publish=can_publish,
                generation_mode=generation_mode,
                notes=notes,
            )
        )

    if not parsed:
        parsed = generate_headline_candidates(source_text)

    return parsed[:3]

def build_remote_headline_prompt(
    *,
    provider: str,
    video_title: str,
    start_time: str,
    end_time: str,
    transcript: str,
    prepared_transcript: str | None = None,
) -> tuple[str, str]:
    del provider
    prepared_transcript = prepared_transcript or build_headline_source_text(transcript, HEADLINE_SOURCE_CONFIG)
    instructions = (
        "You create concise Japanese headlines for Twitch highlight clips. "
        "Return a JSON object with a field named candidates. "
        "Generate exactly 3 candidates in one response. "
        "Each candidate must contain headline, used_terms, confidence, reason, can_publish. "
        "generation_mode and notes are optional. "
        "Use only facts explicitly present in the source text. "
        "Do not add names, events, or details that are not in the source text. "
        f"Keep each headline natural Japanese and under {HEADLINE_MAX_CHARS} characters. "
        "Reuse concrete source terms when possible, but do not copy the source sentence verbatim. "
        "When source is weak, still output short readable headlines (safe/extractive allowed). "
        "Never return SKIP if source text is non-empty."
    )
    prompt = (
        f"Stream title: {video_title}\n"
        f"Clip range: {start_time} - {end_time}\n"
        "Rules:\n"
        "- Source faithful: no hallucination.\n"
        "- Prefer concise title-like event summaries over conversational phrasing.\n"
        "- Keep concrete nouns/actions from source.\n"
        "- Provide three quality variants: summary-lean, extractive-lean, safe-lean.\n"
        "- Avoid conversational tails/fragments like 「〜けど」「〜かな」「〜かも」「というか」「なんか」。\n"
        "- Prefer event summaries that read well as a list headline.\n"
        "- Avoid plain transcript copy/paste.\n"
        f"Source text (already normalized): {prepared_transcript}\n"
        "Return JSON only."
    )
    return instructions, prompt

def build_headline_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "used_terms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                        "can_publish": {"type": "boolean"},
                    },
                    "required": ["headline", "used_terms", "confidence", "reason", "can_publish"],
                    "additionalProperties": False,
                },
            },
            "headline": {
                "type": "string",
                "description": "Backward-compatible single headline field.",
            },
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def build_headline_retry_prompt(
    *,
    provider: str,
    video_title: str,
    start_time: str,
    end_time: str,
    transcript: str,
    previous_headline: str,
    issues: list[str],
) -> tuple[str, str]:
    instructions, prompt = build_remote_headline_prompt(
        provider=provider,
        video_title=video_title,
        start_time=start_time,
        end_time=end_time,
        transcript=transcript,
        prepared_transcript=None,
    )
    repair_prompt = (
        f"{prompt}\n"
        f"Previous headline: {previous_headline}\n"
        "That headline was rejected. Write one better alternative.\n"
        "Issues to fix:\n"
        + "\n".join(f"- {issue}" for issue in issues)
        + "\nReturn JSON with candidates only."
    )
    return instructions, repair_prompt


def text_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=str(left or ""), b=str(right or "")).ratio()


def load_term_dictionary(path: Path | str) -> TermDictionary:
    return tpp.load_term_dictionary(path)


def normalize_transcript_terms(
    text: str,
    term_dict: TermDictionary,
    config: TermNormalizationConfig,
) -> NormalizedTranscriptResult:
    return tpp.normalize_transcript_terms(text, term_dict, config)


def merge_term_dictionaries(*term_dictionaries: TermDictionary) -> TermDictionary:
    return tpp.merge_term_dictionaries(*term_dictionaries)


BASE_TERM_DICTIONARY = load_term_dictionary(Path(TERM_DICTIONARY_PATH))
GAME_TERM_DICTIONARY = load_term_dictionary(Path(GAME_TERM_DICTIONARY_PATH))


TERM_NORMALIZATION_CONFIG = TermNormalizationConfig(
    similarity_threshold=TERM_NORMALIZATION_SIMILARITY,
    min_token_len=TERM_NORMALIZATION_MIN_TOKEN_LEN,
    min_term_len=TERM_NORMALIZATION_MIN_TERM_LEN,
)


def resolve_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    return tpp.resolve_active_term_dictionary(
        use_game_term_dictionary=use_game_term_dictionary,
        base_term_dictionary=BASE_TERM_DICTIONARY,
        game_term_dictionary=GAME_TERM_DICTIONARY,
    )


ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(USE_GAME_TERM_DICTIONARY_DEFAULT)


def set_active_term_dictionary(use_game_term_dictionary: bool) -> TermDictionary:
    global ACTIVE_TERM_DICTIONARY
    ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(use_game_term_dictionary)
    return ACTIVE_TERM_DICTIONARY


def build_headline_source_config(
    *,
    source_sentence_limit: int = SOURCE_SENTENCE_LIMIT_DEFAULT,
    print_source_selection: bool = PRINT_SOURCE_SELECTION_DEFAULT,
    use_game_term_dictionary: bool = USE_GAME_TERM_DICTIONARY_DEFAULT,
) -> dict[str, Any]:
    active_term_dictionary = resolve_active_term_dictionary(use_game_term_dictionary)
    return {
        "bonus_terms": [entry.canonical for entry in active_term_dictionary.entries],
        "max_source_sentences": max(1, min(2, int(source_sentence_limit))),
        "print_source_selection": bool(print_source_selection),
        "use_game_term_dictionary": bool(use_game_term_dictionary),
    }


HEADLINE_SOURCE_CONFIG = build_headline_source_config()


def refresh_runtime_configuration() -> None:
    global PREPROCESS_CONTEXT
    global SOURCE_SENTENCE_SPLIT_RE
    global SOURCE_INTERJECTION_RE
    global SOURCE_TRAILING_CHATTER_RE
    global SOURCE_LOW_SIGNAL_CLAUSE_RE
    global SOURCE_CLAUSE_MAX_CHARS
    global BASE_TERM_DICTIONARY
    global GAME_TERM_DICTIONARY
    global TERM_NORMALIZATION_CONFIG
    global ACTIVE_TERM_DICTIONARY
    global HEADLINE_SOURCE_CONFIG

    PREPROCESS_CONTEXT = hlp.merge_preprocess_context(
        headline_max_chars=HEADLINE_MAX_CHARS,
        streamer_id=HEADLINE_STREAMER_ID,
    )
    SOURCE_SENTENCE_SPLIT_RE = PREPROCESS_CONTEXT.patterns.sentence_split_re
    SOURCE_INTERJECTION_RE = PREPROCESS_CONTEXT.patterns.interjection_re
    SOURCE_TRAILING_CHATTER_RE = PREPROCESS_CONTEXT.patterns.trailing_chatter_re
    SOURCE_LOW_SIGNAL_CLAUSE_RE = PREPROCESS_CONTEXT.patterns.low_signal_re
    SOURCE_CLAUSE_MAX_CHARS = PREPROCESS_CONTEXT.source_clause_max_chars
    BASE_TERM_DICTIONARY = load_term_dictionary(Path(TERM_DICTIONARY_PATH))
    GAME_TERM_DICTIONARY = load_term_dictionary(Path(GAME_TERM_DICTIONARY_PATH))
    TERM_NORMALIZATION_CONFIG = TermNormalizationConfig(
        similarity_threshold=TERM_NORMALIZATION_SIMILARITY,
        min_token_len=TERM_NORMALIZATION_MIN_TOKEN_LEN,
        min_term_len=TERM_NORMALIZATION_MIN_TERM_LEN,
    )
    ACTIVE_TERM_DICTIONARY = resolve_active_term_dictionary(USE_GAME_TERM_DICTIONARY_DEFAULT)
    HEADLINE_SOURCE_CONFIG = build_headline_source_config(
        source_sentence_limit=SOURCE_SENTENCE_LIMIT_DEFAULT,
        print_source_selection=PRINT_SOURCE_SELECTION_DEFAULT,
        use_game_term_dictionary=USE_GAME_TERM_DICTIONARY_DEFAULT,
    )


def _contains_dictionary_term(text: str, term: str) -> bool:
    target = str(term or "").strip()
    value = str(text or "")
    if not value or not target:
        return False
    if re.search(r"[A-Za-z0-9]", target):
        return bool(re.search(rf"\b{re.escape(target)}\b", value, flags=re.IGNORECASE))
    return target in value


def _contains_exact_alias_token(
    tokens: set[str],
    lowered_tokens: set[str],
    alias: str,
) -> bool:
    target = str(alias or "").strip()
    if not target:
        return False
    if re.search(r"[A-Za-z0-9]", target):
        return target.lower() in lowered_tokens
    if target in tokens:
        return True
    for token in tokens:
        if not token.startswith(target):
            continue
        suffix = token[len(target) :]
        if suffix in EXACT_ALIAS_PARTICLE_SUFFIXES:
            return True
    return False


def _collect_game_term_match_info(
    text: str,
    term_dictionary: TermDictionary | None = None,
) -> tuple[list[str], list[str], list[str]]:
    value = normalize_source_text(text)
    if not value:
        return [], [], []
    source_tokens = {token for token in _iter_source_tokens(value) if token}
    source_tokens_lowered = {token.lower() for token in source_tokens}
    dictionary = term_dictionary or ACTIVE_TERM_DICTIONARY
    hits: list[str] = []
    canonical_hits: list[str] = []
    alias_only_hits: list[str] = []
    seen_hits: set[str] = set()
    seen_canonical: set[str] = set()
    seen_alias_only: set[str] = set()
    for entry in dictionary.entries:
        if entry.category != "game_terms":
            continue
        canonical = sanitize_headline(entry.canonical)
        if not canonical:
            continue
        canonical_in_exact_aliases = any(
            str(alias).strip() == entry.canonical for alias in entry.exact_aliases
        )
        if canonical_in_exact_aliases:
            canonical_hit = _contains_exact_alias_token(
                source_tokens,
                source_tokens_lowered,
                entry.canonical,
            )
        else:
            canonical_hit = _contains_dictionary_term(value, entry.canonical)
        alias_hit = any(_contains_dictionary_term(value, alias) for alias in entry.aliases)
        exact_alias_hit = any(
            _contains_exact_alias_token(source_tokens, source_tokens_lowered, alias)
            for alias in entry.exact_aliases
        )
        if not canonical_hit and not alias_hit and not exact_alias_hit:
            continue
        if canonical not in seen_hits:
            seen_hits.add(canonical)
            hits.append(canonical)
        if canonical_hit:
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                canonical_hits.append(canonical)
            continue
        if canonical not in seen_alias_only:
            seen_alias_only.add(canonical)
            alias_only_hits.append(canonical)
    return hits, canonical_hits, alias_only_hits

def _collect_optional_alias_hits(
    text: str,
    term_dictionary: TermDictionary | None = None,
) -> list[str]:
    value = normalize_source_text(text)
    if not value:
        return []
    dictionary = term_dictionary or ACTIVE_TERM_DICTIONARY
    hits: list[str] = []
    seen: set[str] = set()
    for alias, canonical in dictionary.optional_aliases.items():
        alias_text = str(alias).strip()
        canonical_text = str(canonical).strip()
        if not alias_text or alias_text == canonical_text:
            continue
        if not _contains_dictionary_term(value, alias_text):
            continue
        if canonical_text and _contains_dictionary_term(value, canonical_text):
            continue
        if alias_text in seen:
            continue
        seen.add(alias_text)
        hits.append(alias_text)
    return hits

def collect_game_term_hits(text: str, term_dictionary: TermDictionary | None = None) -> list[str]:
    hits, _canonical_hits, _alias_only_hits = _collect_game_term_match_info(
        text,
        term_dictionary=term_dictionary,
    )
    return hits


def collect_source_terms_for_headline(transcript: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for game_term in collect_game_term_hits(transcript):
        if game_term in seen:
            continue
        seen.add(game_term)
        terms.append(game_term)
        if len(terms) >= 6:
            return terms

    for token in _iter_source_tokens(transcript):
        cleaned = sanitize_headline(token)
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        if not _is_content_token(cleaned):
            continue
        seen.add(cleaned)
        terms.append(cleaned)
        if len(terms) >= 6:
            break
    return terms


def contains_emoji(text: str) -> bool:
    return any(0x1F300 <= ord(char) <= 0x1FAFF for char in text)


def has_excessive_symbols(text: str) -> bool:
    symbol_count = len(re.findall(r"[!???#*~|/\\]+", text))
    return symbol_count >= 3


def headline_reuses_source_terms(headline: str, transcript: str) -> bool:
    terms = collect_source_terms_for_headline(transcript)
    if not terms:
        return True
    return any(term in headline for term in terms[:4])


def validate_headline_result(headline: str, *, transcript: str) -> hlv.ValidationResult:
    source_terms = collect_source_terms_for_headline(transcript)
    return hlv.validate_headline(
        headline,
        source_terms,
        sanitize_headline=sanitize_headline,
        meta_re=HEADLINE_META_RE,
        sensitive_re=HEADLINE_SENSITIVE_RE,
        low_signal_re=HEADLINE_LOW_SIGNAL_RE,
        broken_phrase_re=HEADLINE_BROKEN_PHRASE_RE,
        function_word_re=HEADLINE_FUNCTION_WORD_RE,
        contains_emoji=contains_emoji,
        has_excessive_symbols=has_excessive_symbols,
        allowed_chars_re=HEADLINE_ALLOWED_CHARS_RE,
    )


def compare_tokenizer_function_detection(headlines: list[str]) -> list[dict[str, Any]]:
    active_tokenizer = hlv.resolve_tokenizer()
    fallback_tokenizer = hlv.RegexFallbackTokenizer()
    rows: list[dict[str, Any]] = []
    for headline in headlines:
        rows.append(
            {
                "headline": headline,
                "active_tokenizer": active_tokenizer.name,
                "active_detected": hlv.contains_function_like_tokens(
                    headline,
                    function_word_re=HEADLINE_FUNCTION_WORD_RE,
                    tokenizer=active_tokenizer,
                ),
                "fallback_tokenizer": fallback_tokenizer.name,
                "fallback_detected": hlv.contains_function_like_tokens(
                    headline,
                    function_word_re=HEADLINE_FUNCTION_WORD_RE,
                    tokenizer=fallback_tokenizer,
                ),
            }
        )
    return rows


def explain_headline_issues(headline: str, *, transcript: str) -> list[str]:
    return validate_headline_result(headline, transcript=transcript).issue_messages


def split_headline_issues(issues: list[str]) -> tuple[list[str], list[str]]:
    return hlv.split_headline_issues(issues, soft_issue_set=SOFT_HEADLINE_ISSUES)


def rank_headline_candidate(text: str, *, transcript: str) -> tuple[int, int, float]:
    validation = validate_headline_result(text, transcript=transcript)
    source_terms = collect_source_terms_for_headline(transcript)
    score = hls.score_headline(
        headline=text,
        source_terms=source_terms,
        base_score=score_headline_candidate(text),
        validation_result=validation,
    )
    return (-len(validation.hard_issues), -len(validation.soft_issues), score.total)


def _normalized_provider_name(candidate: HeadlineResult) -> str:
    metadata = dict(candidate.metadata or {})
    return str(metadata.get("provider") or candidate.source or "unknown").strip().lower() or "unknown"


def _to_candidate_confidence(value: Any) -> float:
    confidence = _to_optional_float(value)
    if confidence is None:
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _candidate_confidence_from_metadata(metadata: dict[str, Any]) -> float:
    confidence = _to_optional_float(metadata.get("candidate_confidence"))
    if confidence is None:
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def _build_remote_comparison_pool(candidates: list[HeadlineResult]) -> list[HeadlineResult]:
    provider_pool: dict[str, list[HeadlineResult]] = defaultdict(list)
    provider_seen: dict[str, set[str]] = defaultdict(set)
    provider_order: list[str] = []

    def _append_candidate(
        *,
        provider: str,
        headline: str,
        model: str,
        generation_mode: str,
        notes: str,
        metadata: dict[str, Any],
    ) -> None:
        cleaned = cleanup_headline_candidate(headline)
        if not cleaned:
            return
        if cleaned in provider_seen[provider]:
            return
        if len(provider_pool[provider]) >= 3:
            return
        provider_seen[provider].add(cleaned)
        row_metadata = dict(metadata)
        row_metadata["provider"] = provider
        provider_pool[provider].append(
            HeadlineResult(
                text=cleaned,
                model=model,
                source=provider,
                generation_mode=generation_mode,
                confidence="medium",
                notes=notes,
                metadata=row_metadata,
            )
        )

    for candidate in candidates:
        metadata = dict(candidate.metadata or {})
        provider = _normalized_provider_name(candidate)
        if provider not in provider_order:
            provider_order.append(provider)

        raw_provider_candidates = metadata.get("provider_candidates") or []
        for rank, row in enumerate(raw_provider_candidates, start=1):
            if not isinstance(row, dict):
                continue
            if not bool(row.get("can_publish", True)):
                continue
            _append_candidate(
                provider=provider,
                headline=str(row.get("headline") or "").strip(),
                model=candidate.model,
                generation_mode=str(row.get("generation_mode") or candidate.generation_mode or "llm_ranked").strip() or "llm_ranked",
                notes=str(row.get("reason") or row.get("notes") or "provider_candidate_pool").strip() or "provider_candidate_pool",
                metadata={
                    "attempt": metadata.get("attempt"),
                    "origin": "provider_candidate",
                    "provider_candidate_rank": rank,
                    "candidate_confidence": _to_candidate_confidence(row.get("confidence")),
                    "provider_candidate_reason": str(row.get("reason") or "provider_candidate").strip() or "provider_candidate",
                },
            )

        selected_meta = metadata.get("provider_selected") or {}
        _append_candidate(
            provider=provider,
            headline=candidate.text,
            model=candidate.model,
            generation_mode=str(candidate.generation_mode or selected_meta.get("generation_mode") or "llm_ranked").strip() or "llm_ranked",
            notes=str(candidate.notes or selected_meta.get("reason") or "provider_selected").strip() or "provider_selected",
            metadata={
                "attempt": metadata.get("attempt"),
                "origin": "provider_selected",
                "candidate_confidence": _to_candidate_confidence(selected_meta.get("confidence")),
                "provider_candidate_reason": str(selected_meta.get("reason") or "provider_selected").strip() or "provider_selected",
            },
        )

    pool: list[HeadlineResult] = []
    for provider in provider_order:
        pool.extend(provider_pool.get(provider) or [])

    if pool:
        return pool
    return candidates


def choose_best_remote_headline(candidates: list[HeadlineResult], *, transcript: str) -> tuple[HeadlineResult, dict[str, Any]]:
    pool = _build_remote_comparison_pool(candidates)
    evaluations: list[hls.CandidateEvaluation] = []
    source_terms = collect_source_terms_for_headline(transcript)

    for candidate in pool:
        metadata = dict(candidate.metadata or {})
        candidate_confidence = _candidate_confidence_from_metadata(metadata)
        source_score = score_headline_candidate_with_source(
            HeadlineCandidate(
                headline=candidate.text,
                used_terms=_collect_used_terms(candidate.text, transcript),
                confidence=candidate_confidence,
                reason=str(metadata.get("provider_candidate_reason") or "remote_pool").strip() or "remote_pool",
                can_publish=True,
                generation_mode=str(candidate.generation_mode or "llm_ranked").strip() or "llm_ranked",
                notes=str(candidate.notes or "").strip(),
            ),
            transcript,
        )
        validation = validate_headline_result(candidate.text, transcript=transcript)
        score = hls.score_headline(
            headline=candidate.text,
            source_terms=source_terms,
            base_score=source_score.total,
            validation_result=validation,
        )
        evaluations.append(hls.CandidateEvaluation(text=candidate.text, validation=validation, score=score))

    hlp.summarize_candidate_evaluations(evaluations, logger=print)
    winner = hlp.choose_best_candidate(evaluations, logger=print)

    provider_candidates: dict[str, list[str]] = {}
    provider_pool_counts: dict[str, int] = {}
    pool_candidates: list[dict[str, Any]] = []
    selected: HeadlineResult | None = None
    selected_score = 0.0

    for index, candidate in enumerate(pool):
        metadata = dict(candidate.metadata or {})
        provider_name = _normalized_provider_name(candidate)
        provider_rows = provider_candidates.setdefault(provider_name, [])
        if candidate.text not in provider_rows:
            provider_rows.append(candidate.text)
        provider_pool_counts[provider_name] = provider_pool_counts.get(provider_name, 0) + 1

        evaluation = evaluations[index]
        if candidate.text == winner.text and selected is None:
            selected = candidate
            selected_score = evaluation.score.total

        pool_candidates.append(
            {
                "provider": provider_name,
                "attempt": metadata.get("attempt"),
                "origin": metadata.get("origin") or "unknown",
                "headline": candidate.text,
                "model": candidate.model,
                "score_total": round(evaluation.score.total, 3),
                "hard_issues": list(evaluation.validation.hard_issues),
                "soft_issues": list(evaluation.validation.soft_issues),
            }
        )

    if selected is None:
        selected = pool[0]

    summary = {
        "selected_headline": selected.text,
        "selected_source": selected.source,
        "selected_score": round(selected_score, 3),
        "provider_candidates": provider_candidates,
        "provider_pool_counts": provider_pool_counts,
        "comparison_pool_size": len(pool),
        "pool_candidates": pool_candidates,
    }
    return selected, summary

def build_natural_fallback_headline(*, transcript: str, video_title: str) -> str:
    terms = [term for term in collect_source_terms_for_headline(transcript) if term not in SOFT_DROP_HEADLINE_TOKENS]
    if len(terms) >= 3:
        candidate = finalize_headline(f"{terms[0]}?{terms[1]}???")
        if not explain_headline_issues(candidate, transcript=transcript):
            return candidate
    if len(terms) >= 2:
        candidate = finalize_headline(f"{terms[0]}?{terms[1]}")
        if not explain_headline_issues(candidate, transcript=transcript):
            return candidate
    heuristic = build_rule_based_headline(transcript=transcript)
    if heuristic and not explain_headline_issues(heuristic, transcript=transcript):
        return finalize_headline(heuristic)
    fallback_title = strip_stream_title(video_title)
    if fallback_title and not explain_headline_issues(fallback_title, transcript=transcript):
        return finalize_headline(fallback_title)
    return ""


def find_unusable_headline_reason(text: str, *, video_title: str) -> str | None:
    value = sanitize_headline(text)
    if not value:
        return "empty headline"
    lowered = value.lower()
    if lowered in {"headline", "json", "1", "5"}:
        return "placeholder-like headline"
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}\s*[-~]\s*\d{2}:\d{2}:\d{2}\)?", value):
        return "time range only"
    broken_markers = (
        "json",
        "headline",
        "stream title:",
        "clip range:",
        "transcript notes:",
        "bad examples:",
        "good style:",
        "return only json",
        '{"headline"',
    )
    if any(marker in lowered for marker in broken_markers):
        return "meta explanation leaked into headline"
    if lowered.startswith(("stream title:", "clip range:", "transcript notes:", "bad examples:", "good style:")):
        return "prompt field leaked into headline"
    stripped_title = strip_stream_title(video_title)
    if stripped_title and sanitize_headline(stripped_title) == value:
        return "stream title copied as headline"
    return None


def ensure_usable_remote_headline(*, text: str, video_title: str, provider: str, transcript: str) -> str:
    raw_value = sanitize_headline(text)
    if raw_value and HEADLINE_ALLOWED_CHARS_RE.fullmatch(raw_value) and re.search(r"[\s\u3001,\u30fb]", raw_value):
        raise HeadlineProviderError(
            provider,
            "returned low-quality headline: looks like a noun list instead of a natural phrase",
        )
    finalized = finalize_headline(cleanup_headline_candidate(text) or text)
    reason = find_unusable_headline_reason(finalized, video_title=video_title)
    if reason:
        raise HeadlineProviderError(provider, f"returned unusable headline: {reason}")
    validation = validate_headline_result(finalized, transcript=transcript)
    final_japanese_validation = validate_final_headline_japanese(finalized, source_text=transcript)
    print(
        "debug: headline validation "
        f"provider={provider} headline={finalized} "
        f"hard={validation.hard_issues or 'none'} soft={validation.soft_issues or 'none'} "
        f"flags={validation.info_flags or 'none'} final_reasons={final_japanese_validation.reasons or 'none'}"
    )
    if validation.hard_issues:
        raise HeadlineProviderError(
            provider,
            f"returned low-quality headline: {hlp.format_rejection_summary(validation)}",
        )
    if not final_japanese_validation.accepted:
        raise HeadlineProviderError(
            provider,
            f"returned low-quality headline: final_japanese_filter={','.join(final_japanese_validation.reasons)}",
        )
    return finalized

def normalize_headline_output(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value).strip()
    for candidate in (value, extract_json_like_fragment(value)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows = payload.get("candidates")
            if isinstance(rows, list) and rows:
                first = rows[0] if isinstance(rows[0], dict) else {}
                first_headline = str(first.get("headline") or "").strip()
                if first_headline:
                    return first_headline
            headline = str(payload.get("headline") or "").strip()
            if headline:
                return headline
    return value


def extract_json_like_fragment(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return ""
    return text[start : end + 1].strip()


def read_http_error_detail(exc: error.HTTPError) -> str:
    if not hasattr(exc, "read"):
        return ""
    try:
        return exc.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def classify_gemini_http_error(code: int, detail: str) -> tuple[str, bool]:
    payload_status = ""
    payload_message = ""
    try:
        payload = json.loads(detail) if detail else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        error_payload = payload.get("error") or {}
        if isinstance(error_payload, dict):
            payload_status = str(error_payload.get("status") or "").strip()
            payload_message = str(error_payload.get("message") or "").strip()

    detail_text = " ".join(part for part in (payload_status, payload_message, detail[:200]) if part).strip()
    normalized = detail_text.lower()
    retryable = code in {408, 409, 429, 500, 502, 503, 504}
    if code == 429 or "resource_exhausted" in normalized:
        return ("RESOURCE_EXHAUSTED / HTTP 429", True)
    if "unavailable" in normalized or code == 503:
        return (f"temporary unavailable (HTTP {code})", True)
    if "deadline_exceeded" in normalized or "timeout" in normalized or "timed out" in normalized:
        return (f"request timed out (HTTP {code})", True)
    if retryable:
        return (f"temporary API error (HTTP {code})", True)
    message = payload_message or detail[:200] or f"HTTP {code}"
    return (f"HTTP {code}: {message}", False)


def is_temporary_transport_error(reason: str) -> bool:
    normalized = str(reason or "").lower()
    return any(
        keyword in normalized
        for keyword in (
            "timed out",
            "timeout",
            "temporary",
            "temporarily unavailable",
            "connection reset",
            "connection aborted",
            "connection refused",
            "service unavailable",
        )
    )


def build_fallback_extractive_result(
    *,
    prepared_source_text: str,
    transcript: str,
    video_title: str,
    reason: str,
    source_config: dict[str, Any] | None = None,
) -> HeadlineResult:
    active_source_config = source_config or HEADLINE_SOURCE_CONFIG
    source_text = prepared_source_text or build_headline_source_text(transcript, active_source_config)
    headline = build_extractive_headline(transcript=source_text, video_title=video_title, source_config=active_source_config)
    return HeadlineResult(
        text=headline,
        model=LOCAL_HEADLINE_MODEL,
        source="extractive",
        generation_mode="fallback_extractive",
        confidence="low",
        notes=reason,
    )


def build_tag_based_fallback_headline(tags: Any) -> str:
    normalized_tags = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
    fallback_by_tag = (
        ("好プレー", "好プレーで盛り上がる"),
        ("おめ", "祝福コメントが集まる"),
        ("ホラー", "緊張の展開にざわつく"),
        ("まずい", "予想外の展開に驚く"),
        ("ww", "笑いが一気に広がる"),
        ("えっど", "意外な発言にざわつく"),
        ("えっ", "意外な展開に驚く"),
        ("つべ", "話題の発言で盛り上がる"),
    )
    for tag, fallback in fallback_by_tag:
        if tag in normalized_tags:
            return fallback
    return "コメントが一気に増える"


def build_safe_fallback_headline(*, transcript: str, video_title: str) -> str:
    heuristic = build_pattern_fallback_headline(transcript=transcript, video_title=video_title)
    if heuristic and is_publishable_headline(heuristic):
        return heuristic
    return DEFAULT_HEADLINE_TEXT


def is_safe_extractive_headline_candidate(headline: str, *, source_text: str) -> bool:
    cleaned = cleanup_headline_candidate(headline)
    if not cleaned:
        return False
    if len(cleaned) > HEADLINE_MAX_CHARS:
        return False
    if HEADLINE_CONVERSATIONAL_END_RE.search(cleaned) or HEADLINE_CONVERSATIONAL_PHRASE_RE.search(cleaned):
        return False
    if SOURCE_SELECTION_SUSPICIOUS_RE.search(cleaned):
        return False

    validation = validate_final_headline_japanese(cleaned, source_text=source_text)
    if not validation.accepted:
        return False

    source_similarity = text_similarity(normalize_source_text(cleaned), normalize_source_text(source_text))
    if source_similarity >= 0.78 and len(cleaned) >= 16:
        return False

    if _count_action_hints(cleaned) == 0 and not collect_game_term_hits(cleaned):
        return False

    return True


def build_extractive_headline(
    *,
    transcript: str,
    video_title: str,
    source_config: dict[str, Any] | None = None,
) -> str:
    preferred = build_rule_based_headline(transcript=transcript)
    if preferred and not explain_headline_issues(preferred, transcript=transcript):
        return finalize_headline(preferred)

    active_source_config = source_config or HEADLINE_SOURCE_CONFIG
    source_text = build_headline_source_text(transcript, active_source_config)
    candidates = collect_headline_candidates(source_text)
    if not candidates:
        return build_safe_fallback_headline(transcript=source_text or transcript, video_title=video_title)

    best = ""
    best_score = float("-inf")
    for candidate in candidates:
        cleaned = cleanup_headline_candidate(candidate)
        if not cleaned:
            continue
        if not is_safe_extractive_headline_candidate(cleaned, source_text=source_text or transcript):
            continue
        if explain_headline_issues(cleaned, transcript=source_text or transcript):
            continue
        score = score_headline_candidate(cleaned) + (_count_action_hints(cleaned) * 0.6)
        if collect_game_term_hits(cleaned):
            score += 1.1
        if score > best_score:
            best = cleaned
            best_score = score

    if not best:
        return build_safe_fallback_headline(transcript=source_text or transcript, video_title=video_title)
    return finalize_headline(best)


def collect_source_term_counts(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for token in _iter_source_tokens(text):
        cleaned = sanitize_headline(token)
        if not cleaned or len(cleaned) < 2:
            continue
        if not _is_content_token(cleaned):
            continue
        counts[cleaned] += 1
    return counts


def split_source_text(text: str) -> list[str]:
    return hpp.split_source_text(text, sentence_split_re=SOURCE_SENTENCE_SPLIT_RE)


def normalize_source_clause(clause: str) -> str:
    return hpp.normalize_source_clause(
        clause,
        normalize_source_text=normalize_source_text,
        collapse_japanese_spacing=collapse_japanese_spacing,
        smart_truncate=smart_truncate,
        filler_prefix_re=FILLER_PREFIX_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
        max_chars=SOURCE_CLAUSE_MAX_CHARS,
        interjection_re=SOURCE_INTERJECTION_RE,
        trailing_chatter_re=SOURCE_TRAILING_CHATTER_RE,
        low_signal_re=SOURCE_LOW_SIGNAL_CLAUSE_RE,
    )


def is_low_signal_clause(clause: str) -> bool:
    return hpp.is_low_signal_clause(
        clause,
        low_signal_re=SOURCE_LOW_SIGNAL_CLAUSE_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
    )


def extract_candidate_clauses(text: str) -> list[str]:
    return hpp.extract_candidate_clauses(
        text,
        normalize_source_text=normalize_source_text,
        collapse_japanese_spacing=collapse_japanese_spacing,
        smart_truncate=smart_truncate,
        filler_prefix_re=FILLER_PREFIX_RE,
        japanese_char_re=JAPANESE_CHAR_RE,
        context=PREPROCESS_CONTEXT,
        logger=print,
    )


def cleanup_source_clause(text: str) -> str:
    return normalize_source_clause(text)


def split_source_clauses(text: str) -> list[str]:
    return extract_candidate_clauses(text)


def trim_unsupported_trailing_token(clause: str, *, term_counts: Counter[str]) -> str:
    parts = str(clause or '').split()
    if len(parts) < 2:
        return str(clause or '').strip()
    trailing = sanitize_headline(parts[-1])
    if not trailing or len(trailing) > 6:
        return str(clause or '').strip()
    if HEADLINE_FUNCTION_WORD_RE.search(trailing):
        return str(clause or '').strip()
    if term_counts.get(trailing, 0) > 1:
        return str(clause or '').strip()
    trimmed = ' '.join(parts[:-1]).strip()
    if len(trimmed) < 10:
        return str(clause or '').strip()
    return trimmed


def _is_greeting_or_reaction_clause(clause: str) -> bool:
    normalized = normalize_source_text(clause).lower()
    if not normalized:
        return True
    if SOURCE_ONLY_GREET_RE.fullmatch(normalized):
        return True
    tokens = [token for token in re.split(r"[\s??,.!???]+", normalized) if token]
    if not tokens:
        return True
    reaction_tokens = {'lol', 'www', 'wow', 'gg', 'nice', 'ok', 'yeah', 'hmm', 'grass'}
    return all(token in reaction_tokens for token in tokens)


def _interjection_ratio(clause: str) -> float:
    tokens = [token for token in re.split(r"[\s??,.!???]+", normalize_source_text(clause).lower()) if token]
    if not tokens:
        return 1.0
    matched = sum(1 for token in tokens if SOURCE_INTERJECTION_TOKEN_RE.search(token))
    return matched / len(tokens)


def _content_token_count(clause: str) -> int:
    return sum(1 for token in _iter_source_tokens(clause) if _is_content_token(token))


def _strip_reaction_prefix(clause: str) -> str:
    return re.sub(
        r"^(?:\s*(?:lol|wow|gg|nice|www+|grass+|hmm|uh|um)[\s,?.!???]*)+",
        '',
        str(clause or ''),
        flags=re.IGNORECASE,
    ).strip()


def _segment_sentence_candidates(
    segment: dict[str, Any],
    *,
    offset_index: int,
) -> list[dict[str, Any]]:
    raw_text = str(segment.get('text') or '').strip()
    if not raw_text:
        return []

    normalized_segment = normalize_source_text(raw_text)
    if not normalized_segment:
        return []

    parts = split_source_clauses(normalized_segment)
    if not parts:
        parts = [normalized_segment]

    seg_start = _to_optional_float(segment.get('start'))
    seg_end = _to_optional_float(segment.get('end'))
    if seg_start is not None and seg_end is not None and seg_end <= seg_start:
        seg_end = seg_start + 1.0

    has_word_timestamps = bool(segment.get('words'))
    total_parts = max(1, len(parts))
    rows: list[dict[str, Any]] = []
    for idx, part in enumerate(parts):
        cleaned = normalize_source_clause(part)
        cleaned = _strip_reaction_prefix(cleaned)
        if not cleaned:
            continue
        if _is_greeting_or_reaction_clause(cleaned):
            continue
        if seg_start is not None and seg_end is not None:
            span = max(0.2, seg_end - seg_start)
            part_start = seg_start + span * (idx / total_parts)
            part_end = seg_start + span * ((idx + 1) / total_parts)
        else:
            part_start = None
            part_end = None
        rows.append(
            {
                'index': offset_index + idx,
                'text': cleaned,
                'start_sec': part_start,
                'end_sec': part_end,
                'has_word_timestamps': has_word_timestamps,
            }
        )
    return rows


def _collect_source_sentence_candidates(
    transcript_result: TranscriptResult | str,
) -> list[dict[str, Any]]:
    if isinstance(transcript_result, TranscriptResult):
        transcript = transcript_result.normalized_text or transcript_result.text
        segments = transcript_result.segments or []
    else:
        transcript = str(transcript_result or '')
        segments = []

    rows: list[dict[str, Any]] = []
    if segments:
        cursor = 0
        for segment in segments:
            segment_rows = _segment_sentence_candidates(segment, offset_index=cursor)
            rows.extend(segment_rows)
            cursor += max(1, len(segment_rows))

    if not rows:
        clauses = split_source_clauses(transcript)
        if not clauses:
            clauses = [normalize_source_text(transcript)] if normalize_source_text(transcript) else []
        for idx, clause in enumerate(clauses):
            cleaned = normalize_source_clause(clause)
            cleaned = _strip_reaction_prefix(cleaned)
            if not cleaned:
                continue
            if _is_greeting_or_reaction_clause(cleaned):
                continue
            rows.append(
                {
                    'index': idx,
                    'text': cleaned,
                    'start_sec': None,
                    'end_sec': None,
                    'has_word_timestamps': False,
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = normalize_source_text(str(row.get('text') or ''))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    denominator = max(1, len(deduped) - 1)
    for order, row in enumerate(deduped):
        row['position_ratio'] = 0.5 if len(deduped) == 1 else (order / denominator)
    return deduped


def _candidate_midpoint_abs_sec(candidate: dict[str, Any], context: SourceSelectionContext | None) -> float | None:
    if context is None:
        return None
    start_sec = _to_optional_float(candidate.get('start_sec'))
    end_sec = _to_optional_float(candidate.get('end_sec'))
    if start_sec is not None or end_sec is not None:
        midpoint_local = ((start_sec or end_sec or 0.0) + (end_sec or start_sec or 0.0)) / 2.0
        if context.transcript_window_start_sec is None:
            return midpoint_local
        return float(context.transcript_window_start_sec) + midpoint_local

    window_start = _to_optional_float(context.transcript_window_start_sec)
    window_end = _to_optional_float(context.transcript_window_end_sec)
    if window_start is None or window_end is None or window_end <= window_start:
        return None
    ratio = float(candidate.get('position_ratio') or 0.5)
    ratio = max(0.0, min(1.0, ratio))
    return window_start + ((window_end - window_start) * ratio)


def _score_center_proximity(candidate_midpoint_abs: float | None, context: SourceSelectionContext | None) -> float:
    if context is None or candidate_midpoint_abs is None:
        return 0.0
    scene_start = _to_optional_float(context.scene_start_sec)
    scene_end = _to_optional_float(context.scene_end_sec)
    if scene_start is None or scene_end is None or scene_end <= scene_start:
        return 0.0
    center = (scene_start + scene_end) / 2.0
    half = max(1.0, (scene_end - scene_start) / 2.0)
    distance_ratio = min(1.0, abs(candidate_midpoint_abs - center) / half)
    return (1.0 - distance_ratio) * 3.2


def _score_activity_peak(candidate_midpoint_abs: float | None, context: SourceSelectionContext | None) -> float:
    if context is None or candidate_midpoint_abs is None:
        return 0.0
    activity_map = context.activity_map or {}
    bucket_sec = int(activity_map.get('bucket_sec') or 0)
    buckets = activity_map.get('buckets') or []
    if bucket_sec <= 0 or not isinstance(buckets, list) or not buckets:
        return 0.0

    scene_start = int(_to_optional_float(context.scene_start_sec) or 0)
    scene_end = int(_to_optional_float(context.scene_end_sec) or 0)
    if scene_end <= scene_start:
        scene_start = int(context.transcript_window_start_sec or 0)
        scene_end = int(context.transcript_window_end_sec or scene_start)
    if scene_end <= scene_start:
        return 0.0

    start_idx = max(0, int(scene_start // bucket_sec))
    end_idx = min(len(buckets) - 1, int(scene_end // bucket_sec))
    if end_idx < start_idx:
        return 0.0

    local_buckets = buckets[start_idx : end_idx + 1]
    if not local_buckets:
        return 0.0

    local_peak = max(local_buckets)
    if local_peak <= 0:
        return 0.0

    candidate_idx = int(candidate_midpoint_abs // bucket_sec)
    candidate_idx = max(0, min(len(buckets) - 1, candidate_idx))
    candidate_count = float(buckets[candidate_idx])

    peak_offset = local_buckets.index(local_peak)
    peak_idx = start_idx + peak_offset
    peak_sec = (peak_idx + 0.5) * bucket_sec
    half_scene = max(1.0, (scene_end - scene_start) / 2.0)
    proximity = max(0.0, 1.0 - (abs(candidate_midpoint_abs - peak_sec) / half_scene))
    intensity = max(0.0, min(1.0, candidate_count / float(local_peak)))
    return (proximity * 2.0) + (intensity * 1.6)


def _score_source_sentence_candidate(
    raw_candidate: dict[str, Any],
    *,
    context: SourceSelectionContext | None,
    all_term_counts: Counter[str],
) -> SourceSentenceCandidate:
    text = str(raw_candidate.get('text') or '').strip()
    normalized = normalize_source_text(text)
    game_term_hits_list, canonical_term_hits, alias_only_term_hits = _collect_game_term_match_info(normalized)
    game_term_hits = tuple(game_term_hits_list)
    optional_alias_hits = _collect_optional_alias_hits(normalized)
    midpoint_abs = _candidate_midpoint_abs_sec(raw_candidate, context)
    center_score = _score_center_proximity(midpoint_abs, context)
    activity_score = _score_activity_peak(midpoint_abs, context)
    game_term_score = min(4.8, len(game_term_hits) * 2.1)
    action_hints = _count_action_hints(normalized)
    action_score = min(2.8, action_hints * 1.2)
    content_words = _content_token_count(normalized)
    token_count = len(_iter_source_tokens(normalized))
    meaning_score = 1.4 if content_words >= 2 else -1.2
    if content_words >= 4:
        meaning_score += 0.8
    has_word_timestamps = bool(raw_candidate.get('has_word_timestamps'))
    word_timestamp_bonus = 0.9 if has_word_timestamps else 0.0
    term_reuse_score = min(2.2, sum(min(2, all_term_counts.get(term, 0)) for term in game_term_hits) * 0.6)
    noise_penalty = _interjection_ratio(normalized) * 2.8
    incomplete_penalty = 2.4 if SOURCE_INCOMPLETE_END_RE.search(normalized.rstrip('?.!???').strip()) else 0.0
    chatter_penalty = 2.0 if SOURCE_SELECTION_CHATTER_RE.search(normalized) and not game_term_hits and action_hints == 0 else 0.0
    no_term_penalty = 1.2 if not game_term_hits else 0.0
    colloquial_penalty = 1.8 if SOURCE_SELECTION_COLLOQUIAL_TAIL_RE.search(normalized.rstrip('?.!???').strip()) else 0.0
    unknown_ratio = _unknown_token_ratio(normalized)
    optional_alias_penalty = min(3.8, len(optional_alias_hits) * 1.9)
    alias_only_penalty = min(3.6, len(alias_only_term_hits) * 1.4)
    if game_term_hits and not canonical_term_hits and alias_only_term_hits:
        alias_only_penalty += 1.1
    long_noise_penalty = 0.0
    if token_count >= 11:
        long_noise_penalty += min(2.8, (token_count - 10) * 0.32)
    if token_count >= 8 and unknown_ratio > 0.3:
        long_noise_penalty += min(1.6, (unknown_ratio - 0.3) * 4.0)
    compact_bonus = 0.0
    if 3 <= content_words <= 8 and 4 <= token_count <= 10 and unknown_ratio <= 0.28:
        compact_bonus += 0.8
        if action_hints > 0:
            compact_bonus += 0.3
        if game_term_hits:
            compact_bonus += 0.2
    compact_bonus = min(1.4, compact_bonus)
    suspicious_penalty = 0.0
    if unknown_ratio > 0.55:
        suspicious_penalty += min(2.8, (unknown_ratio - 0.55) * 6.0)
    if SOURCE_SELECTION_SUSPICIOUS_RE.search(normalized):
        suspicious_penalty += 1.2
    reaction_penalty = 2.0 if _is_greeting_or_reaction_clause(normalized) else 0.0
    low_signal_penalty = 1.4 if is_low_signal_clause(normalized) else 0.0
    score = (
        center_score
        + activity_score
        + game_term_score
        + action_score
        + meaning_score
        + word_timestamp_bonus
        + term_reuse_score
        + compact_bonus
        - noise_penalty
        - incomplete_penalty
        - chatter_penalty
        - no_term_penalty
        - colloquial_penalty
        - optional_alias_penalty
        - alias_only_penalty
        - long_noise_penalty
        - suspicious_penalty
        - reaction_penalty
        - low_signal_penalty
    )
    breakdown = {
        'center_proximity': round(center_score, 3),
        'activity_peak': round(activity_score, 3),
        'game_term_bonus': round(game_term_score, 3),
        'action_bonus': round(action_score, 3),
        'meaning_bonus': round(meaning_score, 3),
        'word_timestamp_bonus': round(word_timestamp_bonus, 3),
        'term_reuse_bonus': round(term_reuse_score, 3),
        'compact_bonus': round(compact_bonus, 3),
        'noise_penalty': -round(noise_penalty, 3),
        'incomplete_penalty': -round(incomplete_penalty, 3),
        'chatter_penalty': -round(chatter_penalty, 3),
        'no_term_penalty': -round(no_term_penalty, 3),
        'colloquial_penalty': -round(colloquial_penalty, 3),
        'optional_alias_penalty': -round(optional_alias_penalty, 3),
        'alias_only_penalty': -round(alias_only_penalty, 3),
        'long_noise_penalty': -round(long_noise_penalty, 3),
        'suspicious_penalty': -round(suspicious_penalty, 3),
        'reaction_penalty': -round(reaction_penalty, 3),
        'low_signal_penalty': -round(low_signal_penalty, 3),
        'token_count': float(token_count),
        'unknown_ratio': round(unknown_ratio, 3),
    }
    reasons = (
        f'game_term_hits={list(game_term_hits) or []}',
        f'canonical_term_hits={canonical_term_hits or []}',
        f'alias_only_term_hits={alias_only_term_hits or []}',
        f'optional_alias_hits={optional_alias_hits or []}',
        f'action_hints={action_hints}',
        f'content_words={content_words}',
        f'token_count={token_count}',
        f'has_word_timestamps={has_word_timestamps}',
    )
    return SourceSentenceCandidate(
        index=int(raw_candidate.get('index') or 0),
        text=text,
        normalized=normalized,
        start_sec=_to_optional_float(raw_candidate.get('start_sec')),
        end_sec=_to_optional_float(raw_candidate.get('end_sec')),
        has_word_timestamps=has_word_timestamps,
        game_term_hits=game_term_hits,
        score=score,
        breakdown=breakdown,
        reasons=reasons,
    )


def _select_source_sentences(
    scored_candidates: list[SourceSentenceCandidate],
    *,
    sentence_limit: int,
) -> tuple[SourceSentenceCandidate, ...]:
    if not scored_candidates:
        return tuple()

    ranked = sorted(scored_candidates, key=lambda row: row.score, reverse=True)
    primary = ranked[0]
    selected: list[SourceSentenceCandidate] = [primary]

    if sentence_limit <= 1 or len(ranked) == 1:
        return tuple(selected)

    def _connection_score(candidate: SourceSentenceCandidate) -> float:
        index_gap = abs(candidate.index - primary.index)
        gap_score = 1.3 - (index_gap * 0.4)
        if index_gap > 3:
            gap_score -= 1.0
        similarity = text_similarity(candidate.normalized, primary.normalized)
        sequence_bonus = 0.35 if candidate.index > primary.index else 0.2
        return (candidate.score * 0.35) + gap_score + (similarity * 1.4) + sequence_bonus

    runner = max((row for row in ranked[1:]), key=_connection_score, default=None)
    if runner is not None:
        connection_score = _connection_score(runner)
        if connection_score >= 1.1 and runner.score >= primary.score - 4.8:
            selected.append(runner)

    selected = sorted(selected, key=lambda row: row.index)
    return tuple(selected[:sentence_limit])


def _log_source_selection(
    *,
    context: SourceSelectionContext,
    selection: SourceSelectionResult,
    source_text: str,
) -> None:
    print('source-selection ----------------------------------------')
    print(f'item_id: {context.item_id or "unknown"}')
    print(f'transcript_pass: {context.transcript_pass or "unknown"}')
    print('candidate_sentences:')
    if not selection.candidates:
        print('none')
    else:
        for candidate in sorted(selection.candidates, key=lambda row: row.score, reverse=True):
            print(
                'candidate '
                f'index={candidate.index} score={candidate.score:.3f} '
                f'game_term_hit={list(candidate.game_term_hits) or []} '
                f'word_timestamps={candidate.has_word_timestamps} '
                f'breakdown={candidate.breakdown} '
                f'text={candidate.normalized}'
            )
    selected_texts = [candidate.normalized for candidate in selection.selected]
    print(f'selected_sentences: {selected_texts or "none"}')
    print(f'headline_source_text: {source_text or "none"}')
    print('---------------------------------------------------------')


def _build_source_selection_result(
    transcript_result: TranscriptResult | str,
    *,
    context: SourceSelectionContext | None,
    sentence_limit: int,
) -> SourceSelectionResult:
    raw_candidates = _collect_source_sentence_candidates(transcript_result)
    if not raw_candidates:
        return SourceSelectionResult(candidates=tuple(), selected=tuple())

    term_counts = collect_source_term_counts(' '.join(str(row.get('text') or '') for row in raw_candidates))
    scored_candidates = [
        _score_source_sentence_candidate(row, context=context, all_term_counts=term_counts)
        for row in raw_candidates
    ]
    selected = _select_source_sentences(scored_candidates, sentence_limit=sentence_limit)
    return SourceSelectionResult(candidates=tuple(scored_candidates), selected=selected)


def build_headline_source_text(
    transcript_result: TranscriptResult | str,
    config: dict[str, Any] | None = None,
    *,
    selection_context: SourceSelectionContext | None = None,
    selection_result_out: dict[str, Any] | None = None,
) -> str:
    active_config = _merge_source_config(config)
    sentence_limit = max(1, min(2, int(active_config.get('max_source_sentences') or 2)))
    if selection_context is not None:
        sentence_limit = max(1, min(2, int(selection_context.sentence_limit or sentence_limit)))

    if isinstance(transcript_result, TranscriptResult):
        transcript = transcript_result.normalized_text or transcript_result.text
    else:
        transcript = str(transcript_result or '')

    selection = _build_source_selection_result(
        transcript_result,
        context=selection_context,
        sentence_limit=sentence_limit,
    )

    selected_sentences = [row.normalized for row in selection.selected if row.normalized]
    if selected_sentences:
        raw_source_text = '?'.join(selected_sentences)
    else:
        raw_source_text = normalize_source_text(transcript)

    normalized_source_text = normalize_headline_source_text(raw_source_text, active_config)
    if not normalized_source_text:
        normalized_source_text = normalize_headline_source_text(transcript, active_config)

    if selection_result_out is not None:
        selection_result_out['selection'] = selection
        selection_result_out['selected_sentences'] = selected_sentences

    print_selection = bool(active_config.get('print_source_selection', False))
    if selection_context is not None and (selection_context.print_details or print_selection):
        _log_source_selection(context=selection_context, selection=selection, source_text=normalized_source_text)

    print(f'debug: headline source normalized before={raw_source_text} after={normalized_source_text}')

    validation = is_valid_headline_source_text(normalized_source_text, active_config)
    print(
        'debug: headline source validation '
        f'accepted={validation.accepted} reasons={validation.reasons or "none"} '
        f'content_words={validation.content_word_count} subjects={validation.subject_hint_count} '
        f'actions={validation.action_hint_count} unknown_ratio={validation.unknown_ratio:.2f}'
    )
    return normalized_source_text


def build_rule_based_headline(*, transcript: str) -> str:
    text = normalize_source_text(transcript)
    rules = (
        ("\u5149\u308b\u9053\u306e\u898b\u843d\u3068\u3057\u306b\u6c17\u3065\u304f", (r"\u5149\u3063\u3066\u306a\u304b\u3063\u305f|\u898b\u3048\u3066\u305f", r"\u3053\u3053\u306a\u3093\u3060|\u9003\u304c\u3057\u3066|\u8f2a\u90ed")),
        ("\u7d42\u308f\u3089\u306a\u3044\u6df1\u591c\u30c8\u30fc\u30af", (r"\u6c38\u9060", r"\u6642\u9593|\u3084\u308d\u3046")),
        ("\u8db3\u9996\u306e\u30bf\u30c8\u30a5\u30fc\u306b\u61a7\u308c\u305f\u8a71", (r"\u8db3\u9996", r"\u5148\u751f|\u5973\u306e\u5b50", r"\u30bf\u30c8\u30a5\u30fc|\u305f\u3068\u3044\u3046|\u304a\u82b1")),
        ("\u597d\u304d\u304c\u7dda\u3067\u3064\u306a\u304c\u308b\u611f\u899a", (r"\u30d4\u30fc\u30b9", r"\u7dda|\u661f\u5ea7|\u5f62\u306b\u306a\u308b")),
        ("\u3057\u3093\u3069\u3055\u3092\u7b11\u3044\u8a71\u306b\u5909\u3048\u308b", (r"\u3042\u308b\u3042\u308b|\u5927\u5909", r"\u4f11|\u75c5|\u6b7b\u306c\u3089")),
        ("\u53ef\u611b\u3044\u5973\u306e\u5b50\u3092\u63cf\u304f\u96e3\u3057\u3055", (r"\u304b\u308f\u3086\u3046|\u304b\u308f\u3044\u3044|\u5973\u306e\u5b50", r"\u63cf\u304f|\u66f8\u304f", r"\u96e3")),
        ("\u602a\u3057\u3044URL\u306b\u8b66\u6212\u3059\u308b", (r"URL|IP|\u30ab\u30e2\u30d5\u30e9",)),
        ("\u30c8\u30e9\u30d6\u30eb\u4e2d\u306b\u30e2\u30f3\u30af\u6483\u6c88", (r"YouTube|\u3084\u3064\u3079|\u67a0", r"\u30e2\u30f3\u30af|\u3084\u3089\u308c\u305f", r"\u6b7b\u3093\u3060|\u30af\u30e9\u30c3\u30b7\u30e5")),
        ("\u6016\u3044\u90e8\u5c4b\u3092\u307f\u3093\u306a\u3067\u78ba\u8a8d", (r"\u6016\u3044", r"\u307f\u3093\u306a\u3067", r"\u78ba\u8a8d|\u958b\u304b\u306a\u3044|\u5965")),
        ("\u30e9\u30b9\u30dc\u30b9\u6226\u3078\u306e\u624b\u5fdc\u3048", (r"\u30e9\u30b9\u30dc\u30b9", r"\u30ef\u30f3\u30d1\u30f3|\u30a2\u30a4\u30c6\u30e0|\u307e\u3060\u3044\u308b")),
    )
    for headline, patterns in rules:
        if all(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            return headline
    return ""


def build_pattern_fallback_headline(*, transcript: str, video_title: str) -> str:
    natural = build_natural_fallback_headline(transcript=transcript, video_title=video_title)
    if natural:
        return natural
    heuristic = build_rule_based_headline(transcript=transcript)
    if heuristic and not explain_headline_issues(heuristic, transcript=transcript):
        return finalize_headline(heuristic)
    fallback_title = strip_stream_title(video_title)
    if fallback_title and not explain_headline_issues(fallback_title, transcript=transcript):
        return finalize_headline(fallback_title)
    return ""


def collect_headline_candidates(text: str) -> list[str]:

    normalized = normalize_source_text(text)
    if not normalized:
        return []

    candidates: list[str] = []
    candidates.extend(part.strip() for part in re.split(r"[\r\n\u3002\uff01\uff1f!?]+", normalized) if part.strip())

    words = [word for word in normalized.split(" ") if word.strip()]
    for window_size in (1, 2, 3, 4, 5):
        if len(words) < window_size:
            continue
        max_start = min(len(words) - window_size, 4)
        for start in range(max_start + 1):
            candidates.append(" ".join(words[start : start + window_size]))

    for start in (0, 8, 16):
        if start < len(normalized):
            candidates.append(normalized[start : start + HEADLINE_MAX_CHARS + 12])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def normalize_source_text(text: str) -> str:
    normalized = " ".join(str(text or "").replace("\u3000", " ").split())
    return normalized.strip()


def cleanup_headline_candidate(text: str) -> str:
    cleaned = sanitize_headline(text)
    cleaned = strip_stream_title(cleaned)
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = FILLER_PREFIX_RE.sub("", cleaned).strip()
        cleaned = sanitize_headline(cleaned)
    cleaned = collapse_japanese_spacing(cleaned)
    cleaned = re.sub(r"\b(?:w{2,}|www)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = sanitize_headline(cleaned)
    if not cleaned:
        return ""
    if WEAK_HEADLINE_RE.fullmatch(cleaned):
        return ""
    if len(JAPANESE_CHAR_RE.findall(cleaned)) < 2:
        return ""
    return cleaned


def strip_stream_title(text: str) -> str:
    value = sanitize_headline(text)
    if not value:
        return ""
    value = re.sub(r"^[\[\(\{\u3010].*?[\]\)\}\u3011]\s*", "", value)
    value = re.sub(r"\s*[|/].*$", "", value)
    return value.strip()


def collapse_japanese_spacing(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    compact = re.sub(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])", "", compact)
    compact = re.sub(r"\s+(?=[\u3001\u3002\uff01\uff1f])", "", compact)
    compact = re.sub(r"(?<=[\u3001\u3002\uff01\uff1f])\s+", "", compact)
    return compact.strip()


def score_headline_candidate(text: str) -> float:
    length = len(text)
    if length == 0:
        return float("-inf")

    score = 0.0
    if 10 <= length <= HEADLINE_MAX_CHARS:
        score += 8.0
    elif 6 <= length < 10:
        score += 5.0
    elif length > HEADLINE_MAX_CHARS:
        score += max(0.0, 6.0 - (length - HEADLINE_MAX_CHARS) * 0.35)
    else:
        score += length * 0.35

    score += len(re.findall(r"[\u4e00-\u9fff]", text)) * 0.35
    score += len(re.findall(r"[\u3040-\u30ff]", text)) * 0.12
    score -= text.count(" ") * 0.75

    phrase_count = len([part for part in text.split(" ") if part.strip()])
    if phrase_count > 2:
        score -= (phrase_count - 2) * 1.8

    if HEADLINE_KEYWORD_RE.search(text):
        score += 2.5
    if re.search(r"\d", text):
        score += 0.6
    if re.search(r"[\u300c\u300d\u300e\u300f]", text):
        score += 0.5
    if HEADLINE_META_RE.search(text):
        score -= 4.0
    if HEADLINE_SENSITIVE_RE.search(text):
        score -= 10.0
    return score


def finalize_headline(text: str) -> str:
    headline = collapse_japanese_spacing(text)
    headline = sanitize_headline(headline)
    if len(headline) > HEADLINE_MAX_CHARS:
        headline = smart_truncate(headline, HEADLINE_MAX_CHARS)
    headline = sanitize_headline(headline)
    return headline or DEFAULT_HEADLINE_TEXT


def smart_truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    best = text[:limit]
    for separator in (" ", "\u3001", "\u30fb", "/"):
        index = text.rfind(separator, 0, limit + 1)
        if index >= max(6, limit // 2):
            best = text[:index]
            break
    return best.rstrip(" ,.!?\u3001\u3002\u30fb\uff01\uff1f")


def sanitize_headline(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = text.strip().strip("\"'`")
    text = text.strip("[](){}<>")
    text = text.strip("\u300c\u300d\u300e\u300f\u3010\u3011\u201c\u201d\u2018\u2019")
    for prefix in ("Subheading:", "Headline:", "Title:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = re.sub(r"^[\-:;,.!?/\u3001\u3002\uff01\uff1f\s]+", "", text)
    text = re.sub(r"[\-:;,.!?/\u3001\u3002\uff01\uff1f\s]+$", "", text)
    if len(text) > HEADLINE_MAX_CHARS:
        text = text[:HEADLINE_MAX_CHARS].rstrip(" ,.!?\u3001\u3002\u30fb\uff01\uff1f")
    return text.strip()


def is_acceptable_headline(text: str) -> bool:
    validation = validate_headline_result(text, transcript=text)
    return validation.accepted

def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
