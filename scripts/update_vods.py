from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from statistics import mean
from typing import Any, Iterable
from urllib import parse, request

from project_config import load_project_config

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_local_env(ENV_PATH)
PROJECT_CONFIG = load_project_config()

CHANNEL = PROJECT_CONFIG.twitch_channel_login
CHANNEL_URL = PROJECT_CONFIG.twitch_channel_url
TWITCHMETRICS_URL = PROJECT_CONFIG.twitchmetrics_url
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"
TWITCH_VIDEOS_URL = "https://api.twitch.tv/helix/videos"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
TWITCH_API_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_API_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
TWITCH_GQL_CLIENT_ID = os.environ.get(
    "TWITCH_GQL_CLIENT_ID",
    "kimne78kx3ncx6brgo4mv6wki5h1ko",
).strip()
USER_AGENT = "Mozilla/5.0"
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUT_PATH = DATA_DIR / "vods.json"
VOD_INDEX_PATH = DATA_DIR / "vod_index.json"
VOD_DETAILS_DIR = DATA_DIR / "vods"
CACHE_PATH = DATA_DIR / "processed_vods.json"
BACKFILL_SUMMARY_PATH = DATA_DIR / "backfill_summary.json"
SEGMENT_THUMBNAILS_DIR = DATA_DIR / "segment-thumbnails"
ANALYSIS_VERSION = "chat-zscore-v8"
UPDATE_HOUR_LOCAL = 9
JST_TIMEZONE = timezone(timedelta(hours=9))
PUBLIC_VIDEO_LIMIT = 3
PUBLIC_VOD_RETENTION_DAYS = 60
BACKFILL_DEFAULT_DAYS = 120
BACKFILL_SOURCE_LIMIT_MULTIPLIER = 3
BACKFILL_SOURCE_LIMIT_FLOOR = 30
TWITCH_LIVE_CHECK_ENABLED_DEFAULT = "1"
TWITCH_LIVE_CHECK_FAIL_OPEN_DEFAULT = "0"
PUBLIC_ITEM_FIELDS = (
    "rank",
    "id",
    "start_sec",
    "end_sec",
    "duration_sec",
    "start_time",
    "end_time",
    "reason",
    "headline",
    "tags",
    "watch_url",
    "screenshot_url",
)
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

COMPACT_ARRAY_PATHS = {("activity_map", "buckets")}
COMPACT_ARRAY_ITEMS_PER_LINE = 40
JSON_READ_ENCODING = "utf-8-sig"
JSON_WRITE_ENCODING = "utf-8"
@dataclass(frozen=True)
class FetchConfig:
    max_pages: int = 60
    timeout_sec: int = 20
    sleep_sec: float = 0.05


@dataclass(frozen=True)
class ChatFetchResult:
    comments: list[dict[str, Any]]
    duration_sec: int | None = None



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


@dataclass(frozen=True)
class CliArgs:
    backfill: bool
    backfill_days: int
    backfill_limit: int | None
    force_reanalyze: bool


@dataclass
class BackfillSummary:
    scanned: int = 0
    reused: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    reused_vod_ids: list[str] = field(default_factory=list)
    failed_vod_ids: list[str] = field(default_factory=list)
    analyzed_details: list[dict[str, int | str]] = field(default_factory=list)


def main() -> None:
    args = parse_cli_args()
    now = datetime.now().astimezone()
    if args.backfill:
        run_backfill_mode(now, args)
        return
    run_normal_mode(now)


def parse_cli_args() -> CliArgs:
    parser = argparse.ArgumentParser(description="Update Twitch highlight VOD cache and public JSON outputs.")
    parser.add_argument("--backfill", action="store_true", help="Enable local backfill mode.")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=BACKFILL_DEFAULT_DAYS,
        help=f"Backfill range in days (default: {BACKFILL_DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--backfill-limit",
        type=int,
        default=None,
        help="Optional max number of latest VODs to fetch for backfill.",
    )
    parser.add_argument(
        "--force-reanalyze",
        action="store_true",
        help="Force reanalysis for all scoped VODs (backfill mode only).",
    )
    parsed = parser.parse_args()
    if parsed.backfill_days <= 0:
        parser.error("--backfill-days must be a positive integer")
    if parsed.backfill_limit is not None and parsed.backfill_limit <= 0:
        parser.error("--backfill-limit must be a positive integer")
    if not parsed.backfill:
        if parsed.backfill_limit is not None:
            parser.error("--backfill-limit requires --backfill")
        if parsed.force_reanalyze:
            parser.error("--force-reanalyze requires --backfill")
        if parsed.backfill_days != BACKFILL_DEFAULT_DAYS:
            parser.error("--backfill-days requires --backfill")
    return CliArgs(
        backfill=parsed.backfill,
        backfill_days=parsed.backfill_days,
        backfill_limit=parsed.backfill_limit,
        force_reanalyze=parsed.force_reanalyze,
    )


def run_normal_mode(now: datetime) -> None:
    target_count = 3
    source_limit = max(target_count * 2, target_count + 2)
    videos = fetch_latest_videos(limit=source_limit)
    skip_latest_candidate, skip_reason = resolve_live_skip_decision(CHANNEL)
    skipped_latest_vod_id = ""
    if skip_latest_candidate:
        skipped_latest_vod_id = resolve_latest_vod_id(videos)
        if skipped_latest_vod_id:
            print(f"skip_live_candidate: vod_id={skipped_latest_vod_id} reason={skip_reason}")
            videos = [video for video in videos if str(video.get("vod_id") or "").strip() != skipped_latest_vod_id]

    cache_payload = load_processed_cache()
    cached_videos = [item for item in cache_payload.get("videos", []) if item.get("vod_id")]
    cached_by_vod_id = {
        item["vod_id"]: item
        for item in cached_videos
    }
    selected_videos: list[dict[str, Any]] = []

    selected_vod_ids: set[str] = set()
    for video in videos:
        if len(selected_videos) >= target_count:
            break
        resolved = resolve_video_entry(video, cached_by_vod_id, now)
        if not resolved:
            continue
        selected_videos.append(resolved)
        cached_by_vod_id[resolved["vod_id"]] = resolved
        selected_vod_ids.add(resolved["vod_id"])

    if len(selected_videos) < target_count:
        for cached in cached_videos:
            cached_vod_id = str(cached.get("vod_id") or "").strip()
            if not cached_vod_id or cached_vod_id in selected_vod_ids:
                continue
            selected_videos.append(cached)
            selected_vod_ids.add(cached_vod_id)
            print(f"fallback {cached_vod_id}")
            if len(selected_videos) >= target_count:
                break

    if not selected_videos:
        raise RuntimeError("No valid videos available; refusing to overwrite data files")

    write_processed_cache(cached_by_vod_id.values(), now)
    write_public_data(cached_by_vod_id.values(), now)
    print(f"wrote {OUT_PATH}")


def run_backfill_mode(now: datetime, args: CliArgs) -> None:
    cache_payload = load_processed_cache()
    cached_videos = [item for item in cache_payload.get("videos", []) if item.get("vod_id")]
    cached_by_vod_id = {item["vod_id"]: item for item in cached_videos}

    source_limit = determine_backfill_source_limit(args.backfill_days, args.backfill_limit)
    videos = fetch_latest_videos(limit=source_limit)
    scoped_videos = select_backfill_videos(videos, now, args.backfill_days)
    summary = BackfillSummary(scanned=len(scoped_videos))

    print(
        "backfill mode:"
        f" days={args.backfill_days}"
        f" source_limit={source_limit}"
        f" fetched={len(videos)}"
        f" scoped={len(scoped_videos)}"
        f" force_reanalyze={'true' if args.force_reanalyze else 'false'}"
    )

    for video in scoped_videos:
        vod_id = video["vod_id"]
        cached = cached_by_vod_id.get(vod_id)
        if not should_reanalyze_cached_video(cached, force_reanalyze=args.force_reanalyze):
            print(f"reuse {vod_id}")
            cached_by_vod_id[vod_id] = merge_video_metadata(video, cached or {})
            summary.reused += 1
            summary.reused_vod_ids.append(vod_id)
            continue

        analyzed_video, status = analyze_video_entry(video, now)
        if analyzed_video:
            cached_by_vod_id[vod_id] = analyzed_video
            summary.analyzed += 1
            summary.analyzed_details.append(build_analyzed_detail_entry(analyzed_video))
            continue

        if status == "failed":
            summary.failed += 1
            summary.failed_vod_ids.append(vod_id)
        else:
            summary.skipped += 1

        if cached:
            print(f"keep-cache {vod_id}")
            cached_by_vod_id[vod_id] = merge_video_metadata(video, cached)

    write_processed_cache(cached_by_vod_id.values(), now)
    write_public_data(cached_by_vod_id.values(), now)
    write_backfill_summary_file(
        summary,
        now,
        backfill_days=args.backfill_days,
        source_limit=source_limit,
        fetched_count=len(videos),
        scoped_count=len(scoped_videos),
        force_reanalyze=args.force_reanalyze,
    )
    print_backfill_summary(summary)
    print("wrote data/vods.json")


def determine_backfill_source_limit(backfill_days: int, backfill_limit: int | None) -> int:
    if backfill_limit is not None:
        return backfill_limit
    return max(BACKFILL_SOURCE_LIMIT_FLOOR, backfill_days * BACKFILL_SOURCE_LIMIT_MULTIPLIER)


def select_backfill_videos(videos: list[dict[str, str]], now: datetime, backfill_days: int) -> list[dict[str, str]]:
    cutoff = now - timedelta(days=backfill_days)
    scoped: list[dict[str, str]] = []
    for video in videos:
        published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
        if not published_at:
            continue
        if published_at < cutoff:
            break
        scoped.append(video)
    return scoped


def print_backfill_summary(summary: BackfillSummary) -> None:
    print("backfill summary:")
    print(f"  scanned={summary.scanned}")
    print(f"  reused={summary.reused}")
    print(f"  analyzed={summary.analyzed}")
    print(f"  skipped={summary.skipped}")
    print(f"  failed={summary.failed}")
    print("  analyzed_vod_ids:")
    if summary.analyzed_details:
        for detail in summary.analyzed_details:
            print(
                "    -"
                f" {detail['vod_id']}"
                f" items_count={detail['items_count']}"
                f" activity_bucket_count={detail['activity_bucket_count']}"
            )
    else:
        print("    - (none)")
    print(f"  reused_vod_ids: {format_vod_id_list(summary.reused_vod_ids)}")
    print(f"  failed_vod_ids: {format_vod_id_list(summary.failed_vod_ids)}")
    print("  summary_file: data/backfill_summary.json")


def build_analyzed_detail_entry(video: dict[str, Any]) -> dict[str, int | str]:
    items = video.get("items")
    activity_map = normalize_activity_map(video.get("activity_map"))
    buckets = activity_map.get("buckets")
    return {
        "vod_id": str(video.get("vod_id") or "").strip(),
        "items_count": len(items) if isinstance(items, list) else 0,
        "activity_bucket_count": len(buckets) if isinstance(buckets, list) else 0,
    }


def format_vod_id_list(vod_ids: list[str]) -> str:
    return ", ".join(vod_ids) if vod_ids else "(none)"


def write_backfill_summary_file(
    summary: BackfillSummary,
    now: datetime,
    *,
    backfill_days: int,
    source_limit: int,
    fetched_count: int,
    scoped_count: int,
    force_reanalyze: bool,
) -> None:
    payload = {
        "mode": "backfill",
        "updated_at": now.isoformat(timespec="seconds"),
        "backfill_days": backfill_days,
        "source_limit": source_limit,
        "fetched": fetched_count,
        "scoped": scoped_count,
        "force_reanalyze": force_reanalyze,
        "counts": {
            "scanned": summary.scanned,
            "reused": summary.reused,
            "analyzed": summary.analyzed,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
        "analyzed": summary.analyzed_details,
        "reused": summary.reused_vod_ids,
        "failed": summary.failed_vod_ids,
    }
    write_json_payload(BACKFILL_SUMMARY_PATH, payload)


def next_scheduled_update_at(now: datetime) -> datetime:
    base = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    now_jst = base.astimezone(JST_TIMEZONE)
    scheduled_jst = now_jst.replace(hour=UPDATE_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    if scheduled_jst <= now_jst:
        scheduled_jst += timedelta(days=1)
    return scheduled_jst.astimezone(timezone.utc)


def get_positive_int_env(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def env_flag_is_enabled(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def twitch_live_check_enabled() -> bool:
    return env_flag_is_enabled("TWITCH_LIVE_CHECK_ENABLED", default=(TWITCH_LIVE_CHECK_ENABLED_DEFAULT == "1"))


def twitch_live_check_fail_open() -> bool:
    return env_flag_is_enabled("TWITCH_LIVE_CHECK_FAIL_OPEN", default=(TWITCH_LIVE_CHECK_FAIL_OPEN_DEFAULT == "1"))


def fetch_current_stream_status(channel_login: str = CHANNEL) -> dict[str, Any]:
    if not has_twitch_api_credentials():
        raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set")

    access_token = fetch_twitch_app_access_token()
    headers = build_twitch_api_headers(access_token)
    query = parse.urlencode(
        {
            "user_login": channel_login,
            "type": "live",
            "first": "1",
        }
    )
    payload = fetch_json(f"{TWITCH_STREAMS_URL}?{query}", headers=headers)
    data = payload.get("data") or []
    if not data:
        return {
            "channel": channel_login,
            "live": False,
            "stream_id": "",
            "started_at": "",
        }

    stream = data[0] if isinstance(data[0], dict) else {}
    return {
        "channel": channel_login,
        "live": True,
        "stream_id": str(stream.get("id") or "").strip(),
        "started_at": str(stream.get("started_at") or "").strip(),
    }


def is_channel_live(channel_login: str = CHANNEL) -> bool:
    return bool(fetch_current_stream_status(channel_login).get("live"))


def resolve_live_skip_decision(channel_login: str = CHANNEL) -> tuple[bool, str]:
    if not twitch_live_check_enabled():
        print(f"twitch_live_status: channel={channel_login} live_check_enabled=false")
        return False, "live_check_disabled"

    try:
        status = fetch_current_stream_status(channel_login)
    except Exception as exc:
        fail_open = twitch_live_check_fail_open()
        print(
            f"twitch_live_status_error: channel={channel_login}"
            f" error={exc}"
            f" fail_open={'true' if fail_open else 'false'}"
        )
        if fail_open:
            return False, "live_check_failed_fail_open"
        return True, "live_check_failed_safe_mode"

    if bool(status.get("live")):
        print(
            f"twitch_live_status: channel={channel_login} live=true"
            f" stream_id={status.get('stream_id') or ''}"
            f" started_at={status.get('started_at') or ''}"
        )
        return True, "channel_live"

    print(f"twitch_live_status: channel={channel_login} live=false")
    return False, "channel_offline"


def sort_videos_by_published_at_desc(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(video: dict[str, Any]) -> tuple[float, str]:
        published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
        timestamp = published_at.timestamp() if published_at else -1.0
        return (timestamp, str(video.get("vod_id") or ""))

    normalized = [video for video in videos if str(video.get("vod_id") or "").strip()]
    return sorted(normalized, key=key, reverse=True)


def resolve_latest_vod_id(videos: Iterable[dict[str, Any]]) -> str:
    ordered = sort_videos_by_published_at_desc(videos)
    if not ordered:
        return ""
    return str(ordered[0].get("vod_id") or "").strip()


def load_processed_cache() -> dict[str, Any]:
    for path in (CACHE_PATH, OUT_PATH):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding=JSON_READ_ENCODING))
        except json.JSONDecodeError:
            continue
        videos = payload.get("videos") or payload.get("vods") or []
        normalized = [normalize_cached_video(video) for video in videos]
        return {
            "channel": payload.get("channel", CHANNEL),
            "analysis_version": payload.get("analysis_version", ANALYSIS_VERSION),
            "videos": [video for video in normalized if video],
        }
    return {"channel": CHANNEL, "analysis_version": ANALYSIS_VERSION, "videos": []}


def normalize_cached_video(video: dict[str, Any]) -> dict[str, Any] | None:
    vod_id = str(video.get("vod_id") or video.get("id") or "").strip()
    if not vod_id:
        return None
    items = video.get("items") or video.get("segments") or []
    normalized = {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or video.get("url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "count": int(video.get("count") or len(items)),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "items": items,
        "activity_map": normalize_activity_map(video.get("activity_map")),
        "analysis_version": video.get("analysis_version", ANALYSIS_VERSION),
        "analyzed_at": video.get("analyzed_at") or video.get("updated_at") or "",
    }
    return normalized


def resolve_video_entry(
    video: dict[str, str], cached_by_vod_id: dict[str, dict[str, Any]], now: datetime
) -> dict[str, Any] | None:
    vod_id = video["vod_id"]
    cached = cached_by_vod_id.get(vod_id)
    if is_reusable_cached_video(cached):
        print(f"reuse {vod_id}")
        return merge_video_metadata(video, cached)

    analyzed_video, _ = analyze_video_entry(video, now)
    return analyzed_video


def analyze_video_entry(video: dict[str, str], now: datetime) -> tuple[dict[str, Any] | None, str]:
    vod_id = video["vod_id"]
    print(f"analyze {vod_id}")
    try:
        chat_data = fetch_chat_data(vod_id, FetchConfig())
        comments = chat_data.comments
        chat_total = len(comments)
        activity_map = build_activity_map(comments, DetectConfig(), chat_data.duration_sec)
        comments_per_hour_duration_sec = resolve_comments_per_hour_duration_sec(
            chat_data_duration_sec=chat_data.duration_sec,
            activity_map_duration_sec=activity_map.get("duration_sec"),
        )
        comments_per_hour = calculate_comments_per_hour(chat_total, comments_per_hour_duration_sec)
        items = detect_items(
            comments,
            vod_id,
            DetectConfig(),
            total_duration_sec=comments_per_hour_duration_sec,
        )
    except Exception as exc:
        print(f"warn: skip {vod_id} ({exc})")
        return None, "failed"

    if not items:
        print(f"warn: skip {vod_id} (no detectable segments)")
        return None, "skipped"

    return {
        "vod_id": vod_id,
        "vod_url": video["vod_url"],
        "title": video["title"],
        "published_at": video["published_at"],
        "thumbnail_url": video["thumbnail_url"],
        "duration_sec": comments_per_hour_duration_sec,
        "count": len(items),
        "chat_total": chat_total,
        "comments_per_hour": comments_per_hour,
        "items": items,
        "activity_map": activity_map,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now.isoformat(timespec="seconds"),
    }, "analyzed"


def is_reusable_cached_video(video: dict[str, Any] | None) -> bool:
    if not video:
        return False
    if video.get("analysis_version") != ANALYSIS_VERSION:
        return False
    items = video.get("items") or []
    return bool(items)


def should_reanalyze_cached_video(video: dict[str, Any] | None, *, force_reanalyze: bool = False) -> bool:
    if force_reanalyze:
        return True
    if not video:
        return True
    if video.get("analysis_version") != ANALYSIS_VERSION:
        return True

    items = video.get("items")
    if not isinstance(items, list) or not items:
        return True

    activity_map = video.get("activity_map")
    if not isinstance(activity_map, dict) or not activity_map:
        return True
    buckets = activity_map.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        return True
    return False


def merge_video_metadata(latest: dict[str, str], cached: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "vod_id": latest["vod_id"],
        "vod_url": latest["vod_url"],
        "title": latest["title"],
        "published_at": latest["published_at"],
        "thumbnail_url": latest["thumbnail_url"],
        "duration_sec": parse_int(cached.get("duration_sec")) or parse_int(latest.get("duration_sec")),
        "count": int(cached.get("count") or len(cached.get("items") or [])),
        "chat_total": normalize_chat_total(cached.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(cached.get("comments_per_hour")),
        "items": cached.get("items") or [],
        "activity_map": normalize_activity_map(cached.get("activity_map")),
        "analysis_version": cached.get("analysis_version", ANALYSIS_VERSION),
        "analyzed_at": cached.get("analyzed_at", ""),
    }
    return merged


TAG_LABEL_ALIASES = {
    "笑い": "ww",
    "衝撃": "えっ",
    "神プレイ": "好プレー",
    "えっろ": "えっど",
    "は？": "は",
}


def normalize_tag_labels(tags: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        label = TAG_LABEL_ALIASES.get(str(tag), str(tag)).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def refresh_cached_video_metadata(video: dict[str, Any], comments: list[dict[str, Any]], duration_sec: int | None) -> dict[str, Any]:
    refreshed = dict(video)
    items: list[dict[str, Any]] = []
    for item in video.get("items") or []:
        updated_item = dict(item)
        start_sec = parse_int(item.get("start_sec"))
        end_sec = parse_int(item.get("end_sec"))
        if start_sec is not None and end_sec is not None:
            updated_item["tags"] = normalize_tag_labels(classify_segment_tags(comments, start_sec, end_sec))
        items.append(updated_item)
    refreshed["items"] = items
    refreshed["activity_map"] = build_activity_map(comments, DetectConfig(), duration_sec)
    return refreshed


def normalize_chat_total(value: Any) -> int | None:
    chat_total = parse_int(value)
    if chat_total is None or chat_total < 0:
        return None
    return chat_total


def parse_non_negative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def normalize_comments_per_hour(value: Any) -> float | None:
    comments_per_hour = parse_non_negative_float(value)
    if comments_per_hour is None:
        return None
    return round(comments_per_hour, 3)


def resolve_comments_per_hour_duration_sec(
    *,
    chat_data_duration_sec: Any,
    activity_map_duration_sec: Any,
) -> int | None:
    chat_duration_sec = parse_int(chat_data_duration_sec)
    if chat_duration_sec is not None and chat_duration_sec > 0:
        return chat_duration_sec
    activity_duration_sec = parse_int(activity_map_duration_sec)
    if activity_duration_sec is not None and activity_duration_sec > 0:
        return activity_duration_sec
    return None


def calculate_comments_per_hour(chat_total: int, duration_sec: int | None) -> float | None:
    if duration_sec is None or duration_sec <= 0:
        return None
    return round(float(chat_total) / (float(duration_sec) / 3600.0), 3)
def to_public_video_entry(video: dict[str, Any]) -> dict[str, Any]:
    vod_id = str(video.get("vod_id") or "").strip()
    return {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "duration_sec": parse_int(video.get("duration_sec")),
        "count": int(video.get("count") or len(video.get("items") or [])),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "items": [to_public_item_entry(item) for item in (video.get("items") or [])],
        "activity_map": to_public_activity_map(video.get("activity_map")),
    }

def to_public_video_index_entry(video: dict[str, Any]) -> dict[str, Any]:
    vod_id = str(video.get("vod_id") or "").strip()
    return {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "duration_sec": parse_int(video.get("duration_sec")),
        "count": int(video.get("count") or len(video.get("items") or [])),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "detail_path": build_vod_detail_path(vod_id),
    }



def build_vod_detail_path(vod_id: str) -> str:
    return f"/data/vods/{vod_id}.json"


def to_public_activity_map(value: Any) -> dict[str, Any]:
    activity_map = normalize_activity_map(value)
    activity_map.pop("peak_count", None)
    return activity_map


def format_json_with_compact_arrays(value: Any) -> str:
    rendered = render_json_value(value, level=0, path=())
    return f"{rendered}\n"


def write_json_payload(path: Path, value: Any) -> None:
    path.write_text(format_json_with_compact_arrays(value), encoding=JSON_WRITE_ENCODING)


def render_json_value(value: Any, *, level: int, path: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        if not value:
            return "{}"
        indent = "  " * level
        next_indent = "  " * (level + 1)
        parts: list[str] = []
        items = list(value.items())
        for index, (key, child) in enumerate(items):
            key_text = json.dumps(str(key), ensure_ascii=False)
            child_text = render_json_value(child, level=level + 1, path=path + (str(key),))
            line = f"{next_indent}{key_text}: {child_text}"
            if index < len(items) - 1:
                line += ","
            parts.append(line)
        return "{\n" + "\n".join(parts) + "\n" + indent + "}"

    if isinstance(value, list):
        if (
            path[-2:] in COMPACT_ARRAY_PATHS
            and value
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ):
            return render_compact_numeric_array(value, level=level)

        if not value:
            return "[]"
        indent = "  " * level
        next_indent = "  " * (level + 1)
        parts: list[str] = []
        for index, child in enumerate(value):
            child_text = render_json_value(child, level=level + 1, path=path)
            line = f"{next_indent}{child_text}"
            if index < len(value) - 1:
                line += ","
            parts.append(line)
        return "[\n" + "\n".join(parts) + "\n" + indent + "]"

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_compact_numeric_array(values: list[int | float], *, level: int) -> str:
    indent = "  " * level
    line_indent = "  " * (level + 1)
    chunks = [
        values[index : index + COMPACT_ARRAY_ITEMS_PER_LINE]
        for index in range(0, len(values), COMPACT_ARRAY_ITEMS_PER_LINE)
    ]
    lines: list[str] = []
    for chunk_index, chunk in enumerate(chunks):
        numbers = ", ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in chunk)
        suffix = "," if chunk_index < len(chunks) - 1 else ""
        lines.append(f"{line_indent}{numbers}{suffix}")
    return "[\n" + "\n".join(lines) + "\n" + indent + "]"


def write_processed_cache(videos: Iterable[dict[str, Any]], now: datetime) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        [sanitize_video_for_storage(video) for video in videos if video.get("vod_id")],
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )
    payload = {
        "updated_at": now.isoformat(timespec="seconds"),
        "channel": CHANNEL,
        "channel_url": CHANNEL_URL,
        "analysis_version": ANALYSIS_VERSION,
        "videos": ordered,
    }
    write_json_payload(CACHE_PATH, payload)


def to_public_item_entry(item: dict[str, Any]) -> dict[str, Any]:
    public_item = {field: item[field] for field in PUBLIC_ITEM_FIELDS if field in item}
    start_sec = parse_int(public_item.get("start_sec"))
    end_sec = parse_int(public_item.get("end_sec"))
    if start_sec is not None and end_sec is not None and "duration_sec" not in public_item:
        public_item["duration_sec"] = max(0, end_sec - start_sec)
    if start_sec is not None and "start_time" not in public_item:
        public_item["start_time"] = format_hhmmss(start_sec)
    if end_sec is not None and "end_time" not in public_item:
        public_item["end_time"] = format_hhmmss(end_sec)
    tags = public_item.get("tags")
    if isinstance(tags, list):
        public_item["tags"] = normalize_tag_labels(tags)
    segment_id = str(public_item.get("id") or "").strip()
    vod_id = infer_vod_id_from_segment_id(segment_id)
    screenshot_url = resolve_public_segment_screenshot_url_if_exists(vod_id, segment_id)
    if screenshot_url:
        public_item["screenshot_url"] = screenshot_url
    else:
        public_item.pop("screenshot_url", None)
    return public_item


def infer_vod_id_from_segment_id(segment_id: str) -> str:
    value = str(segment_id or "").strip()
    if not value:
        return ""
    head, _, _ = value.partition("_")
    return head if head.isdigit() else ""


def has_segment_screenshot_file(vod_id: str, segment_id: str) -> bool:
    if not vod_id or not segment_id:
        return False
    screenshot_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if not screenshot_path.exists():
        return False
    try:
        return screenshot_path.stat().st_size > 0
    except OSError:
        return False


def resolve_public_segment_screenshot_url_if_exists(vod_id: str, segment_id: str) -> str:
    if not has_segment_screenshot_file(vod_id, segment_id):
        return ""
    return build_segment_screenshot_public_path(vod_id, segment_id)
def sanitize_video_for_storage(video: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "vod_id",
        "vod_url",
        "title",
        "published_at",
        "thumbnail_url",
        "duration_sec",
        "count",
        "chat_total",
        "comments_per_hour",
        "items",
        "activity_map",
        "analysis_version",
        "analyzed_at",
    )
    sanitized = {field: video[field] for field in fields if field in video}
    sanitized["items"] = [sanitize_item_for_storage(item) for item in (video.get("items") or [])]
    return sanitized

def sanitize_item_for_storage(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "rank",
        "id",
        "start_sec",
        "end_sec",
        "duration_sec",
        "start_time",
        "end_time",
        "reason",
        "headline",
        "tags",
        "watch_url",
        "screenshot_url",
    )
    return {field: item[field] for field in fields if field in item}



def build_public_payload(videos: Iterable[dict[str, Any]], now: datetime) -> dict[str, Any]:
    filtered_videos = filter_public_videos_within_retention(videos, now)
    public_videos = [to_public_video_entry(video) for video in filtered_videos[:PUBLIC_VIDEO_LIMIT]]
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "next_update_at": next_scheduled_update_at(now).isoformat(timespec="seconds"),
        "videos": public_videos,
    }


def build_public_index_payload(videos: Iterable[dict[str, Any]], now: datetime) -> dict[str, Any]:
    filtered_videos = filter_public_videos_within_retention(videos, now)
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "next_update_at": next_scheduled_update_at(now).isoformat(timespec="seconds"),
        "videos": [to_public_video_index_entry(video) for video in filtered_videos],
    }


def order_public_videos(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [video for video in videos if str(video.get("vod_id") or "").strip()],
        key=lambda item: str(item.get("published_at", "")),
        reverse=True,
    )


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


def is_public_vod_within_retention(video: dict[str, Any], now: datetime) -> bool:
    published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
    if not published_at:
        return False
    cutoff = now - timedelta(days=PUBLIC_VOD_RETENTION_DAYS)
    return published_at >= cutoff


def filter_public_videos_within_retention(videos: Iterable[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    ordered_videos = order_public_videos(videos)
    return [video for video in ordered_videos if is_public_vod_within_retention(video, now)]


def collect_public_vod_id_set(videos: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(video.get("vod_id") or "").strip()
        for video in videos
        if str(video.get("vod_id") or "").strip()
    }


def cleanup_stale_segment_thumbnail_dirs(public_vod_ids: set[str]) -> list[str]:
    if not SEGMENT_THUMBNAILS_DIR.exists():
        return []

    removed_vod_ids: list[str] = []
    for child in sorted(SEGMENT_THUMBNAILS_DIR.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        vod_id = child.name.strip()
        if not vod_id or vod_id in public_vod_ids:
            continue
        shutil.rmtree(child)
        removed_vod_ids.append(vod_id)
    return removed_vod_ids


def find_missing_public_screenshot_urls(public_videos: Iterable[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for video in public_videos:
        vod_id = str(video.get("vod_id") or "").strip()
        for item in video.get("items") or []:
            screenshot_url = str(item.get("screenshot_url") or "").strip()
            if not screenshot_url:
                continue
            segment_id = str(item.get("id") or "").strip()
            if not has_segment_screenshot_file(vod_id, segment_id):
                missing.append(screenshot_url)
    return missing


def assert_public_screenshot_urls_are_resolvable(public_videos: Iterable[dict[str, Any]]) -> None:
    missing = find_missing_public_screenshot_urls(public_videos)
    if missing:
        sample = ", ".join(missing[:3])
        raise RuntimeError(f"public screenshot_url references missing files: {sample}")


def write_public_data(videos: Iterable[dict[str, Any]], now: datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    public_videos = filter_public_videos_within_retention(videos, now)
    public_vod_ids = collect_public_vod_id_set(public_videos)
    removed_vod_ids = cleanup_stale_segment_thumbnail_dirs(public_vod_ids)
    for vod_id in removed_vod_ids:
        print(f"pruned stale thumbnails for vod_id={vod_id}")

    latest_payload = build_public_payload(public_videos, now)
    assert_public_screenshot_urls_are_resolvable(latest_payload.get("videos") or [])
    write_json_payload(OUT_PATH, latest_payload)

    index_payload = build_public_index_payload(public_videos, now)
    write_json_payload(VOD_INDEX_PATH, index_payload)

    VOD_DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    detail_videos = [to_public_video_entry(video) for video in public_videos]
    assert_public_screenshot_urls_are_resolvable(detail_videos)
    detail_vod_ids: set[str] = set()
    for public_video in detail_videos:
        vod_id = public_video["vod_id"]
        detail_vod_ids.add(vod_id)
        detail_path = VOD_DETAILS_DIR / f"{vod_id}.json"
        write_json_payload(detail_path, public_video)

    for stale_path in VOD_DETAILS_DIR.glob("*.json"):
        if stale_path.stem not in detail_vod_ids:
            stale_path.unlink()


def fetch_latest_videos(limit: int) -> list[dict[str, str]]:
    if has_twitch_api_credentials():
        try:
            return fetch_latest_videos_from_twitch_api(limit)
        except Exception as exc:
            print(f"warn: Twitch API fetch failed ({exc}); falling back to TwitchMetrics")
    else:
        print("warn: TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set; falling back to TwitchMetrics")

    return fetch_latest_videos_from_twitchmetrics(limit)


def has_twitch_api_credentials() -> bool:
    return bool(TWITCH_API_CLIENT_ID and TWITCH_API_CLIENT_SECRET)


def fetch_latest_videos_from_twitch_api(limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []

    access_token = fetch_twitch_app_access_token()
    headers = build_twitch_api_headers(access_token)
    user_id = fetch_twitch_user_id(CHANNEL, headers)
    videos: list[dict[str, str]] = []
    seen_vod_ids: set[str] = set()
    cursor = ""
    while len(videos) < limit:
        query_params: dict[str, str] = {
            "user_id": user_id,
            "type": "archive",
            "first": str(min(100, max(1, limit - len(videos)))),
        }
        if cursor:
            query_params["after"] = cursor
        query = parse.urlencode(query_params)
        payload = fetch_json(f"{TWITCH_VIDEOS_URL}?{query}", headers=headers)
        page_items = payload.get("data") or []
        if not page_items:
            break

        for item in page_items:
            vod_id = str(item.get("id") or "").strip()
            published_at = str(item.get("published_at") or item.get("created_at") or "").strip()
            if not vod_id or not published_at or vod_id in seen_vod_ids:
                continue
            seen_vod_ids.add(vod_id)
            videos.append(
                {
                    "vod_id": vod_id,
                    "vod_url": str(item.get("url") or f"https://www.twitch.tv/videos/{vod_id}"),
                    "title": str(item.get("title") or "").strip(),
                    "published_at": to_local_iso(published_at),
                    "thumbnail_url": normalize_thumbnail_url(str(item.get("thumbnail_url") or "").strip()),
                    "duration_sec": parse_twitch_duration_text(item.get("duration")),
                }
            )
            if len(videos) >= limit:
                break

        cursor = str((payload.get("pagination") or {}).get("cursor") or "").strip()
        if not cursor:
            break

    return videos


def fetch_twitch_app_access_token() -> str:
    body = parse.urlencode(
        {
            "client_id": TWITCH_API_CLIENT_ID,
            "client_secret": TWITCH_API_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    payload = fetch_json(
        TWITCH_OAUTH_URL,
        method="POST",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("missing access_token in Twitch OAuth response")
    return access_token


def build_twitch_api_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": TWITCH_API_CLIENT_ID,
        "User-Agent": USER_AGENT,
    }


def fetch_twitch_user_id(login: str, headers: dict[str, str]) -> str:
    query = parse.urlencode({"login": login})
    payload = fetch_json(f"{TWITCH_USERS_URL}?{query}", headers=headers)
    users = payload.get("data") or []
    if not users:
        raise RuntimeError(f"Twitch user not found for login={login}")
    user_id = str(users[0].get("id") or "").strip()
    if not user_id:
        raise RuntimeError(f"missing Twitch user id for login={login}")
    return user_id


def fetch_latest_videos_from_twitchmetrics(limit: int) -> list[dict[str, str]]:
    if not TWITCHMETRICS_URL:
        return []
    html = fetch_text(TWITCHMETRICS_URL)
    blocks = re.findall(r'<li class="list-group-item d-block">(.*?)</li>', html, flags=re.S)
    videos: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for block in blocks:
        url_match = re.search(r'href="(https://www\.twitch\.tv/videos/(?P<vod_id>\d+))"', block)
        title_match = re.search(r"<h5[^>]*>(.*?)</h5>", block, flags=re.S)
        time_match = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        thumb_match = re.search(r'<img[^>]+src="([^"]+)"', block)
        if not url_match or not title_match or not time_match:
            continue

        vod_id = url_match.group("vod_id")
        if vod_id in seen_ids:
            continue
        seen_ids.add(vod_id)

        videos.append(
            {
                "vod_id": vod_id,
                "vod_url": f"https://www.twitch.tv/videos/{vod_id}",
                "title": clean_html_text(title_match.group(1)),
                "published_at": to_local_iso(time_match.group(1)),
                "thumbnail_url": html_unescape(thumb_match.group(1)) if thumb_match else "",
            }
        )
        if len(videos) >= limit:
            break

    return videos


def fetch_chat_data(vod_id: str, cfg: FetchConfig) -> ChatFetchResult:
    downloader_bin = resolve_twitchdownloader_bin()
    if downloader_bin:
        try:
            return fetch_chat_data_with_twitchdownloader(vod_id, cfg, downloader_bin)
        except Exception as exc:
            print(f"warn: TwitchDownloader fetch failed for {vod_id} ({exc}); falling back to Twitch GQL")

    return ChatFetchResult(comments=fetch_chat_comments_gql(vod_id, cfg), duration_sec=None)


def resolve_twitchdownloader_bin() -> str | None:
    env_path = os.environ.get("TWITCHDOWNLOADER_BIN", "").strip()
    candidates = [
        env_path,
        str(Path(__file__).resolve().parents[1] / ".tmp-tools" / "twitchdownloader" / "TwitchDownloaderCLI"),
        str(Path(__file__).resolve().parents[1] / ".tmp-tools" / "twitchdownloader" / "TwitchDownloaderCLI.exe"),
        str(Path(__file__).resolve().parents[1] / ".tmp-tools" / "TwitchDownloaderCLI" / "TwitchDownloaderCLI"),
        str(Path(__file__).resolve().parents[1] / ".tmp-tools" / "TwitchDownloaderCLI" / "TwitchDownloaderCLI.exe"),
        shutil.which("TwitchDownloaderCLI") or "",
        shutil.which("TwitchDownloaderCLI.exe") or "",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def fetch_chat_data_with_twitchdownloader(vod_id: str, cfg: FetchConfig, downloader_bin: str) -> ChatFetchResult:
    with tempfile.TemporaryDirectory(prefix=f"twitch-chat-{vod_id}-") as temp_dir:
        output_path = Path(temp_dir) / "chat.json"
        cmd = [
            downloader_bin,
            "chatdownload",
            "--id",
            vod_id,
            "--output",
            str(output_path),
            "--threads",
            "4",
            "--collision",
            "Overwrite",
            "--banner=false",
            "--log-level",
            "Warning,Error",
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(60, cfg.timeout_sec * cfg.max_pages),
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip().splitlines()[-1]
            raise RuntimeError(detail)
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    return parse_twitchdownloader_chat_payload(payload)


def parse_twitchdownloader_chat_payload(payload: dict[str, Any]) -> ChatFetchResult:
    comments: list[dict[str, Any]] = []
    for item in payload.get("comments") or []:
        sec = item.get("content_offset_seconds")
        if not isinstance(sec, (int, float)):
            continue
        comments.append(
            {
                "id": item.get("_id"),
                "content_offset_seconds": sec,
                "user_name": extract_twitchdownloader_user_name(item),
                "message": extract_twitchdownloader_message_text(item.get("message") or {}),
            }
        )

    video = payload.get("video") or {}
    duration_raw = video.get("length")
    duration_sec = int(math.ceil(float(duration_raw))) if isinstance(duration_raw, (int, float)) and float(duration_raw) > 0 else None
    return ChatFetchResult(comments=comments, duration_sec=duration_sec)


def extract_twitchdownloader_message_text(message: dict[str, Any]) -> str:
    body = str(message.get("body") or "").strip()
    if body:
        return body

    fragments = message.get("fragments") or []
    parts: list[str] = []
    for fragment in fragments:
        text = fragment.get("text")
        if text:
            parts.append(str(text))
    return "".join(parts).strip()


def extract_twitchdownloader_user_name(comment: dict[str, Any]) -> str:
    commenter = comment.get("commenter") or {}
    if isinstance(commenter, dict):
        for key in ("display_name", "name", "login"):
            value = str(commenter.get(key) or "").strip()
            if value:
                return value
    return "unknown"


def extract_commenter_user_name(commenter: dict[str, Any]) -> str:
    for key in ("displayName", "login"):
        value = str(commenter.get(key) or "").strip()
        if value:
            return value
    return "unknown"


def fetch_chat_comments_gql(vod_id: str, cfg: FetchConfig) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    pages = 0
    offset = 0
    seen_keys: set[tuple[str | None, float | None]] = set()

    while pages < cfg.max_pages:
        payload = {
            "operationName": "VideoCommentsByOffsetOrCursor",
            "query": VIDEO_COMMENTS_QUERY,
            "variables": {
                "videoID": vod_id,
                "contentOffsetSeconds": offset,
            },
        }
        obj = post_gql(payload, cfg.timeout_sec)
        if "errors" in obj:
            raise RuntimeError(obj["errors"][0].get("message", "Twitch GQL error"))

        block = obj.get("data", {}).get("video", {}).get("comments", {})
        edges = block.get("edges") or []
        if not edges:
            break

        max_offset_this_page = offset
        for edge in edges:
            node = edge.get("node") or {}
            sec = node.get("contentOffsetSeconds")
            key = (node.get("id"), sec)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            comments.append(
                {
                    "id": node.get("id"),
                    "content_offset_seconds": sec,
                    "user_name": extract_commenter_user_name(node.get("commenter") or {}),
                    "message": extract_message_text(node.get("message") or {}),
                }
            )
            if isinstance(sec, (int, float)) and sec > max_offset_this_page:
                max_offset_this_page = int(sec)

        pages += 1
        has_next = bool((block.get("pageInfo") or {}).get("hasNextPage"))
        if not has_next or max_offset_this_page <= offset:
            break
        offset = max_offset_this_page + 1
        if cfg.sleep_sec > 0:
            time.sleep(cfg.sleep_sec)

    return comments


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


def fetch_text(url: str) -> str:
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    with request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    data: bytes | None = None,
    timeout_sec: int = 20,
) -> dict[str, Any]:
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    with request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def post_gql(payload: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        TWITCH_GQL_URL,
        data=body,
        headers={
            "Client-ID": TWITCH_GQL_CLIENT_ID,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


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


VIDEO_COMMENTS_QUERY = """
query VideoCommentsByOffsetOrCursor(
  $videoID: ID!
  $contentOffsetSeconds: Int
) {
  video(id: $videoID) {
    comments(contentOffsetSeconds: $contentOffsetSeconds) {
      edges {
        node {
          id
          contentOffsetSeconds
          commenter {
            displayName
            login
          }
          message {
            fragments {
              text
            }
          }
        }
      }
      pageInfo {
        hasNextPage
      }
    }
  }
}
""".strip()


if __name__ == "__main__":
    main()
