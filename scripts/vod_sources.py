from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import parse, request

from vod_highlights import (
    clean_html_text,
    extract_message_text,
    html_unescape,
    normalize_thumbnail_url,
    parse_twitch_duration_text,
    to_local_iso,
)


CHANNEL = ""
TWITCHMETRICS_URL = ""
TWITCH_API_CLIENT_ID = ""
TWITCH_API_CLIENT_SECRET = ""
TWITCH_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"


def configure_source(
    *,
    channel: str,
    twitchmetrics_url: str,
    client_id: str = "",
    client_secret: str = "",
    gql_client_id: str = "kimne78kx3ncx6brgo4mv6wki5h1ko",
) -> None:
    globals().update(
        CHANNEL=str(channel or "").strip(),
        TWITCHMETRICS_URL=str(twitchmetrics_url or "").strip(),
        TWITCH_API_CLIENT_ID=str(client_id or "").strip(),
        TWITCH_API_CLIENT_SECRET=str(client_secret or "").strip(),
        TWITCH_GQL_CLIENT_ID=str(gql_client_id or DEFAULT_TWITCH_GQL_CLIENT_ID).strip(),
    )

TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"

TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"

TWITCH_VIDEOS_URL = "https://api.twitch.tv/helix/videos"

TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"

TWITCH_GQL_URL = "https://gql.twitch.tv/gql"

DEFAULT_TWITCH_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

USER_AGENT = "Mozilla/5.0"

@dataclass(frozen=True)
class FetchConfig:
    max_pages: int = 60
    timeout_sec: int = 20
    sleep_sec: float = 0.05

@dataclass(frozen=True)
class ChatFetchResult:
    comments: list[dict[str, Any]]
    duration_sec: int | None = None

def fetch_current_stream_status(channel_login: str | None = None) -> dict[str, Any]:
    channel_login = str(channel_login or CHANNEL).strip()
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

def is_channel_live(channel_login: str | None = None) -> bool:
    return bool(fetch_current_stream_status(channel_login).get("live"))

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
