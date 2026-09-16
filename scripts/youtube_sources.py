from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from vod_sources import ChatFetchResult


YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_URL_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
YOUTUBE_ORACLE_COMMAND_ENV = "YOUTUBE_ORACLE_COMMAND_JSON"
YOUTUBE_ORACLE_TIMEOUT_ENV = "YOUTUBE_ORACLE_TIMEOUT_SEC"
YOUTUBE_URL_TOKEN = "{url}"


@dataclass(frozen=True)
class YoutubeOracleConfig:
    command: tuple[str, ...]
    timeout_sec: int = 300


@dataclass(frozen=True)
class YoutubeFetchResult:
    video: dict[str, Any]
    chat: ChatFetchResult


def parse_youtube_video_id(value: str) -> str:
    raw = str(value or "").strip()
    if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(raw):
        return raw

    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    if hostname not in YOUTUBE_URL_HOSTS:
        raise ValueError("unsupported YouTube URL")

    if hostname in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        candidate = parts[1] if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"} else ""

    if not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(candidate):
        raise ValueError("missing or invalid YouTube video id")
    return candidate


def build_oracle_command(config: YoutubeOracleConfig, video_url: str) -> list[str]:
    if not config.command:
        raise ValueError("YouTube Oracle command is empty")
    if not any(YOUTUBE_URL_TOKEN in token for token in config.command):
        raise ValueError("YouTube Oracle command must contain {url}")

    command_names = {token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() for token in config.command}
    remote_command = bool(command_names & {"ssh", "ssh.exe", "plink", "plink.exe"}) or any(
        "oracle" in token.lower() for token in config.command
    )
    direct_downloader = any(name in {"yt-dlp", "yt-dlp.exe", "yt_dlp", "yt_dlp.exe"} for name in command_names)
    if direct_downloader or not remote_command:
        raise ValueError("YouTube chat must be fetched through an Oracle VM command")

    return [token.replace(YOUTUBE_URL_TOKEN, video_url) for token in config.command]


def youtube_oracle_config_from_env(env: Mapping[str, str] | None = None) -> YoutubeOracleConfig:
    source = os.environ if env is None else env
    raw_command = str(source.get(YOUTUBE_ORACLE_COMMAND_ENV) or "").strip()
    if not raw_command:
        raise RuntimeError(f"{YOUTUBE_ORACLE_COMMAND_ENV} is not set")
    try:
        parsed_command = json.loads(raw_command)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid {YOUTUBE_ORACLE_COMMAND_ENV}") from exc
    if not isinstance(parsed_command, list) or not all(isinstance(item, str) and item.strip() for item in parsed_command):
        raise RuntimeError(f"{YOUTUBE_ORACLE_COMMAND_ENV} must be a JSON string array")

    try:
        timeout_sec = int(str(source.get(YOUTUBE_ORACLE_TIMEOUT_ENV) or "300"))
    except ValueError:
        timeout_sec = 300
    if timeout_sec <= 0:
        timeout_sec = 300
    return YoutubeOracleConfig(command=tuple(parsed_command), timeout_sec=timeout_sec)


def fetch_youtube_video(
    video_url: str,
    config: YoutubeOracleConfig | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> YoutubeFetchResult:
    video_id = parse_youtube_video_id(video_url)
    oracle_config = config or youtube_oracle_config_from_env()
    command = build_oracle_command(oracle_config, video_url)
    completed = runner(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=oracle_config.timeout_sec,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Oracle YouTube fetch failed for {video_id}")
    return parse_youtube_oracle_output(completed.stdout or "", video_url)


def parse_youtube_oracle_output(output: str, expected_video: str) -> YoutubeFetchResult:
    expected_video_id = parse_youtube_video_id(expected_video)
    metadata: dict[str, Any] = {}
    offsets: list[float] = []

    for line_number, raw_line in enumerate(str(output or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Oracle output line {line_number} is not JSON") from exc
        _collect_oracle_record(record, metadata, offsets)

    metadata_video_id = str(metadata.get("video_id") or "").strip()
    if metadata_video_id and metadata_video_id != expected_video_id:
        raise ValueError("Oracle output video id does not match requested video")
    if not offsets:
        raise ValueError("Oracle output contains no YouTube live_chat offsets")

    video: dict[str, Any] = {
        "provider": "youtube",
        "vod_id": expected_video_id,
        "vod_url": f"https://www.youtube.com/watch?v={expected_video_id}",
        "title": str(metadata.get("title") or f"YouTube archive {expected_video_id}").strip(),
        "published_at": str(metadata.get("published_at") or "").strip(),
        "thumbnail_url": str(metadata.get("thumbnail_url") or f"https://i.ytimg.com/vi/{expected_video_id}/hqdefault.jpg").strip(),
    }
    duration_sec = _parse_duration(metadata.get("duration_sec"))
    if duration_sec is not None:
        video["duration_sec"] = duration_sec

    comments = [{"content_offset_seconds": offset} for offset in offsets]
    return YoutubeFetchResult(video=video, chat=ChatFetchResult(comments=comments, duration_sec=duration_sec))


def _collect_oracle_record(record: Any, metadata: dict[str, Any], offsets: list[float]) -> None:
    if isinstance(record, dict):
        record_type = str(record.get("type") or "").strip().lower()
        is_metadata_record = record_type in {"metadata", "video", "info"} or any(
            key in record
            for key in (
                "title",
                "published_at",
                "thumbnail_url",
                "duration_sec",
                "upload_date",
                "thumbnail",
                "duration",
                "id",
            )
        )
        if is_metadata_record:
            candidate_id = record.get("video_id") or record.get("videoId") or record.get("id")
            if candidate_id:
                metadata["video_id"] = str(candidate_id).strip()
            for key in ("title", "published_at", "thumbnail_url", "duration_sec"):
                if key in record and record[key] not in (None, ""):
                    metadata[key] = record[key]
            if record.get("thumbnail") not in (None, "") and not metadata.get("thumbnail_url"):
                metadata["thumbnail_url"] = record["thumbnail"]
            if record.get("duration") not in (None, "") and "duration_sec" not in metadata:
                metadata["duration_sec"] = record["duration"]
            if record.get("upload_date") not in (None, "") and not metadata.get("published_at"):
                metadata["published_at"] = _normalize_upload_date(record["upload_date"])
        if "videoOffsetTimeMsec" in record:
            offset = _parse_offset_seconds(record.get("videoOffsetTimeMsec"))
            if offset is not None:
                offsets.append(offset)
        for child in record.values():
            _collect_oracle_record(child, metadata, offsets)
    elif isinstance(record, list):
        for child in record:
            _collect_oracle_record(child, metadata, offsets)


def _parse_offset_seconds(value: Any) -> float | None:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(milliseconds) or milliseconds < 0:
        return None
    return milliseconds / 1000.0


def _parse_duration(value: Any) -> int | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return int(math.ceil(duration))


def _normalize_upload_date(value: Any) -> str:
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
    return raw
