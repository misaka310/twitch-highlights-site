from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def parse_timezone_aware_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def collect_recently_analyzed_vod_ids(
    videos: list[dict[str, Any]],
    *,
    now: datetime,
    window_hours: int,
) -> list[str]:
    cutoff = now - timedelta(hours=max(1, int(window_hours)))
    recent_vod_ids: list[str] = []
    for video in videos:
        vod_id = str(video.get("vod_id") or "").strip()
        if not vod_id:
            continue
        analyzed_at = parse_timezone_aware_iso_datetime(video.get("analyzed_at"))
        if analyzed_at is not None and analyzed_at >= cutoff:
            recent_vod_ids.append(vod_id)
    return recent_vod_ids


def dedupe_preserving_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped

