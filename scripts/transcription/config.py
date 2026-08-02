from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _source(mapping: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if mapping is None else mapping


def env_flag(name: str, default: str = "0", *, mapping: Mapping[str, str] | None = None) -> bool:
    return str(_source(mapping).get(name, default)).strip().lower() in _TRUE_VALUES


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    mapping: Mapping[str, str] | None = None,
) -> int:
    try:
        value = int(str(_source(mapping).get(name, default)).strip())
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    mapping: Mapping[str, str] | None = None,
) -> float:
    try:
        value = float(str(_source(mapping).get(name, default)).strip())
    except (TypeError, ValueError):
        value = float(default)
    if minimum is not None:
        value = max(float(minimum), value)
    if maximum is not None:
        value = min(float(maximum), value)
    return value


def env_text(name: str, default: str = "", *, mapping: Mapping[str, str] | None = None) -> str:
    return str(_source(mapping).get(name, default) or default).strip()


@dataclass(frozen=True)
class PipelineSettings:
    TRANSCRIPT_MODEL: str
    TRANSCRIPT_COMPUTE_TYPE: str
    TRANSCRIPT_DEVICE: str
    TRANSCRIPT_MAX_SEGMENTS: int
    TRANSCRIPT_PADDING_SEC: int
    TRANSCRIPT_MAX_DURATION_SEC: int
    TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC: int
    TRANSCRIPT_TARGET_SCOPE: str
    TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS: int
    SEGMENT_SCREENSHOT_GENERATION_ENABLED: bool
    TRANSCRIPT_DRY_RUN: bool
    TRANSCRIPT_RETRY_ERRORS: bool
    HEADLINE_RETRY_ERRORS: bool
    FORCE_TRANSCRIPT_REFRESH: bool
    FORCE_HEADLINE_REFRESH: bool
    TRANSCRIPT_PREPROCESS_PROFILE: str
    TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH: str
    TRANSCRIPT_BEAM_SIZE: int
    TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT: bool
    TRANSCRIPT_VAD_FILTER: bool
    TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS: int | None
    TRANSCRIPT_SECOND_PASS_ENABLED: bool
    TRANSCRIPT_SECOND_PASS_MODEL: str
    TRANSCRIPT_SECOND_PASS_SELECTION_MODE: str
    TRANSCRIPT_SECOND_PASS_TOP_N: int
    TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC: int
    TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS: bool
    TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE: str
    TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD: int
    TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD: float
    TERM_DICTIONARY_PATH: str
    GAME_TERM_DICTIONARY_PATH: str
    TERM_NORMALIZATION_ENABLED: bool
    USE_GAME_TERM_DICTIONARY_DEFAULT: bool
    TERM_NORMALIZATION_SIMILARITY: int
    TERM_NORMALIZATION_MIN_TOKEN_LEN: int
    TERM_NORMALIZATION_MIN_TERM_LEN: int
    SOURCE_SENTENCE_LIMIT_DEFAULT: int
    PRINT_SOURCE_SELECTION_DEFAULT: bool
    GEMINI_API_KEY: str
    GEMINI_MODEL: str
    GEMINI_API_URL: str
    GEMINI_TIMEOUT_SEC: int
    GROQ_API_KEY: str
    GROQ_MODEL: str
    GROQ_RESPONSES_URL: str
    GROQ_TIMEOUT_SEC: int
    NVIDIA_API_KEY: str
    NVIDIA_MODEL: str
    NVIDIA_API_URL: str
    NVIDIA_TIMEOUT_SEC: int
    HEADLINE_MAX_CHARS: int
    HEADLINE_MAX_ATTEMPTS: int
    HEADLINE_STREAMER_ID: str | None

    @classmethod
    def from_env(cls, mapping: Mapping[str, str] | None = None) -> "PipelineSettings":
        source = _source(mapping)
        model = env_text("TRANSCRIPT_MODEL", "small", mapping=source)
        preprocess = env_text("TRANSCRIPT_PREPROCESS_PROFILE", "light", mapping=source).lower()
        screenshot_raw = env_text("SEGMENT_SCREENSHOT_GENERATION_ENABLED", "", mapping=source).lower()
        screenshot_enabled = (
            screenshot_raw in _TRUE_VALUES
            if screenshot_raw
            else not env_flag("CI", "0", mapping=source)
        )
        silence_raw = env_text("TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS", "", mapping=source)
        try:
            silence = max(0, int(silence_raw)) if silence_raw else None
        except ValueError:
            silence = None
        streamer_id = env_text("HEADLINE_STREAMER_ID", "", mapping=source) or None
        return cls(
            TRANSCRIPT_MODEL=model,
            TRANSCRIPT_COMPUTE_TYPE=env_text("TRANSCRIPT_COMPUTE_TYPE", "int8", mapping=source),
            TRANSCRIPT_DEVICE=env_text("TRANSCRIPT_DEVICE", "cpu", mapping=source),
            TRANSCRIPT_MAX_SEGMENTS=env_int("TRANSCRIPT_MAX_SEGMENTS", 9, minimum=1, mapping=source),
            TRANSCRIPT_PADDING_SEC=env_int("TRANSCRIPT_PADDING_SEC", 15, minimum=0, mapping=source),
            TRANSCRIPT_MAX_DURATION_SEC=env_int("TRANSCRIPT_MAX_DURATION_SEC", 150, minimum=30, mapping=source),
            TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC=env_int("TRANSCRIPT_DOWNLOAD_TIMEOUT_SEC", 180, minimum=30, mapping=source),
            TRANSCRIPT_TARGET_SCOPE=env_text("TRANSCRIPT_TARGET_SCOPE", "recent_public", mapping=source).lower(),
            TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS=env_int("TRANSCRIPT_RECENT_ANALYZED_WINDOW_HOURS", 36, minimum=1, mapping=source),
            SEGMENT_SCREENSHOT_GENERATION_ENABLED=screenshot_enabled,
            TRANSCRIPT_DRY_RUN=env_flag("TRANSCRIPT_DRY_RUN", "0", mapping=source),
            TRANSCRIPT_RETRY_ERRORS=env_flag("TRANSCRIPT_RETRY_ERRORS", "0", mapping=source),
            HEADLINE_RETRY_ERRORS=env_flag("HEADLINE_RETRY_ERRORS", "1", mapping=source),
            FORCE_TRANSCRIPT_REFRESH=env_flag("FORCE_TRANSCRIPT_REFRESH", "0", mapping=source),
            FORCE_HEADLINE_REFRESH=env_flag("FORCE_HEADLINE_REFRESH", "0", mapping=source),
            TRANSCRIPT_PREPROCESS_PROFILE=preprocess,
            TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH=env_text("TRANSCRIPT_PREPROCESS_DENOISE_STRENGTH", "-25", mapping=source),
            TRANSCRIPT_BEAM_SIZE=env_int("TRANSCRIPT_BEAM_SIZE", 1, minimum=1, mapping=source),
            TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT=env_flag("TRANSCRIPT_CONDITION_ON_PREVIOUS_TEXT", "0", mapping=source),
            TRANSCRIPT_VAD_FILTER=env_flag("TRANSCRIPT_VAD_FILTER", "1", mapping=source),
            TRANSCRIPT_VAD_MIN_SILENCE_DURATION_MS=silence,
            TRANSCRIPT_SECOND_PASS_ENABLED=env_flag("TRANSCRIPT_SECOND_PASS_ENABLED", "1", mapping=source),
            TRANSCRIPT_SECOND_PASS_MODEL=env_text("TRANSCRIPT_SECOND_PASS_MODEL", model, mapping=source),
            TRANSCRIPT_SECOND_PASS_SELECTION_MODE=env_text("TRANSCRIPT_SECOND_PASS_SELECTION_MODE", "hybrid", mapping=source).lower(),
            TRANSCRIPT_SECOND_PASS_TOP_N=env_int("TRANSCRIPT_SECOND_PASS_TOP_N", 2, minimum=0, mapping=source),
            TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC=env_int("TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC", 3, minimum=0, mapping=source),
            TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS=env_flag("TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS", "1", mapping=source),
            TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE=env_text("TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE", preprocess, mapping=source).lower(),
            TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD=env_int("TRANSCRIPT_LOW_INFO_TOKEN_THRESHOLD", 6, minimum=1, mapping=source),
            TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD=env_float("TRANSCRIPT_SUSPICIOUS_RATIO_THRESHOLD", 0.2, minimum=0.0, maximum=1.0, mapping=source),
            TERM_DICTIONARY_PATH=env_text("TERM_DICTIONARY_PATH", str(Path("data") / "term_dictionary.json"), mapping=source),
            GAME_TERM_DICTIONARY_PATH=env_text("GAME_TERM_DICTIONARY_PATH", str(Path("data") / "game_term_dictionary.json"), mapping=source),
            TERM_NORMALIZATION_ENABLED=env_flag("TERM_NORMALIZATION_ENABLED", "1", mapping=source),
            USE_GAME_TERM_DICTIONARY_DEFAULT=env_flag("USE_GAME_TERM_DICTIONARY", "1", mapping=source),
            TERM_NORMALIZATION_SIMILARITY=env_int("TERM_NORMALIZATION_SIMILARITY", 88, minimum=0, maximum=100, mapping=source),
            TERM_NORMALIZATION_MIN_TOKEN_LEN=env_int("TERM_NORMALIZATION_MIN_TOKEN_LEN", 3, minimum=2, mapping=source),
            TERM_NORMALIZATION_MIN_TERM_LEN=env_int("TERM_NORMALIZATION_MIN_TERM_LEN", 3, minimum=2, mapping=source),
            SOURCE_SENTENCE_LIMIT_DEFAULT=env_int("SOURCE_SENTENCE_LIMIT", 2, minimum=1, maximum=2, mapping=source),
            PRINT_SOURCE_SELECTION_DEFAULT=env_flag("PRINT_SOURCE_SELECTION", "0", mapping=source),
            GEMINI_API_KEY=env_text("GEMINI_API_KEY", "", mapping=source),
            GEMINI_MODEL=env_text("GEMINI_MODEL", "gemini-2.5-flash", mapping=source),
            GEMINI_API_URL=env_text(
                "GEMINI_API_URL",
                "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                mapping=source,
            ),
            GEMINI_TIMEOUT_SEC=env_int("GEMINI_TIMEOUT_SEC", 45, minimum=10, mapping=source),
            GROQ_API_KEY=env_text("GROQ_API_KEY", "", mapping=source),
            GROQ_MODEL=env_text("GROQ_MODEL", "", mapping=source),
            GROQ_RESPONSES_URL=env_text(
                "GROQ_RESPONSES_URL",
                "https://api.groq.com/openai/v1/responses",
                mapping=source,
            ),
            GROQ_TIMEOUT_SEC=env_int("GROQ_TIMEOUT_SEC", 45, minimum=10, mapping=source),
            NVIDIA_API_KEY=env_text("NVIDIA_API_KEY", "", mapping=source),
            NVIDIA_MODEL=env_text(
                "NVIDIA_MODEL",
                "mistralai/mistral-large-3-675b-instruct-2512",
                mapping=source,
            ),
            NVIDIA_API_URL=env_text(
                "NVIDIA_API_URL",
                "https://integrate.api.nvidia.com/v1/chat/completions",
                mapping=source,
            ),
            NVIDIA_TIMEOUT_SEC=env_int("NVIDIA_TIMEOUT_SEC", 45, minimum=10, mapping=source),
            HEADLINE_MAX_CHARS=env_int("HEADLINE_MAX_CHARS", 28, minimum=12, mapping=source),
            HEADLINE_MAX_ATTEMPTS=env_int("HEADLINE_MAX_ATTEMPTS", 2, minimum=1, mapping=source),
            HEADLINE_STREAMER_ID=streamer_id,
        )

    def as_globals(self) -> dict[str, object]:
        return {field.name: getattr(self, field.name) for field in fields(self)}
