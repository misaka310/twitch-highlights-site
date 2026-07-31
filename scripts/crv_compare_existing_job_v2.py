from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import crv_compare_existing_job as base

MIN_VALID_CANDIDATES = 20


def probe_duration(path: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
        timeout=120,
    )
    return float(completed.stdout.strip())


def source_url(job_dir: Path) -> str:
    for path in (job_dir / "project.json", job_dir / "runtime" / "source-metadata.json"):
        if not path.is_file():
            continue
        payload = base.read_json(path)
        if path.name == "project.json":
            source = payload.get("source") if isinstance(payload, dict) else None
            source = source if isinstance(source, dict) else {}
            value = source.get("url") or source.get("webpage_url")
        else:
            value = (payload.get("webpage_url") or payload.get("original_url")) if isinstance(payload, dict) else None
        if value:
            return str(value)
    raise RuntimeError("The existing job does not contain a source URL")


def candidate_duration(segment: dict[str, Any]) -> float:
    return max(0.0, float(segment["end"]) - float(segment["start"]))


def valid_candidate_clip(path: Path, segment: dict[str, Any]) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        actual = probe_duration(path)
    except Exception:
        return False
    return actual >= max(3.0, candidate_duration(segment) - 2.0)


def historical_candidates(job_dir: Path, candidate_id: int) -> list[Path]:
    paths: list[Path] = []
    history = job_dir / "history"
    if history.is_dir():
        for version in sorted(history.iterdir(), reverse=True):
            if not version.is_dir():
                continue
            for suffix in (".mp4", ".mkv", ".webm"):
                path = version / "clips" / f"{candidate_id:02d}{suffix}"
                if path.is_file():
                    paths.append(path)
    return paths


def run_capture(command: list[str], *, cwd: Path, timeout: int) -> str:
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


def download_candidate(*, url: str, segment: dict[str, Any], destination: Path, repository_root: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate_id = int(segment["id"])
    section = f"*{float(segment['start']):.3f}-{float(segment['end']):.3f}"
    template = destination.parent / f"{candidate_id:02d}.%(ext)s"
    for existing in destination.parent.glob(f"{candidate_id:02d}.*"):
        existing.unlink(missing_ok=True)
    common = [
        sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "--retries", "5",
        "--fragment-retries", "5", "--socket-timeout", "30", "--download-sections", section,
        "--force-keyframes-at-cuts",
    ]
    attempts = [
        common + [
            "-f", "bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=720]+ba/b[height<=720]",
            "--merge-output-format", "mp4", "--remux-video", "mp4", "-o", str(template), url,
        ],
        common + ["-f", "18", "-o", str(template), url],
    ]
    errors: list[str] = []
    for command in attempts:
        try:
            run_capture(command, cwd=repository_root, timeout=1800)
        except Exception as exc:
            errors.append(str(exc))
            for partial in destination.parent.glob(f"{candidate_id:02d}.*"):
                partial.unlink(missing_ok=True)
            continue
        created = sorted(destination.parent.glob(f"{candidate_id:02d}.*"))
        mp4 = next((path for path in created if path.suffix.lower() == ".mp4"), None)
        if mp4 is not None:
            if mp4 != destination:
                destination.unlink(missing_ok=True)
                mp4.replace(destination)
            if valid_candidate_clip(destination, segment):
                return
        errors.append("yt-dlp output did not match the requested candidate duration")
        for partial in destination.parent.glob(f"{candidate_id:02d}.*"):
            partial.unlink(missing_ok=True)
    raise RuntimeError("candidate download failed: " + " | ".join(errors))


def materialize_candidate_clip(
    *, job_dir: Path, segment: dict[str, Any], cache_dir: Path, url: str, repository_root: Path
) -> tuple[Path, str]:
    candidate_id = int(segment["id"])
    cached = cache_dir / f"{candidate_id:02d}.mp4"
    if valid_candidate_clip(cached, segment):
        return cached, "crv-cache"
    search: list[Path] = []
    for suffix in (".mp4", ".mkv", ".webm"):
        search.append(job_dir / "clips" / f"{candidate_id:02d}{suffix}")
    search.extend(historical_candidates(job_dir, candidate_id))
    for candidate in search:
        if valid_candidate_clip(candidate, segment):
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, cached)
            return cached, "existing-full-candidate"
    download_candidate(url=url, segment=segment, destination=cached, repository_root=repository_root)
    return cached, "downloaded-isolated-candidate"


def existing_candidate_id(row: dict[str, Any]) -> int:
    return int(row.get("source_candidate_id", row.get("candidate_id", row.get("id", 0))))


def compare_with_existing(selected: list[base.CandidateReview], existing: list[dict[str, Any]]) -> dict[str, Any]:
    exact_ids = sorted({review.candidate_id for review in selected} & {existing_candidate_id(row) for row in existing})
    timestamp_matches: list[dict[str, Any]] = []
    for review in selected:
        best_overlap = 0.0
        best_row: dict[str, Any] | None = None
        for row in existing:
            overlap = base.interval_overlap(
                review.start, review.end, float(row.get("start", 0.0)), float(row.get("end", 0.0))
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_row = row
        if best_overlap >= 1.0 and best_row is not None:
            timestamp_matches.append({
                "crv_candidate_id": review.candidate_id,
                "existing_candidate_id": existing_candidate_id(best_row),
                "overlap_seconds": round(best_overlap, 3),
            })
    return {
        "existing_scene_count": len(existing),
        "crv_scene_count": len(selected),
        "same_candidate_ids": exact_ids,
        "same_candidate_count": len(exact_ids),
        "timestamp_matches": timestamp_matches,
        "timestamp_match_count": len(timestamp_matches),
    }


def concat_pieces_validated(
    pieces: list[Path], output: Path, *, repository_root: Path, expected_duration: float
) -> dict[str, float]:
    manifest = output.parent / "concat.txt"
    manifest.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in pieces) + "\n", encoding="utf-8")
    base.run([
        "ffmpeg", "-y", "-v", "error", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-vf", "fps=30,format=yuv420p", "-af", "aresample=48000:async=1:first_pts=0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(output),
    ], cwd=repository_root, timeout=1800)
    actual_duration = probe_duration(output)
    tolerance = max(2.0, expected_duration * 0.025)
    if abs(actual_duration - expected_duration) > tolerance:
        raise RuntimeError(f"render duration mismatch: expected={expected_duration:.3f}, actual={actual_duration:.3f}")
    if output.stat().st_size < 1_000_000:
        raise RuntimeError(f"render output is unexpectedly small: {output.stat().st_size} bytes")
    return {
        "expected_duration_seconds": round(expected_duration, 3),
        "actual_duration_seconds": round(actual_duration, 3),
        "size_bytes": output.stat().st_size,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a corrected independent CRV comparison against all stream candidates.")
    parser.add_argument("--video-id", default="kIujKrO80tk")
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--select-count", type=int, default=13)
    parser.add_argument("--max-candidates", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository_root = args.repository_root.resolve() if args.repository_root else Path(__file__).resolve().parents[1]
    work_root = args.work_root.resolve() if args.work_root else repository_root / "work"
    job_dir = work_root / args.video_id
    segments_path = job_dir / "segments.json"
    runtime_dir = job_dir / "runtime"
    output_dir = job_dir / "output-crv-comparison"
    candidate_cache = runtime_dir / "crv-comparison-candidates"
    crv_root = output_dir / "crv"
    render_dir = output_dir / "render"
    review_video = output_dir / f"{args.video_id}-crv-highlight-review.mp4"
    report_json = output_dir / "comparison.json"
    report_html = output_dir / "comparison.html"
    review_board = output_dir / "selected-crv-review-board.jpg"

    for executable in ("ffmpeg", "ffprobe", "crv"):
        base.require_executable(executable)
    if not segments_path.is_file():
        raise FileNotFoundError(f"Existing candidate manifest was not found: {segments_path}")
    segments_raw = base.read_json(segments_path)
    if not isinstance(segments_raw, list) or not segments_raw:
        raise ValueError("segments.json must contain a non-empty array")
    segments = segments_raw[: max(1, args.max_candidates)]
    if len(segments) < MIN_VALID_CANDIDATES:
        raise RuntimeError(f"Too few source candidates for an independent comparison: {len(segments)}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    for directory in (output_dir, crv_root, render_dir, candidate_cache):
        directory.mkdir(parents=True, exist_ok=True)

    url = source_url(job_dir)
    subtitle_events = base.load_subtitle_events(sorted(runtime_dir.glob("subtitles*.json3")))
    existing_scenes = base.read_existing_scenes(job_dir)
    prepared: list[dict[str, Any]] = []
    for ordinal, segment in enumerate(segments, start=1):
        candidate_id = int(segment["id"])
        clip, clip_source = materialize_candidate_clip(
            job_dir=job_dir, segment=segment, cache_dir=candidate_cache, url=url, repository_root=repository_root
        )
        clip_start, clip_end, text, self_contained = base.choose_trim(segment, subtitle_events)
        grids, frame_count = base.run_crv(
            clip=clip,
            output_dir=crv_root / f"candidate-{candidate_id:02d}",
            repository_root=repository_root,
            overwrite=True,
        )
        prepared.append({
            "candidate": segment,
            "candidate_id": candidate_id,
            "clip": clip,
            "clip_source": clip_source,
            "candidate_start": float(segment["start"]),
            "candidate_end": float(segment["end"]),
            "peak": float(segment.get("peak", (float(segment["start"]) + float(segment["end"])) / 2.0)),
            "audio_score": float(segment.get("score", 0.0)),
            "clip_start": clip_start,
            "clip_end": clip_end,
            "transcript": text,
            "self_contained": self_contained,
            "grids": grids,
            "frame_count": frame_count,
            "semantic": base.semantic_raw(text),
        })
        print(
            f"candidate={candidate_id} progress={ordinal}/{len(segments)} source={clip_source} "
            f"duration={probe_duration(clip):.2f} frames={frame_count}",
            flush=True,
        )
    if len(prepared) != len(segments):
        raise RuntimeError(f"Candidate coverage is incomplete: {len(prepared)}/{len(segments)}")

    audio_norm = base.normalize([float(row["audio_score"]) for row in prepared])
    visual_norm = base.normalize([math.log1p(int(row["frame_count"])) for row in prepared])
    semantic_norm = base.normalize([float(row["semantic"]) for row in prepared])
    reviews: list[base.CandidateReview] = []
    clip_sources: dict[int, str] = {}
    for index, row in enumerate(prepared):
        score = 3.8 * audio_norm[index] + 2.8 * visual_norm[index] + 2.2 * semantic_norm[index] + (1.2 if row["self_contained"] else 0.2 if row["transcript"] else 0.0)
        score = round(max(0.0, min(10.0, score)), 3)
        label = base.clean_label(row["transcript"] or str(row["candidate"].get("label") or ""))
        reason_parts = [
            f"音量 {audio_norm[index]:.2f}",
            f"映像変化 {visual_norm[index]:.2f}（CRV {row['frame_count']}枚）",
            f"会話反応 {semantic_norm[index]:.2f}",
        ]
        if row["self_contained"]:
            reason_parts.append("会話が候補内で成立")
        start = row["candidate_start"] + row["clip_start"]
        end = row["candidate_start"] + row["clip_end"]
        review = base.CandidateReview(
            candidate_id=int(row["candidate_id"]), candidate_start=round(float(row["candidate_start"]), 3),
            candidate_end=round(float(row["candidate_end"]), 3), peak=round(float(row["peak"]), 3),
            clip_path=str(row["clip"]), audio_score=round(float(row["audio_score"]), 6),
            frame_count=int(row["frame_count"]), grid_paths=[str(path) for path in row["grids"]],
            transcript=str(row["transcript"]), label=label, reason=" / ".join(reason_parts),
            clip_start=round(float(row["clip_start"]), 3), clip_end=round(float(row["clip_end"]), 3),
            start=round(start, 3), end=round(end, 3), score=score,
            self_contained=bool(row["self_contained"]), error="",
        )
        reviews.append(review)
        clip_sources[review.candidate_id] = str(row["clip_source"])

    selected = sorted(reviews, key=lambda review: (review.score, review.frame_count, review.audio_score), reverse=True)[: max(1, min(args.select_count, len(reviews)))]
    selected.sort(key=lambda review: review.start)
    selected_ids = {review.candidate_id for review in selected}
    for review in reviews:
        review.selected = review.candidate_id in selected_ids

    pieces: list[Path] = []
    expected_duration = 0.0
    for index, review in enumerate(selected, start=1):
        pieces.extend(base.normalize_piece(
            clip=Path(review.clip_path), review=review, index=index, output_dir=render_dir, repository_root=repository_root
        ))
        expected_duration += 1.25 + (review.clip_end - review.clip_start)
    render_validation = concat_pieces_validated(
        pieces, review_video, repository_root=repository_root, expected_duration=expected_duration
    )

    comparison = compare_with_existing(selected, existing_scenes)
    existing_video = base.find_existing_review_video(job_dir)
    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_id": args.video_id,
        "method": {
            "name": "claude-real-video independent local heuristic, Oracle-free",
            "candidate_coverage": len(prepared),
            "selection_formula": {
                "audio_peak": 3.8,
                "crv_visual_change": 2.8,
                "subtitle_semantics": 2.2,
                "self_contained_bonus": 1.2,
            },
            "important_limit": "CRV is the visual extraction layer; final judgment here is a deterministic audio/visual/subtitle heuristic, not an LLM or Oracle judgment.",
        },
        "paths": {
            "existing_review_video": str(existing_video) if existing_video else None,
            "crv_review_video": str(review_video),
            "comparison_html": str(report_html),
            "review_board": str(review_board),
        },
        "render_validation": render_validation,
        "comparison": comparison,
        "selected": [{**asdict(review), "clip_source": clip_sources[review.candidate_id]} for review in selected],
        "candidates": [{**asdict(review), "clip_source": clip_sources[review.candidate_id]} for review in reviews],
        "existing_scenes": existing_scenes,
    }
    base.write_json(report_json, payload)
    base.make_review_board(selected, review_board)
    base.write_comparison_html(
        output=report_html, job_dir=job_dir, review_video=review_video, existing_video=existing_video,
        selected=selected, existing=existing_scenes, comparison=comparison,
    )
    print(f"CANDIDATE_COVERAGE={len(prepared)}/{len(segments)}", flush=True)
    print(f"RENDER_DURATION={render_validation['actual_duration_seconds']}", flush=True)
    print(f"CRV_REVIEW_VIDEO={review_video}", flush=True)
    print(f"COMPARISON_HTML={report_html}", flush=True)
    print(f"REVIEW_BOARD={review_board}", flush=True)
    print(f"COMPARISON_JSON={report_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
