from __future__ import annotations

import subprocess
from pathlib import Path


def download_segment_media(
    *,
    vod_url: str,
    start_label: str,
    end_label: str,
    work_dir: Path,
    python_executable: str,
    timeout_sec: int,
) -> Path:
    output_template = work_dir / "clip.%(ext)s"
    command = [
        python_executable,
        "-m",
        "yt_dlp",
        "--force-overwrites",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--download-sections",
        f"*{start_label}-{end_label}",
        "-o",
        str(output_template),
        vod_url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_sec)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp timed out after {timeout_sec}s") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "yt-dlp failed").strip()
        raise RuntimeError(stderr[:500])

    media_files = [
        path
        for path in sorted(work_dir.iterdir())
        if path.is_file() and path.suffix not in {".part", ".ytdl"}
    ]
    if not media_files:
        raise RuntimeError("yt-dlp did not produce a media file")
    return media_files[0]

