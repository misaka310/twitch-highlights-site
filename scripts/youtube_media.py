"""Fetch only a selected YouTube highlight through the confirmed Oracle route.

The Oracle VM performs the yt-dlp section cut because GitHub-hosted runners are
not allowed to reach the VM over SSH.  The resulting tar stream contains one
temporary media file only; the caller owns its short-lived local work folder.
No chat, cookie, or remote filesystem data is returned.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any, Callable, Mapping

from youtube_sources import (
    YoutubeOracleConfig,
    build_oracle_command,
    parse_youtube_video_id,
    youtube_oracle_config_from_env,
)


YOUTUBE_MEDIA_TIMEOUT_ENV = "YOUTUBE_ORACLE_MEDIA_TIMEOUT_SEC"
YOUTUBE_SCREENSHOT_TIMEOUT_ENV = "YOUTUBE_ORACLE_SCREENSHOT_TIMEOUT_SEC"
YOUTUBE_REMOTE_YTDLP_ENV = "YOUTUBE_ORACLE_YTDLP_PATH"
YOUTUBE_REMOTE_DENO_ENV = "YOUTUBE_ORACLE_DENO_PATH"
YOUTUBE_REMOTE_COOKIES_ENV = "YOUTUBE_ORACLE_COOKIES_PATH"
YOUTUBE_MEDIA_INCLUDE_VIDEO_ENV = "YOUTUBE_ORACLE_MEDIA_INCLUDE_VIDEO"
DEFAULT_REMOTE_YTDLP = "$HOME/yt-dlp"
DEFAULT_REMOTE_DENO = "$HOME/.local/bin/deno"
DEFAULT_REMOTE_COOKIES = "$HOME/youtube-cookies.txt"
_SAFE_MEDIA_NAME = re.compile(r"^clip(?:-\d+)?\.[A-Za-z0-9]+$")


def build_youtube_media_script(
    video_id: str,
    start_sec: int,
    end_sec: int,
    *,
    remote_ytdlp: str = DEFAULT_REMOTE_YTDLP,
    remote_deno: str = DEFAULT_REMOTE_DENO,
    remote_cookies: str = DEFAULT_REMOTE_COOKIES,
    include_video: bool = False,
) -> str:
    """Build a quiet remote script whose stdout is a single tar archive."""

    normalized_id = parse_youtube_video_id(video_id)
    start = max(0, int(start_sec))
    end = max(start + 1, int(end_sec))
    for path in (remote_ytdlp, remote_deno, remote_cookies):
        if not str(path).startswith("/") or any(char in str(path) for char in "'\n\r"):
            raise ValueError("remote media paths must be absolute and shell-safe")
    url = f"https://www.youtube.com/watch?v={normalized_id}"
    format_selector = (
        "worstvideo[protocol=https]+worstaudio[protocol=https]/worst[protocol=https]/worst"
        if include_video
        else "worstaudio[protocol=https]/bestaudio[protocol=https]"
    )
    return f"""#!/usr/bin/env bash
set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo YOUTUBE_MEDIA_FFMPEG_MISSING >&2
  exit 78
fi

work_dir="$(mktemp -d "$HOME/ytprobe/media-{normalized_id}-{start}-{end}-XXXXXX")"
cleanup() {{ rm -rf "$work_dir"; }}
trap cleanup EXIT

"{remote_ytdlp}" \\
  --js-runtimes "deno:{remote_deno}" \\
  --remote-components ejs:github \\
  --cookies "{remote_cookies}" \\
  --force-ipv4 \\
  --quiet \\
  --no-warnings \\
  --no-progress \\
  --no-playlist \\
  --force-overwrites \\
  --download-sections "*{start}-{end}" \\
  -f "{format_selector}" \\
  -o "$work_dir/clip.%(ext)s" \\
  "{url}" >&2

media_path="$(find "$work_dir" -maxdepth 1 -type f \\
  ! -name '*.part' ! -name '*.ytdl' -print -quit)"
if [ -z "$media_path" ]; then
  echo YOUTUBE_MEDIA_OUTPUT_MISSING >&2
  exit 79
fi

tar -C "$work_dir" -cf - "$(basename "$media_path")"
"""


def youtube_media_config_from_env(env: Mapping[str, str] | None = None) -> YoutubeOracleConfig:
    source = os.environ if env is None else env
    base = youtube_oracle_config_from_env(source)
    raw_timeout = source.get(YOUTUBE_MEDIA_TIMEOUT_ENV) or source.get("YOUTUBE_ORACLE_TIMEOUT_SEC") or str(base.timeout_sec)
    try:
        timeout_sec = max(30, int(str(raw_timeout).strip()))
    except (TypeError, ValueError):
        timeout_sec = base.timeout_sec
    return YoutubeOracleConfig(
        host=base.host,
        user=base.user,
        key_path=base.key_path,
        script_path=base.script_path,
        timeout_sec=timeout_sec,
    )


def build_youtube_media_batch_script(
    video_id: str,
    intervals: list[tuple[int, int]],
    *,
    remote_ytdlp: str = DEFAULT_REMOTE_YTDLP,
    remote_deno: str = DEFAULT_REMOTE_DENO,
    remote_cookies: str = DEFAULT_REMOTE_COOKIES,
) -> str:
    """Download audio once on Oracle, then stream only selected clips."""

    normalized_id = parse_youtube_video_id(video_id)
    if not intervals:
        raise ValueError("at least one media interval is required")
    normalized_intervals: list[tuple[int, int]] = []
    for start_sec, end_sec in intervals:
        start = max(0, int(start_sec))
        end = max(start + 1, int(end_sec))
        normalized_intervals.append((start, end))
    for path in (remote_ytdlp, remote_deno, remote_cookies):
        if not str(path).startswith("/") or any(char in str(path) for char in "'\n\r"):
            raise ValueError("remote media paths must be absolute and shell-safe")
    url = f"https://www.youtube.com/watch?v={normalized_id}"
    cuts = "\n".join(
        f'ffmpeg -nostdin -y -loglevel error -ss {start} -t {end - start} -i "$source_path" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$work_dir/clip-{index}.wav"'
        for index, (start, end) in enumerate(normalized_intervals)
    )
    clip_names = " ".join(f"clip-{index}.wav" for index in range(len(normalized_intervals)))
    return f"""#!/usr/bin/env bash
set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo YOUTUBE_MEDIA_FFMPEG_MISSING >&2
  exit 78
fi

work_dir="$(mktemp -d "$HOME/ytprobe/batch-{normalized_id}-XXXXXX")"
cleanup() {{ rm -rf "$work_dir"; }}
trap cleanup EXIT

"{remote_ytdlp}" \\
  --js-runtimes "deno:{remote_deno}" \\
  --remote-components ejs:github \\
  --cookies "{remote_cookies}" \\
  --force-ipv4 \\
  --quiet \\
  --no-warnings \\
  --no-progress \\
  --no-playlist \\
  --force-overwrites \\
  -f "worstaudio[protocol=https]/bestaudio[protocol=https]" \\
  -o "$work_dir/source.%(ext)s" \\
  "{url}" >&2

source_path="$(find "$work_dir" -maxdepth 1 -type f -name 'source.*' -print -quit)"
if [ -z "$source_path" ]; then
  echo YOUTUBE_MEDIA_OUTPUT_MISSING >&2
  exit 79
fi

{cuts}
tar -C "$work_dir" -cf - {clip_names}
"""


def build_youtube_screenshot_batch_script(
    video_id: str,
    intervals: list[tuple[int, int]],
    *,
    remote_ytdlp: str = DEFAULT_REMOTE_YTDLP,
    remote_deno: str = DEFAULT_REMOTE_DENO,
    remote_cookies: str = DEFAULT_REMOTE_COOKIES,
    width: int = 192,
    height: int = 108,
    quality: int = 72,
) -> str:
    """Download a temporary low-resolution video source and return WEBP stills."""

    normalized_id = parse_youtube_video_id(video_id)
    if not intervals:
        raise ValueError("at least one screenshot interval is required")
    normalized_intervals: list[tuple[int, int]] = []
    for start_sec, end_sec in intervals:
        start = max(0, int(start_sec))
        end = max(start + 1, int(end_sec))
        normalized_intervals.append((start, end))
    for path in (remote_ytdlp, remote_deno, remote_cookies):
        if not str(path).startswith("/") or any(char in str(path) for char in "'\n\r"):
            raise ValueError("remote media paths must be absolute and shell-safe")
    if min(width, height, quality) <= 0:
        raise ValueError("screenshot dimensions and quality must be positive")
    url = f"https://www.youtube.com/watch?v={normalized_id}"
    cuts = "\n".join(
        f'ffmpeg -nostdin -y -loglevel error -ss {start} -i "$source_path" -frames:v 1 '
        f'-vf "scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black" '
        f'-c:v libwebp -q:v {quality} "$work_dir/clip-{index}.webp"'
        for index, (start, _end) in enumerate(normalized_intervals)
    )
    clip_names = " ".join(f"clip-{index}.webp" for index in range(len(normalized_intervals)))
    return f'''#!/usr/bin/env bash
set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo YOUTUBE_MEDIA_FFMPEG_MISSING >&2
  exit 78
fi

work_dir="$(mktemp -d "$HOME/ytprobe/screenshot-{normalized_id}-XXXXXX")"
cleanup() {{ rm -rf "$work_dir"; }}
trap cleanup EXIT

"{remote_ytdlp}" \\
  --js-runtimes "deno:{remote_deno}" \\
  --remote-components ejs:github \\
  --cookies "{remote_cookies}" \\
  --force-ipv4 \\
  --quiet \\
  --no-warnings \\
  --no-progress \\
  --no-playlist \\
  --force-overwrites \\
  -f "worstvideo[protocol=https]/worst[protocol=https]/worst" \\
  -o "$work_dir/source.%(ext)s" \\
  "{url}" >&2

source_path="$(find "$work_dir" -maxdepth 1 -type f -name 'source.*' -print -quit)"
if [ -z "$source_path" ]; then
  echo YOUTUBE_MEDIA_OUTPUT_MISSING >&2
  exit 79
fi

{cuts}
tar -C "$work_dir" -cf - {clip_names}
'''


def classify_youtube_media_failure(stderr: str) -> str:
    value = str(stderr or "").lower()
    if any(token in value for token in ("cookie", "sign in", "authentication", "login", "confirm you're not a bot")):
        return "authentication_cookie_failure"
    if any(token in value for token in ("challenge", "captcha", "bot")):
        return "youtube_bot_challenge_failure"
    if "ffmpeg" in value:
        return "oracle_ffmpeg_failure"
    if "yt-dlp" in value or "youtube" in value:
        return "ytdlp_failure"
    return "oracle_runtime_failure"


def fetch_youtube_segment_media_file(
    video_url: str,
    start_sec: int,
    end_sec: int,
    output_dir: Path,
    *,
    config: YoutubeOracleConfig | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> Path:
    """Fetch one media section and safely unpack it into ``output_dir``."""

    video_id = parse_youtube_video_id(video_url)
    start = max(0, int(start_sec))
    end = max(start + 1, int(end_sec))
    oracle_config = config or youtube_media_config_from_env()
    if not oracle_config.key_path.is_file():
        raise RuntimeError(f"youtube_media_auth_failure: SSH key was not found: {oracle_config.key_path}")
    if not oracle_config.script_path.is_file():
        raise RuntimeError(f"youtube_media_runtime_failure: Oracle script was not found: {oracle_config.script_path}")

    script = build_youtube_media_script(
        video_id,
        start,
        end,
        remote_ytdlp=os.environ.get(YOUTUBE_REMOTE_YTDLP_ENV, DEFAULT_REMOTE_YTDLP),
        remote_deno=os.environ.get(YOUTUBE_REMOTE_DENO_ENV, DEFAULT_REMOTE_DENO),
        remote_cookies=os.environ.get(YOUTUBE_REMOTE_COOKIES_ENV, DEFAULT_REMOTE_COOKIES),
        include_video=str(os.environ.get(YOUTUBE_MEDIA_INCLUDE_VIDEO_ENV) or "").strip().lower()
        in {"1", "true", "yes", "on"},
    )
    command = build_oracle_command(oracle_config, video_id)
    completed = runner(
        command,
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=oracle_config.timeout_sec,
        check=False,
    )
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else str(completed.stdout or "").encode()
    stderr = completed.stderr if isinstance(completed.stderr, bytes) else str(completed.stderr or "").encode()
    if completed.returncode != 0:
        reason = classify_youtube_media_failure(stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"youtube_media_{reason}: Oracle media fetch failed for {video_id}")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(stdout), mode="r:") as archive:
            members = [member for member in archive.getmembers() if member.isfile()]
            if len(members) != 1 or not _SAFE_MEDIA_NAME.fullmatch(Path(members[0].name).name):
                raise RuntimeError("youtube_media_runtime_failure: Oracle archive did not contain one safe clip")
            member = members[0]
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError("youtube_media_runtime_failure: Oracle clip could not be read")
            output_path = destination / Path(member.name).name
            output_path.write_bytes(stream.read())
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError("youtube_media_runtime_failure: invalid Oracle media archive") from exc
    if output_path.stat().st_size <= 0:
        raise RuntimeError("youtube_media_runtime_failure: Oracle clip was empty")
    return output_path


def fetch_youtube_highlight_media_files(
    video_url: str,
    intervals: list[tuple[int, int]],
    output_dir: Path,
    *,
    config: YoutubeOracleConfig | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[int, Path]:
    """Fetch a VOD's selected audio sections in one Oracle session."""

    video_id = parse_youtube_video_id(video_url)
    oracle_config = config or youtube_media_config_from_env()
    if not oracle_config.key_path.is_file():
        raise RuntimeError(f"youtube_media_auth_failure: SSH key was not found: {oracle_config.key_path}")
    if not oracle_config.script_path.is_file():
        raise RuntimeError(f"youtube_media_runtime_failure: Oracle script was not found: {oracle_config.script_path}")
    script = build_youtube_media_batch_script(
        video_id,
        intervals,
        remote_ytdlp=os.environ.get(YOUTUBE_REMOTE_YTDLP_ENV, DEFAULT_REMOTE_YTDLP),
        remote_deno=os.environ.get(YOUTUBE_REMOTE_DENO_ENV, DEFAULT_REMOTE_DENO),
        remote_cookies=os.environ.get(YOUTUBE_REMOTE_COOKIES_ENV, DEFAULT_REMOTE_COOKIES),
    )
    completed = runner(
        build_oracle_command(oracle_config, video_id),
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=oracle_config.timeout_sec,
        check=False,
    )
    stderr = completed.stderr if isinstance(completed.stderr, bytes) else str(completed.stderr or "").encode()
    if completed.returncode != 0:
        reason = classify_youtube_media_failure(stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"youtube_media_{reason}: Oracle batch media fetch failed for {video_id}")
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else str(completed.stdout or "").encode()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: dict[int, Path] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(stdout), mode="r:") as archive:
            for member in archive.getmembers():
                name = Path(member.name).name
                match = re.fullmatch(r"clip-(\d+)\.wav", name)
                if not member.isfile() or match is None:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle batch contains an unsafe clip")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle batch clip could not be read")
                output_path = destination / name
                output_path.write_bytes(stream.read())
                if output_path.stat().st_size <= 0:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle batch clip was empty")
                outputs[int(match.group(1))] = output_path
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError("youtube_media_runtime_failure: invalid Oracle batch media archive") from exc
    expected = set(range(len(intervals)))
    if set(outputs) != expected:
        raise RuntimeError("youtube_media_runtime_failure: Oracle batch did not return every selected clip")
    return outputs


def fetch_youtube_highlight_screenshot_files(
    video_url: str,
    intervals: list[tuple[int, int]],
    output_dir: Path,
    *,
    config: YoutubeOracleConfig | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[int, Path]:
    """Fetch one still image per selected highlight through Oracle."""

    video_id = parse_youtube_video_id(video_url)
    oracle_config = config or youtube_media_config_from_env()
    if not oracle_config.key_path.is_file():
        raise RuntimeError(f"youtube_media_auth_failure: SSH key was not found: {oracle_config.key_path}")
    if not oracle_config.script_path.is_file():
        raise RuntimeError(f"youtube_media_runtime_failure: Oracle script was not found: {oracle_config.script_path}")
    script = build_youtube_screenshot_batch_script(
        video_id,
        intervals,
        remote_ytdlp=os.environ.get(YOUTUBE_REMOTE_YTDLP_ENV, DEFAULT_REMOTE_YTDLP),
        remote_deno=os.environ.get(YOUTUBE_REMOTE_DENO_ENV, DEFAULT_REMOTE_DENO),
        remote_cookies=os.environ.get(YOUTUBE_REMOTE_COOKIES_ENV, DEFAULT_REMOTE_COOKIES),
    )
    completed = runner(
        build_oracle_command(oracle_config, video_id),
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=oracle_config.timeout_sec,
        check=False,
    )
    stderr = completed.stderr if isinstance(completed.stderr, bytes) else str(completed.stderr or "").encode()
    if completed.returncode != 0:
        reason = classify_youtube_media_failure(stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"youtube_media_{reason}: Oracle screenshot fetch failed for {video_id}")
    stdout = completed.stdout if isinstance(completed.stdout, bytes) else str(completed.stdout or "").encode()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: dict[int, Path] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(stdout), mode="r:") as archive:
            for member in archive.getmembers():
                name = Path(member.name).name
                match = re.fullmatch(r"clip-(\d+)\.webp", name)
                if not member.isfile() or match is None:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle screenshots contain an unsafe file")
                stream = archive.extractfile(member)
                if stream is None:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle screenshot could not be read")
                output_path = destination / name
                output_path.write_bytes(stream.read())
                if output_path.stat().st_size <= 0:
                    raise RuntimeError("youtube_media_runtime_failure: Oracle screenshot was empty")
                outputs[int(match.group(1))] = output_path
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError("youtube_media_runtime_failure: invalid Oracle screenshot archive") from exc
    expected = set(range(len(intervals)))
    if set(outputs) != expected:
        raise RuntimeError("youtube_media_runtime_failure: Oracle screenshot fetch was incomplete")
    return outputs


__all__ = [
    "DEFAULT_REMOTE_COOKIES",
    "DEFAULT_REMOTE_DENO",
    "DEFAULT_REMOTE_YTDLP",
    "YOUTUBE_MEDIA_TIMEOUT_ENV",
    "YOUTUBE_SCREENSHOT_TIMEOUT_ENV",
    "build_youtube_media_script",
    "build_youtube_media_batch_script",
    "build_youtube_screenshot_batch_script",
    "classify_youtube_media_failure",
    "fetch_youtube_segment_media_file",
    "fetch_youtube_highlight_media_files",
    "fetch_youtube_highlight_screenshot_files",
    "youtube_media_config_from_env",
]
