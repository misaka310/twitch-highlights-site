from __future__ import annotations

import subprocess
from pathlib import Path


def capture_segment_screenshot(
    *,
    output_path: Path,
    media_path: Path,
    seek_sec: float,
    width: int,
    height: int,
    quality: int,
    timeout_sec: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    scale_filter = (
        f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
        f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{float(seek_sec):.3f}",
        "-i",
        str(media_path),
        "-frames:v",
        "1",
        "-vf",
        scale_filter,
        "-c:v",
        "libwebp",
        "-quality",
        str(int(quality)),
        "-compression_level",
        "6",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=max(1, int(timeout_sec)),
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "ffmpeg screenshot failed").strip()
        raise RuntimeError(stderr[:300])
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("ffmpeg screenshot output missing")

