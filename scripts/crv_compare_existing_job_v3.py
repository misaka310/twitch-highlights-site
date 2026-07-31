from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import crv_compare_existing_job_v2 as v2


def run_attempt(command: list[str], *, cwd: Path, timeout: int) -> str:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode})\n{completed.stdout[-6000:]}")
    return completed.stdout


def download_candidate_with_browser_cookies(
    *,
    url: str,
    segment: dict[str, Any],
    destination: Path,
    repository_root: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate_id = int(segment["id"])
    section = f"*{float(segment['start']):.3f}-{float(segment['end']):.3f}"
    template = destination.parent / f"{candidate_id:02d}.%(ext)s"

    common = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--no-warnings",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--socket-timeout",
        "30",
        "--download-sections",
        section,
        "--force-keyframes-at-cuts",
    ]
    formats = [
        [
            "-f",
            "bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
        ],
        ["-f", "18"],
    ]
    errors: list[str] = []
    for browser in ("brave", "chrome", "edge"):
        for format_args in formats:
            for existing in destination.parent.glob(f"{candidate_id:02d}.*"):
                existing.unlink(missing_ok=True)
            command = common + ["--cookies-from-browser", browser] + format_args + ["-o", str(template), url]
            try:
                run_attempt(command, cwd=repository_root, timeout=1800)
            except Exception as exc:
                errors.append(f"{browser}: {exc}")
                continue
            created = sorted(destination.parent.glob(f"{candidate_id:02d}.*"))
            mp4 = next((path for path in created if path.suffix.lower() == ".mp4"), None)
            if mp4 is not None:
                if mp4 != destination:
                    destination.unlink(missing_ok=True)
                    mp4.replace(destination)
                if v2.valid_candidate_clip(destination, segment):
                    print(f"candidate={candidate_id} browser_cookie_source={browser}", flush=True)
                    return
            errors.append(f"{browser}: output did not match requested duration")

    for existing in destination.parent.glob(f"{candidate_id:02d}.*"):
        existing.unlink(missing_ok=True)
    raise RuntimeError("candidate browser-cookie download failed: " + " | ".join(errors))


v2.download_candidate = download_candidate_with_browser_cookies


if __name__ == "__main__":
    raise SystemExit(v2.main())
