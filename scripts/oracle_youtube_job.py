"""Oracle-side YouTube acquisition and OCI PAR handoff.

Run this on the dedicated Oracle VM.  It performs the only YouTube network
access, detects the same chat-z-score highlights as the repository pipeline,
cuts only those intervals, and uploads a short-lived OCI Object Storage PAR
object.  Whisper is intentionally not run on the small Oracle VM.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib import error, request

from update_vods import analyze_video_entry
from vod_sources import ChatFetchResult
from youtube_handoff import build_material_manifest, create_material_bundle, upload_bundle_to_url
from youtube_sources import parse_youtube_video_id


class OracleJobFailure(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


DEFAULT_YTDLP = "/home/ubuntu/yt-dlp"
DEFAULT_DENO = "/home/ubuntu/.local/bin/deno"
DEFAULT_COOKIES = "/home/ubuntu/youtube-cookies.txt"
DEFAULT_WORK_ROOT = "/home/ubuntu/ytprobe"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _run(command: list[str], *, category: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OracleJobFailure(category, "required runtime was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise OracleJobFailure(category, "runtime timed out") from exc
    if completed.returncode != 0:
        raise OracleJobFailure(category, "runtime returned a non-zero exit status")
    return completed


def _classify_ytdlp_failure(completed: subprocess.CompletedProcess[str]) -> str:
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    if any(marker in text for marker in ("sign in", "authentication", "cookies", "login", "age-restricted")):
        return "cookie_authentication_failure"
    if any(marker in text for marker in ("not a bot", "captcha", "challenge", "confirm you're not")):
        return "youtube_bot_challenge_failure"
    if "deno" in text or "javascript runtime" in text or "remote-components" in text:
        return "yt_dlp_deno_failure"
    if any(marker in text for marker in ("timed out", "timeout", "connection", "network", "reset by peer")):
        return "temporary_network_failure"
    return "yt_dlp_failure"


def _run_ytdlp(command: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise OracleJobFailure("yt_dlp_deno_failure", "yt-dlp or its runtime was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise OracleJobFailure("temporary_network_failure", "yt-dlp timed out") from exc
    if completed.returncode != 0:
        raise OracleJobFailure(_classify_ytdlp_failure(completed), "yt-dlp failed")
    return completed


def _yt_dlp_base(ytdlp: str, deno: str, cookies: str) -> list[str]:
    return [
        ytdlp,
        "--js-runtimes",
        f"deno:{deno}",
        "--remote-components",
        "ejs:github",
        "--cookies",
        cookies,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
    ]


def _find_offset(value: Any) -> int | None:
    if isinstance(value, dict):
        if "videoOffsetTimeMsec" in value:
            try:
                offset = int(value["videoOffsetTimeMsec"])
            except (TypeError, ValueError):
                return None
            return offset if offset >= 0 else None
        for child in value.values():
            result = _find_offset(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_offset(child)
            if result is not None:
                return result
    return None


def _find_renderer(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        renderer = value.get("liveChatTextMessageRenderer")
        if isinstance(renderer, dict):
            return renderer
        for child in value.values():
            result = _find_renderer(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_renderer(child)
            if result is not None:
                return result
    return None


def _renderer_text(renderer: dict[str, Any] | None) -> str:
    if not renderer:
        return ""
    message = renderer.get("message")
    if not isinstance(message, dict):
        return ""
    simple = message.get("simpleText")
    if simple:
        return str(simple).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    runs = message.get("runs") or []
    return "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict)).strip()


def _read_live_chat(path: Path) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            offset_ms = _find_offset(record)
            if offset_ms is None:
                continue
            comment: dict[str, Any] = {"content_offset_seconds": offset_ms / 1000.0}
            text = _renderer_text(_find_renderer(record))
            if text:
                # This text exists in memory only for the detector/tag rules.
                comment["message"] = text
            comments.append(comment)
    return comments


def _metadata(completed: subprocess.CompletedProcess[str], video_id: str, video_url: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for line in completed.stdout.splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            record = candidate
            break
    upload_date = str(record.get("upload_date") or "").strip()
    published_at = ""
    if re.fullmatch(r"\d{8}", upload_date):
        published_at = dt.datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=dt.timezone.utc).isoformat()
    else:
        published_at = upload_date
    duration = record.get("duration")
    try:
        duration_sec = int(math.ceil(float(duration))) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_sec = None
    video = {
        "provider": "youtube",
        "vod_id": video_id,
        "vod_url": video_url,
        "title": str(record.get("title") or f"YouTube archive {video_id}").strip(),
        "published_at": published_at,
        "thumbnail_url": str(record.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg").strip(),
    }
    if duration_sec and duration_sec > 0:
        video["duration_sec"] = duration_sec
    return video


def _download_chat_and_metadata(video_url: str, work_dir: Path, ytdlp: str, deno: str, cookies: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    video_id = parse_youtube_video_id(video_url)
    stem = work_dir / "archive"
    _run_ytdlp(
        _yt_dlp_base(ytdlp, deno, cookies)
        + ["--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", str(stem), video_url]
    )
    chat_files = list(work_dir.glob("*.live_chat.json"))
    if not chat_files:
        raise OracleJobFailure("live_chat_zero", "yt-dlp returned no live chat file")
    comments = _read_live_chat(chat_files[0])
    for path in chat_files:
        path.unlink(missing_ok=True)
    if not comments:
        raise OracleJobFailure("live_chat_zero", "live chat contained no usable offsets")

    metadata_result = _run_ytdlp(
        _yt_dlp_base(ytdlp, deno, cookies)
        + ["--skip-download", "--print", "%(.{id,title,upload_date,duration,thumbnail})j", video_url]
    )
    return _metadata(metadata_result, video_id, video_url), comments


def _cut_media(video_url: str, item: dict[str, Any], index: int, work_dir: Path, ytdlp: str, deno: str, cookies: str) -> tuple[Path, Path]:
    start = int(item["start_sec"])
    end = int(item["end_sec"])
    source_prefix = work_dir / f"source-{index}"
    _run_ytdlp(
        _yt_dlp_base(ytdlp, deno, cookies)
        + [
            "--download-sections",
            f"*{start}-{end}",
            "--force-keyframes-at-cuts",
            "-f",
            "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
            "--merge-output-format",
            "mp4",
            "-o",
            f"{source_prefix}.%(ext)s",
            video_url,
        ],
        timeout=1200,
    )
    sources = [path for path in work_dir.glob(f"{source_prefix.name}.*") if path.suffix not in {".part", ".ytdl"}]
    if not sources:
        raise OracleJobFailure("yt_dlp_failure", "selected media section was not created")
    source = max(sources, key=lambda path: path.stat().st_size)
    audio = work_dir / f"clip-{index}.wav"
    screenshot = work_dir / f"clip-{index}.webp"
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        category="oracle_runtime_failure",
    )
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=192:108:force_original_aspect_ratio=decrease,pad=192:108:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libwebp",
            "-quality",
            "75",
            str(screenshot),
        ],
        category="oracle_runtime_failure",
    )
    if audio.stat().st_size <= 0 or screenshot.stat().st_size <= 0:
        raise OracleJobFailure("oracle_runtime_failure", "selected media output was empty")
    source.unlink(missing_ok=True)
    return audio, screenshot


def _dispatch_github(video_id: str) -> None:
    token = _env("YOUTUBE_ORACLE_GITHUB_TOKEN")
    repository = _env("YOUTUBE_ORACLE_GITHUB_REPOSITORY")
    if not token or not repository:
        raise OracleJobFailure("github_dispatch_configuration", "GitHub dispatch configuration is missing")
    url = f"https://api.github.com/repos/{repository}/dispatches"
    payload = json.dumps(
        {"event_type": "youtube-material-ready", "client_payload": {"video_id": video_id}}
    ).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            if int(getattr(response, "status", 200)) >= 300:
                raise OracleJobFailure("github_dispatch_failure", "GitHub dispatch failed")
    except (error.URLError, TimeoutError) as exc:
        raise OracleJobFailure("github_dispatch_failure", "GitHub dispatch failed") from exc


def _notify(category: str | None) -> None:
    webhook = _env("DISCORD_WEBHOOK_URL")
    state_path = Path(_env("YOUTUBE_ORACLE_STATE_PATH", "/var/lib/youtube-highlight/state.json"))
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        state = {}
    previous = str(state.get("failure_category") or "")
    if category:
        should_send = bool(webhook) and (previous != category or not bool(state.get("failure_notified")))
        if should_send:
            _send_discord(webhook, f"YouTube取得に失敗しました\ncategory: {category}\nprovider: youtube")
        state = {"failure_category": category, "failure_notified": bool(webhook)}
    elif previous:
        if webhook:
            _send_discord(webhook, "YouTube取得が復旧しました\nprovider: youtube")
        state = {"failure_category": "", "failure_notified": False}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _send_discord(webhook: str, content: str) -> None:
    req = request.Request(
        webhook,
        data=json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30):
            pass
    except (error.URLError, TimeoutError):
        pass


def run(video_url: str) -> dict[str, Any]:
    ytdlp = _env("YOUTUBE_ORACLE_YTDLP_PATH", DEFAULT_YTDLP)
    deno = _env("YOUTUBE_ORACLE_DENO_PATH", DEFAULT_DENO)
    cookies = _env("YOUTUBE_ORACLE_COOKIES_PATH", DEFAULT_COOKIES)
    upload_url = _env("YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL")
    if not upload_url:
        raise OracleJobFailure("handoff_configuration", "bundle upload PAR is not configured")
    if not Path(cookies).is_file():
        raise OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing")

    work_root = Path(_env("YOUTUBE_ORACLE_WORK_ROOT", DEFAULT_WORK_ROOT))
    work_root.mkdir(parents=True, exist_ok=True)
    video_id = parse_youtube_video_id(video_url)
    with tempfile.TemporaryDirectory(prefix=f"job-{video_id}-", dir=work_root) as temp_dir:
        work_dir = Path(temp_dir)
        video, comments = _download_chat_and_metadata(video_url, work_dir, ytdlp, deno, cookies)
        analyzed, status = analyze_video_entry(
            video,
            dt.datetime.now().astimezone(),
            chat_data_override=ChatFetchResult(comments=comments, duration_sec=video.get("duration_sec")),
            metadata_override=video,
        )
        if not analyzed or status != "analyzed":
            raise OracleJobFailure("highlight_detection_failure", "chat offsets produced no highlights")
        items = list(analyzed.get("items") or [])
        media_files: dict[str, Path] = {}
        for index, item in enumerate(items):
            audio, screenshot = _cut_media(video_url, item, index, work_dir, ytdlp, deno, cookies)
            media_files[f"clips/clip-{index}.wav"] = audio
            media_files[f"clips/clip-{index}.webp"] = screenshot
        manifest = build_material_manifest(video, comments, items)
        bundle_path = work_dir / f"youtube-material-{video_id}.tar.gz"
        create_material_bundle(bundle_path, manifest, media_files)
        try:
            upload_bundle_to_url(bundle_path, upload_url)
        except (OSError, error.URLError, TimeoutError, RuntimeError) as exc:
            raise OracleJobFailure("handoff_upload_failure", "temporary material upload failed") from exc
        _dispatch_github(video_id)
        return {
            "video_id": video_id,
            "chat_total": len(comments),
            "highlights": len(items),
            "media_bytes": sum(path.stat().st_size for path in media_files.values()),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire one YouTube archive on Oracle and hand off selected material.")
    parser.add_argument("--video-url", default=_env("YOUTUBE_ORACLE_VIDEO_URL"))
    args = parser.parse_args()
    if not args.video_url:
        raise SystemExit("YOUTUBE_ORACLE_VIDEO_URL or --video-url is required")
    try:
        result = run(args.video_url)
        _notify(None)
        print(
            "oracle YouTube job complete:"
            f" video_id={result['video_id']}"
            f" chat_offsets={result['chat_total']}"
            f" highlights={result['highlights']}"
            f" media_bytes={result['media_bytes']}"
        )
        return 0
    except OracleJobFailure as exc:
        _notify(exc.category)
        print(f"oracle YouTube job failed: category={exc.category}")
        return 1
    except Exception:
        _notify("oracle_runtime_failure")
        print("oracle YouTube job failed: category=oracle_runtime_failure")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
