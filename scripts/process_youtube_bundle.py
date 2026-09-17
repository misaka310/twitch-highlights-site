"""Process an Oracle YouTube material bundle on GitHub Actions.

This entrypoint has no YouTube network client.  It accepts only the validated
manifest and the selected clips supplied by Oracle, then reuses the existing
highlight/output pipeline and runs Whisper locally in Actions.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from transcribe_segments import build_segment_screenshot_file_path, build_segment_screenshot_public_path
from update_vods import (
    DATA_DIR,
    OUT_PATH,
    analyze_video_entry,
    load_processed_cache,
    write_processed_cache,
    write_public_data,
)
from vod_sources import ChatFetchResult
from youtube_enrichment import enrich_youtube_video
from youtube_handoff import extract_material_bundle


def _interval_key(start_sec: Any, end_sec: Any) -> tuple[int, int]:
    return int(start_sec), int(end_sec)


def process_bundle(bundle_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate, enrich, and publish one Oracle material bundle."""

    active_now = now or datetime.now().astimezone()
    with tempfile.TemporaryDirectory(prefix="youtube-material-", dir=DATA_DIR.parent) as temp_dir:
        root = Path(temp_dir)
        manifest = extract_material_bundle(Path(bundle_path), root)
        video = dict(manifest["video"])
        selected = list(manifest["selected_highlights"])
        offsets = [
            {"content_offset_seconds": float(item["content_offset_seconds"])}
            for item in manifest["chat_offsets"]
        ]
        chat = ChatFetchResult(comments=offsets, duration_sec=video.get("duration_sec"))

        analyzed, status = analyze_video_entry(
            video,
            active_now,
            chat_data_override=chat,
            metadata_override=video,
        )
        if not analyzed or status != "analyzed":
            raise RuntimeError("Oracle material did not produce publishable highlights")

        selected_intervals = {_interval_key(item["start_sec"], item["end_sec"]) for item in selected}
        analyzed_intervals = {
            _interval_key(item["start_sec"], item["end_sec"])
            for item in analyzed.get("items") or []
        }
        if selected_intervals != analyzed_intervals:
            raise RuntimeError("Oracle-selected intervals do not match the repository detector")

        item_by_interval = {
            _interval_key(item["start_sec"], item["end_sec"]): item
            for item in analyzed.get("items") or []
        }
        media_by_item_id: dict[str, dict[str, Path]] = {}
        for media in manifest["media"]:
            item_id = str(media["item_id"])
            item = item_by_interval.get(_interval_key(media["start_sec"], media["end_sec"]))
            if item is None:
                raise RuntimeError(f"missing selected interval for {item_id}")
            audio_path = root / media["audio_path"]
            screenshot_path = root / media["screenshot_path"]
            destination = build_segment_screenshot_file_path(video["vod_id"], item["id"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(screenshot_path, destination)
            item["screenshot_url"] = build_segment_screenshot_public_path(video["vod_id"], item["id"])
            media_by_item_id[item_id] = {"audio": audio_path, "screenshot": screenshot_path}

        def media_fetcher(_vod_url: str, start_sec: int, end_sec: int, _work_dir: Path) -> Path:
            item = item_by_interval.get((int(start_sec), int(end_sec)))
            if item is None or item["id"] not in media_by_item_id:
                raise RuntimeError("requested bundle interval is not present")
            return media_by_item_id[item["id"]]["audio"]

        enriched, summary = enrich_youtube_video(analyzed, media_fetcher=media_fetcher)
        cache_payload = load_processed_cache()
        cached_by_vod_id = {
            item["vod_id"]: item
            for item in cache_payload.get("videos", [])
            if item.get("vod_id")
        }
        cached_by_vod_id[enriched["vod_id"]] = enriched
        write_processed_cache(cached_by_vod_id.values(), active_now)
        write_public_data(cached_by_vod_id.values(), active_now)
        result = {
            "vod_id": enriched["vod_id"],
            "chat_total": enriched["chat_total"],
            "highlights": len(enriched.get("items") or []),
            "transcribed": getattr(summary, "transcribed", 0),
            "headlines": getattr(summary, "headlines", 0),
            "screenshots": len(manifest["media"]),
            "output": str(OUT_PATH),
        }
        print(
            "youtube bundle processed:"
            f" vod_id={result['vod_id']}"
            f" oracle_offsets={result['chat_total']}"
            f" highlights={result['highlights']}"
            f" transcribed={result['transcribed']}"
            f" headlines={result['headlines']}"
            f" screenshots={result['screenshots']}"
        )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a safe Oracle YouTube material bundle.")
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    process_bundle(args.bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
