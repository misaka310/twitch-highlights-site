from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


def load_processed_videos(cache_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(cache_path.read_text(encoding="utf-8-sig"))
    videos = payload.get("videos") or []
    return [video for video in videos if isinstance(video, dict)]


def apply_transcript_result(
    item: dict[str, Any],
    target: Any,
    result: Any,
    *,
    transcript_model: str,
    now_iso: Callable[[], str],
) -> None:
    item["transcript"] = result.text
    item["transcript_source"] = "faster-whisper"
    item["transcript_model"] = str(item.get("_active_transcript_model") or transcript_model)
    item["transcript_status"] = "ok" if result.text else "empty"
    item["transcript_language"] = result.language
    item["transcript_generated_at"] = now_iso()
    item["transcript_window_start_sec"] = target.start_sec
    item["transcript_window_end_sec"] = target.end_sec
    if result.language_probability is not None:
        item["transcript_language_probability"] = round(result.language_probability, 4)
    else:
        item.pop("transcript_language_probability", None)
    if result.source_text:
        item["transcript_source_text"] = result.source_text
    else:
        item.pop("transcript_source_text", None)
    if result.segments:
        item["transcript_has_word_timestamps"] = bool(any(segment.get("words") for segment in result.segments))
        save_segments = _resolve_bool_env("TRANSCRIPT_SAVE_SEGMENTS", True)
        if save_segments:
            save_words = _resolve_bool_env("TRANSCRIPT_SAVE_WORDS", False)
            existing_segments = item.get("transcript_segments")
            transcript_segments = _normalize_transcript_segments(
                result.segments,
                transcript_window_start_sec=target.start_sec,
                transcript_window_end_sec=target.end_sec,
                save_words=save_words,
            )
            if transcript_segments:
                item["transcript_segments"] = transcript_segments
                item["transcript_alignment_source"] = "faster-whisper"
                item["transcript_alignment_saved_at"] = now_iso()
                item["transcript_alignment_status"] = "ready"
            elif isinstance(existing_segments, list) and existing_segments:
                item["transcript_alignment_status"] = "ready"
            else:
                item.pop("transcript_segments", None)
                item.pop("transcript_alignment_source", None)
                item.pop("transcript_alignment_saved_at", None)
                item["transcript_alignment_status"] = "missing_segments"
        else:
            item.pop("transcript_segments", None)
            item.pop("transcript_alignment_source", None)
            item.pop("transcript_alignment_saved_at", None)
            item["transcript_alignment_status"] = "disabled"
    else:
        item.pop("transcript_has_word_timestamps", None)
        existing_segments = item.get("transcript_segments")
        if isinstance(existing_segments, list) and existing_segments:
            item["transcript_alignment_status"] = "ready"
        else:
            item.pop("transcript_segments", None)
            item.pop("transcript_alignment_source", None)
            item.pop("transcript_alignment_saved_at", None)
            item.pop("transcript_alignment_status", None)
    item.pop("transcript_error", None)


def clear_transcript_artifacts(item: dict[str, Any]) -> list[str]:
    return clear_keys(
        item,
        (
            "transcript",
            "transcript_source",
            "transcript_model",
            "transcript_language",
            "transcript_language_probability",
            "transcript_source_text",
            "transcript_has_word_timestamps",
            "transcript_pass",
            "transcript_window_start_sec",
            "transcript_window_end_sec",
            "transcript_segments",
            "transcript_alignment_source",
            "transcript_alignment_saved_at",
            "transcript_alignment_status",
        ),
    )


def clear_headline_artifacts(item: dict[str, Any]) -> list[str]:
    return clear_keys(
        item,
        (
            "headline",
            "headline_source",
            "headline_model",
            "headline_source_text",
            "headline_source_validation",
            "headline_generation_mode",
            "headline_confidence",
            "headline_quality_penalty",
        ),
    )


def clear_keys(item: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    removed: list[str] = []
    for key in keys:
        if key in item:
            removed.append(key)
            item.pop(key, None)
    return removed


def log_item_snapshot(stage: str, label: str, item: dict[str, Any]) -> None:
    print(
        "debug: item state "
        f"stage={stage} label={label} transcript_status={item.get('transcript_status', 'none')} "
        f"headline_status={item.get('headline_status', 'none')} "
        f"has_transcript={bool(str(item.get('transcript') or '').strip())} "
        f"has_headline_source={bool(str(item.get('headline_source_text') or '').strip())} "
        f"has_headline={bool(str(item.get('headline') or '').strip())}"
    )


def _resolve_bool_env(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _to_optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _round_alignment_sec(value: float) -> int | float:
    rounded = round(float(value), 1)
    if float(rounded).is_integer():
        return int(rounded)
    return float(rounded)


def _normalize_transcript_segments(
    segments: list[dict[str, Any]],
    *,
    transcript_window_start_sec: Any,
    transcript_window_end_sec: Any,
    save_words: bool,
) -> list[dict[str, Any]]:
    window_start_sec = _to_optional_float(transcript_window_start_sec) or 0.0
    window_end_sec = _to_optional_float(transcript_window_end_sec)
    normalized_segments: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start_sec = _to_optional_float(segment.get("start"))
        end_sec = _to_optional_float(segment.get("end"))
        if start_sec is None or end_sec is None:
            continue
        if end_sec <= start_sec:
            continue

        absolute_start_sec = window_start_sec + float(start_sec)
        absolute_end_sec = window_start_sec + float(end_sec)
        if window_end_sec is not None:
            absolute_start_sec = max(window_start_sec, min(absolute_start_sec, window_end_sec))
            absolute_end_sec = max(window_start_sec, min(absolute_end_sec, window_end_sec))
        if absolute_end_sec <= absolute_start_sec:
            continue
        segment_row: dict[str, Any] = {
            "start_sec": _round_alignment_sec(absolute_start_sec),
            "end_sec": _round_alignment_sec(absolute_end_sec),
            "text": text,
        }
        if save_words:
            words_rows = _normalize_transcript_words(
                segment.get("words"),
                transcript_window_start_sec=window_start_sec,
                transcript_window_end_sec=window_end_sec,
            )
            if words_rows:
                segment_row["words"] = words_rows
        normalized_segments.append(segment_row)
    return sorted(normalized_segments, key=lambda row: float(_to_optional_float(row.get("start_sec")) or 0.0))


def _normalize_transcript_words(
    words: Any,
    *,
    transcript_window_start_sec: float,
    transcript_window_end_sec: float | None,
) -> list[dict[str, Any]]:
    if not isinstance(words, list):
        return []
    normalized_words: list[dict[str, Any]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        value = str(word.get("word") or "").strip()
        if not value:
            continue
        start_sec = _to_optional_float(word.get("start"))
        end_sec = _to_optional_float(word.get("end"))
        if start_sec is None or end_sec is None:
            continue
        if end_sec <= start_sec:
            continue
        absolute_start_sec = transcript_window_start_sec + float(start_sec)
        absolute_end_sec = transcript_window_start_sec + float(end_sec)
        if transcript_window_end_sec is not None:
            absolute_start_sec = max(transcript_window_start_sec, min(absolute_start_sec, transcript_window_end_sec))
            absolute_end_sec = max(transcript_window_start_sec, min(absolute_end_sec, transcript_window_end_sec))
        if absolute_end_sec <= absolute_start_sec:
            continue
        row: dict[str, Any] = {
            "word": value,
            "start_sec": _round_alignment_sec(absolute_start_sec),
            "end_sec": _round_alignment_sec(absolute_end_sec),
        }
        probability = _to_optional_float(word.get("probability"))
        if probability is not None:
            row["probability"] = round(probability, 4)
        normalized_words.append(row)
    return normalized_words
