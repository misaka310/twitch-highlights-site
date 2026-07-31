from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import crv_compare_existing_job_v2 as v2


def download_candidate_with_cookie_file(
    *,
    url: str,
    segment: dict[str, Any],
    destination: Path,
    repository_root: Path,
) -> None:
    cookie_file = os.environ.get("CRV_COOKIE_FILE", "").strip()
    if not cookie_file or not Path(cookie_file).is_file():
        raise RuntimeError("CRV_COOKIE_FILE is not set to an existing file")

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
        "--cookies",
        cookie_file,
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
    for format_args in formats:
        for existing in destination.parent.glob(f"{candidate_id:02d}.*"):
            existing.unlink(missing_ok=True)
        command = common + format_args + ["-o", str(template), url]
        completed = subprocess.run(
            command,
            cwd=repository_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=1800,
        )
        print("+", " ".join(command[: command.index(cookie_file)]) + "<ephemeral-cookie-file> ...", flush=True)
        print(completed.stdout[-4000:], flush=True)
        if completed.returncode != 0:
            errors.append(f"exit={completed.returncode}: {completed.stdout[-1200:]}")
            continue
        created = sorted(destination.parent.glob(f"{candidate_id:02d}.*"))
        mp4 = next((path for path in created if path.suffix.lower() == ".mp4"), None)
        if mp4 is not None:
            if mp4 != destination:
                destination.unlink(missing_ok=True)
                mp4.replace(destination)
            if v2.valid_candidate_clip(destination, segment):
                return
        errors.append("output did not match requested duration")

    for existing in destination.parent.glob(f"{candidate_id:02d}.*"):
        existing.unlink(missing_ok=True)
    raise RuntimeError("candidate cookie-file download failed: " + " | ".join(errors))


v2.download_candidate = download_candidate_with_cookie_file


if __name__ == "__main__":
    raise SystemExit(v2.main())
