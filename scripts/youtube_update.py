from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from youtube_sources import YoutubeFetchResult, fetch_youtube_video


def run_youtube_mode(
    now: datetime,
    youtube_url: str,
    *,
    analyze_video_entry: Callable[..., tuple[dict[str, Any] | None, str]],
    load_processed_cache: Callable[[], dict[str, Any]],
    write_processed_cache: Callable[..., Any],
    write_public_data: Callable[..., Any],
    output_path: Path,
    fetch_video: Callable[[str], YoutubeFetchResult] = fetch_youtube_video,
) -> None:
    result = fetch_video(youtube_url)
    analyzed_video, status = analyze_video_entry(
        dict(result.video),
        now,
        chat_data_override=result.chat,
        metadata_override=result.video,
    )
    if not analyzed_video or status != "analyzed":
        raise RuntimeError(f"YouTube archive produced no publishable highlights: {youtube_url}")

    cache_payload = load_processed_cache()
    cached_by_vod_id = {
        item["vod_id"]: item
        for item in cache_payload.get("videos", [])
        if item.get("vod_id")
    }
    cached_by_vod_id[analyzed_video["vod_id"]] = analyzed_video
    write_processed_cache(cached_by_vod_id.values(), now)
    write_public_data(cached_by_vod_id.values(), now)
    print(
        "youtube mode:"
        f" vod_id={analyzed_video['vod_id']}"
        f" oracle_comments={analyzed_video['chat_total']}"
        f" highlights={len(analyzed_video.get('items') or [])}"
    )
    print(f"wrote {output_path}")
