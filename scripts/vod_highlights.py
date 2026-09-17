from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from statistics import mean
from typing import Any

from project_config import load_project_config


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
PROJECT_CONFIG = load_project_config(env={})

SEGMENT_THUMBNAILS_DIR = DATA_DIR / "segment-thumbnails"


BASE_TAG_RULES = (
    ("ww", (r"w{2,}", r"ｗ{2,}", r"草", r"笑", r"爆笑")),
    ("ホラー", (r"こわ", r"怖", r"やだ", r"うわ", r"ぎゃ", r"助けて", r"無理", r"ひぃ")),
    ("好プレー", (r"すご", r"うま", r"天才", r"神", r"ないす", r"ナイス", r"つよ", r"勝")),
    ("えっ", (r"えっ", r"まじ", r"やば", r"なんで")),
    ("えっど", (r"えっろ", r"えっど", r"えろ", r"エロ", r"めろい")),
    ("まずい", (r"まずい",)),
    ("おめ", (r"おめ", r"おめでとう", r"おめでと", r"祝", r"888+", r"８８８+")),
)


TAG_RULES = BASE_TAG_RULES + PROJECT_CONFIG.extra_tag_rules


CLOSING_CHATTER_PATTERNS = (
    r"おつ",
    r"お疲れ",
    r"おつかれ",
    r"おやすみ",
    r"またね",
    r"ばいばい",
    r"バイバイ",
    r"ありがとう",
    r"ありがと",
    r"終わり",
    r"終了",
    r"落ちる",
    r"落ちます",
    r"寝る",
    r"ねます",
    r"離脱",
)


CLOSING_CHATTER_REGEX = re.compile(
    "|".join(sorted(CLOSING_CHATTER_PATTERNS, key=len, reverse=True)),
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class DetectConfig:
    bucket_sec: int = 10
    z_thresh: float = 2.5
    pad_before: int = 20
    pad_after: int = 20
    merge_gap_sec: int = 15
    max_candidates: int = 3
    min_spacing_sec: int = 10 * 60
    sustained_bonus_per_bucket: float = 0.35
    exclude_last_sec: int = 60
    closing_penalty_start_ratio: float = 0.88
    closing_penalty_max: float = 2.5
    closing_window_pad_before: int = 15
    closing_window_pad_after: int = 15


def detect_items(
    comments: list[dict[str, Any]],
    vod_id: str,
    cfg: DetectConfig,
    *,
    total_duration_sec: int | None = None,
) -> list[dict[str, Any]]:
    times = []
    for item in comments:
        try:
            times.append(float(item.get("content_offset_seconds")))
        except Exception:
            continue

    if not times:
        return []

    counts, max_t = bucket_counts(times, cfg.bucket_sec)
    resolved_total_duration_sec = max(float(max_t), float(total_duration_sec or 0))
    zs = z_scores(counts)
    raw_segments = merge_hot_buckets(zs, cfg)
    filtered_segments = [
        seg
        for seg in raw_segments
        if not is_segment_in_last_seconds_window(seg.get("end", 0.0), resolved_total_duration_sec, cfg.exclude_last_sec)
    ]
    ranked_segments = rank_segments(
        filtered_segments,
        cfg,
        comments=comments,
        total_duration_sec=resolved_total_duration_sec,
    )
    sorted_segments = select_diverse_segments(ranked_segments, cfg)[: cfg.max_candidates]

    items: list[dict[str, Any]] = []
    for rank, seg in enumerate(sorted_segments, 1):
        start_sec = int(seg["start"])
        end_sec = int(seg["end"])
        score = round(float(seg.get("score", 0.0)), 3)
        segment_id = f"{vod_id}_{start_sec}_{end_sec}"
        items.append(
            {
                "rank": rank,
                "id": segment_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": max(0, end_sec - start_sec),
                "start_time": format_hhmmss(start_sec),
                "end_time": format_hhmmss(end_sec),
                "score": score,
                "reason": f"Chat activity spike around {sec_to_twitch_timestamp(start_sec)} (z-score={score}).",
                "tags": classify_segment_tags(comments, start_sec, end_sec),
                "watch_url": build_watch_url(vod_id, start_sec),
                "screenshot_url": build_segment_screenshot_public_path(vod_id, segment_id),
            }
        )

    return items


def fallback_items(vod_id: str) -> list[dict[str, Any]]:
    defaults = [(1520, 1570), (3760, 3820), (5110, 5180)]
    items = []
    for rank, (start_sec, end_sec) in enumerate(defaults, 1):
        segment_id = f"{vod_id}_{start_sec}_{end_sec}"
        items.append(
            {
                "rank": rank,
                "id": segment_id,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": max(0, end_sec - start_sec),
                "start_time": format_hhmmss(start_sec),
                "end_time": format_hhmmss(end_sec),
                "score": 0.0,
                "reason": f"Chat activity spike around {sec_to_twitch_timestamp(start_sec)} (z-score=0.0).",
                "tags": [],
                "watch_url": build_watch_url(vod_id, start_sec),
                "screenshot_url": build_segment_screenshot_public_path(vod_id, segment_id),
            }
        )
    return items


def bucket_counts(times: list[float], bucket_sec: int) -> tuple[list[int], float]:
    max_t = max(times)
    n = int(math.ceil(max_t / bucket_sec)) + 1
    counts = [0] * n
    for t in times:
        idx = int(t // bucket_sec)
        if 0 <= idx < n:
            counts[idx] += 1
    return counts, max_t


def build_activity_map(comments: list[dict[str, Any]], cfg: DetectConfig, duration_sec: int | None = None) -> dict[str, Any]:
    times: list[float] = []
    for item in comments:
        try:
            times.append(float(item.get("content_offset_seconds")))
        except Exception:
            continue

    if not times:
        return {"bucket_sec": cfg.bucket_sec, "duration_sec": 0, "last_comment_sec": 0, "peak_count": 0, "buckets": []}

    counts, max_t = bucket_counts(times, cfg.bucket_sec)
    resolved_duration = int(math.ceil(max(duration_sec or 0, max_t)))
    target_bucket_count = max(len(counts), int(math.ceil(resolved_duration / cfg.bucket_sec)) + 1)
    if len(counts) < target_bucket_count:
        counts.extend([0] * (target_bucket_count - len(counts)))
    return {
        "bucket_sec": cfg.bucket_sec,
        "duration_sec": resolved_duration,
        "last_comment_sec": int(math.ceil(max_t)),
        "peak_count": max(counts) if counts else 0,
        "buckets": counts,
    }


def normalize_activity_map(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"bucket_sec": 10, "duration_sec": 0, "last_comment_sec": 0, "peak_count": 0, "buckets": []}

    raw_buckets = value.get("buckets")
    buckets = [int(item) for item in raw_buckets if isinstance(item, (int, float))] if isinstance(raw_buckets, list) else []
    bucket_sec = parse_int(value.get("bucket_sec"))
    duration_sec = parse_int(value.get("duration_sec"))
    last_comment_sec = parse_int(value.get("last_comment_sec"))
    peak_count = parse_int(value.get("peak_count"))
    resolved_bucket_sec = bucket_sec if bucket_sec and bucket_sec > 0 else 10
    fallback_last_comment = 0
    for index in range(len(buckets) - 1, -1, -1):
        if buckets[index] > 0:
            fallback_last_comment = (index + 1) * resolved_bucket_sec
            break
    return {
        "bucket_sec": resolved_bucket_sec,
        "duration_sec": duration_sec if duration_sec and duration_sec >= 0 else 0,
        "last_comment_sec": last_comment_sec if last_comment_sec and last_comment_sec >= 0 else fallback_last_comment,
        "peak_count": peak_count if peak_count and peak_count >= 0 else (max(buckets) if buckets else 0),
        "buckets": buckets,
    }


def z_scores(counts: list[int]) -> list[float]:
    if not counts:
        return []
    avg = mean(counts)
    var = mean([(c - avg) ** 2 for c in counts])
    sd = math.sqrt(var) if var > 1e-9 else 1.0
    return [(c - avg) / sd for c in counts]


def merge_hot_buckets(zs: list[float], cfg: DetectConfig) -> list[dict[str, float]]:
    hot = [i for i, z in enumerate(zs) if z >= cfg.z_thresh]
    if not hot:
        return []

    bands: list[tuple[int, int]] = []
    start = prev = hot[0]
    for idx in hot[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        bands.append((start, prev))
        start = prev = idx
    bands.append((start, prev))

    segments: list[dict[str, float]] = []
    for start_idx, end_idx in bands:
        segments.append(
            {
                "start": max(0.0, start_idx * cfg.bucket_sec - cfg.pad_before),
                "end": (end_idx + 1) * cfg.bucket_sec + cfg.pad_after,
                "score": round(max(zs[start_idx : end_idx + 1]), 3),
            }
        )
    return merge_overlapping_segments(segments, cfg.merge_gap_sec)


def merge_overlapping_segments(segments: list[dict[str, float]], gap_sec: int) -> list[dict[str, float]]:
    ordered = sorted(segments, key=lambda item: item["start"])
    merged = [ordered[0].copy()]
    for seg in ordered[1:]:
        current = merged[-1]
        if seg["start"] <= current["end"] + gap_sec:
            current["end"] = max(current["end"], seg["end"])
            current["score"] = max(current["score"], seg["score"])
        else:
            merged.append(seg.copy())
    return merged


def collect_nearby_comment_texts(
    comments: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
    pad_before: int,
    pad_after: int,
) -> list[str]:
    window_start = max(0.0, float(start_sec) - float(pad_before))
    window_end = float(end_sec) + float(pad_after)
    nearby_texts: list[str] = []
    for comment in comments:
        sec = comment.get("content_offset_seconds")
        if not isinstance(sec, (int, float)):
            continue
        if not (window_start <= float(sec) <= window_end):
            continue
        text = str(comment.get("message") or "").strip()
        if text:
            nearby_texts.append(text)
    return nearby_texts


def count_closing_chatter_hits(messages: list[str]) -> int:
    hits = 0
    for message in messages:
        hits += len(CLOSING_CHATTER_REGEX.findall(message))
    return hits


def calculate_closing_chatter_penalty(
    segment: dict[str, float],
    total_duration_sec: float,
    comments: list[dict[str, Any]],
    cfg: DetectConfig,
) -> float:
    safe_total_duration = max(float(cfg.bucket_sec), float(total_duration_sec))
    start_sec = float(segment.get("start", 0.0))
    end_sec = float(segment.get("end", 0.0))
    midpoint_ratio = ((start_sec + end_sec) / 2.0) / safe_total_duration
    if midpoint_ratio < cfg.closing_penalty_start_ratio:
        return 0.0

    nearby_messages = collect_nearby_comment_texts(
        comments,
        start_sec,
        end_sec,
        cfg.closing_window_pad_before,
        cfg.closing_window_pad_after,
    )
    closing_hits = count_closing_chatter_hits(nearby_messages)
    if closing_hits <= 0:
        return 0.0
    return min(cfg.closing_penalty_max, closing_hits * 0.6)


def is_segment_in_last_seconds_window(segment_end_sec: float, total_duration_sec: float, exclude_last_sec: int) -> bool:
    safe_total_duration = max(0.0, float(total_duration_sec))
    last_window_start = max(0.0, safe_total_duration - float(exclude_last_sec))
    return float(segment_end_sec) > last_window_start


def format_hhmmss(total_sec: int) -> str:
    sec = max(0, int(total_sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_segment_screenshot_public_path(vod_id: str, segment_id: str) -> str:
    return f"/data/segment-thumbnails/{vod_id}/{segment_id}.webp"


def build_segment_screenshot_file_path(vod_id: str, segment_id: str) -> Path:
    return SEGMENT_THUMBNAILS_DIR / vod_id / f"{segment_id}.webp"


def rank_segments(
    segments: list[dict[str, float]],
    cfg: DetectConfig,
    *,
    comments: list[dict[str, Any]],
    total_duration_sec: float,
) -> list[dict[str, float]]:
    ranked: list[dict[str, float]] = []
    safe_total_duration = max(float(cfg.bucket_sec), float(total_duration_sec))

    for seg in segments:
        start_sec = float(seg["start"])
        end_sec = float(seg["end"])
        duration_sec = max(0.0, end_sec - start_sec)
        covered_buckets = max(1.0, math.ceil(duration_sec / cfg.bucket_sec))
        sustained_bonus = max(0.0, covered_buckets - 1.0) * cfg.sustained_bonus_per_bucket
        closing_penalty = calculate_closing_chatter_penalty(seg, safe_total_duration, comments, cfg)

        nearby_messages = collect_nearby_comment_texts(
            comments,
            start_sec,
            end_sec,
            cfg.closing_window_pad_before,
            cfg.closing_window_pad_after,
        )
        closing_hits = count_closing_chatter_hits(nearby_messages)

        adjusted = float(seg.get("score", 0.0)) + sustained_bonus - closing_penalty
        ranked.append(
            {
                **seg,
                "duration_sec": duration_sec,
                "sustained_bonus": round(sustained_bonus, 3),
                "closing_penalty": round(closing_penalty, 3),
                "closing_hits": closing_hits,
                "adjusted_score": round(adjusted, 3),
            }
        )

    return sorted(
        ranked,
        key=lambda item: (
            item.get("adjusted_score", 0.0),
            item.get("score", 0.0),
            item.get("duration_sec", 0.0),
            item.get("start", 0.0),
        ),
        reverse=True,
    )


def select_diverse_segments(segments: list[dict[str, float]], cfg: DetectConfig) -> list[dict[str, float]]:
    selected: list[dict[str, float]] = []

    for seg in segments:
        midpoint_sec = (float(seg["start"]) + float(seg["end"])) / 2.0
        too_close = any(
            abs(midpoint_sec - ((float(picked["start"]) + float(picked["end"])) / 2.0)) < cfg.min_spacing_sec
            for picked in selected
        )
        if too_close:
            continue
        selected.append(seg)
        if len(selected) >= cfg.max_candidates:
            return selected

    return selected


def sec_to_twitch_timestamp(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}h{m}m{s}s"


def build_watch_url(vod_id: str, start_sec: int) -> str:
    return f"https://www.twitch.tv/videos/{vod_id}?t={sec_to_twitch_timestamp(start_sec)}"


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_twitch_duration_text(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    matches = re.findall(r"(\d+)([hms])", text)
    if not matches:
        return None
    total = 0
    for amount_text, unit in matches:
        amount = int(amount_text)
        if unit == "h":
            total += amount * 3600
        elif unit == "m":
            total += amount * 60
        elif unit == "s":
            total += amount
    return total if total > 0 else None


def clean_html_text(value: str) -> str:
    return html_unescape(re.sub(r"<.*?>", "", value)).strip()


def normalize_thumbnail_url(value: str) -> str:
    return value.replace("%{width}", "320").replace("%{height}", "180")


def html_unescape(value: str) -> str:
    return unescape(value or "").strip()


def extract_message_text(message: dict[str, Any]) -> str:
    fragments = message.get("fragments") or []
    parts: list[str] = []
    for fragment in fragments:
        text = fragment.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts).strip()


def classify_segment_tags(comments: list[dict[str, Any]], start_sec: int, end_sec: int) -> list[str]:
    window_start = max(0, start_sec - 15)
    window_end = end_sec + 15
    nearby_messages = []
    for comment in comments:
        sec = comment.get("content_offset_seconds")
        if not isinstance(sec, (int, float)):
            continue
        if window_start <= float(sec) <= window_end:
            text = str(comment.get("message") or "").strip()
            if text:
                nearby_messages.append(text)

    return classify_tags_from_texts(nearby_messages)


def classify_tags_from_texts(messages: list[str]) -> list[str]:
    if not messages:
        return []

    joined = "\n".join(messages)
    score_by_label: dict[str, int] = {}

    aa_hits = 0
    ha_hits = 0
    for message in messages:
        if re.fullmatch(r"[\u3042\u3041\u30A2]+[!\uFF01?\uFF1F\u30FC\uFF5E\u2026]*", message):
            aa_hits += 1
        normalized_message = str(message).strip()
        if normalized_message in {"\u306f", "?", "\uff1f", "\u306f\uff1f", "\uff1f\uff1f\uff1f\uff1f\uff1f\uff1f", "\u982d\u304a\u304b\u3057\u3044\u306e\u304b\uff1f", "444444"}:
            ha_hits += 1
    if aa_hits > 0:
        score_by_label["\u3042"] = aa_hits
    if ha_hits > 0:
        score_by_label["は"] = ha_hits

    for label, patterns in TAG_RULES:
        hits = 0
        for pattern in patterns:
            hits += len(re.findall(pattern, joined, flags=re.IGNORECASE))
        if hits > 0:
            score_by_label[label] = hits

    for label in ("えっど", "は"):
        if label in score_by_label and "えっ" in score_by_label:
            score_by_label["えっ"] = max(0, score_by_label["えっ"] - score_by_label[label])
            if score_by_label["えっ"] == 0:
                score_by_label.pop("えっ", None)

    scored_tags = sorted(score_by_label.items(), key=lambda item: (-item[1], item[0]))
    return [label for label, _ in scored_tags[:3]]


def to_local_iso(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone().isoformat(timespec="seconds")
