from __future__ import annotations

import argparse
import math
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import crv_compare_existing_job as base
import crv_compare_existing_job_v2 as v2

DEFAULT_KEEP = 10


def current_clip(clips_dir: Path, ordinal: int) -> Path:
    for suffix in (".mp4", ".mkv", ".webm"):
        path = clips_dir / f"{ordinal:02d}{suffix}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    raise FileNotFoundError(f"Existing selected clip {ordinal:02d} was not found")


def source_candidate_id(scene: dict[str, Any]) -> int:
    return int(scene.get("source_candidate_id", scene.get("candidate_id", scene.get("id", 0))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply CRV as a post-filter to the existing Oracle-selected scene pool."
    )
    parser.add_argument("--video-id", default="kIujKrO80tk")
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--keep-count", type=int, default=DEFAULT_KEEP)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository_root = args.repository_root.resolve() if args.repository_root else Path(__file__).resolve().parents[1]
    work_root = args.work_root.resolve() if args.work_root else repository_root / "work"
    job_dir = work_root / args.video_id
    runtime_dir = job_dir / "runtime"
    clips_dir = job_dir / "clips"
    output_dir = job_dir / "output-crv-comparison"
    crv_root = output_dir / "crv-selected-pool"
    render_dir = output_dir / "render-selected-pool"
    review_video = output_dir / f"{args.video_id}-crv-postfilter-review.mp4"
    existing_copy = output_dir / f"{args.video_id}-existing-oracle-review.mp4"
    report_json = output_dir / "comparison.json"
    report_html = output_dir / "comparison.html"
    review_board = output_dir / "selected-crv-review-board.jpg"

    for executable in ("ffmpeg", "ffprobe", "crv"):
        base.require_executable(executable)
    existing_scenes = base.read_existing_scenes(job_dir)
    if not existing_scenes:
        raise RuntimeError("Existing edit-manifest.json contains no scenes")
    if not clips_dir.is_dir():
        raise FileNotFoundError(f"Selected clips directory was not found: {clips_dir}")

    segments_raw = base.read_json(job_dir / "segments.json")
    if not isinstance(segments_raw, list):
        raise ValueError("segments.json must contain an array")
    segments = {int(row["id"]): row for row in segments_raw}
    subtitles = base.load_subtitle_events(sorted(runtime_dir.glob("subtitles*.json3")))

    if output_dir.exists():
        shutil.rmtree(output_dir)
    for directory in (output_dir, crv_root, render_dir):
        directory.mkdir(parents=True, exist_ok=True)

    prepared: list[dict[str, Any]] = []
    for ordinal, scene in enumerate(existing_scenes, start=1):
        candidate_id = source_candidate_id(scene)
        clip = current_clip(clips_dir, ordinal)
        actual_duration = v2.probe_duration(clip)
        expected_duration = max(0.0, float(scene.get("end", 0.0)) - float(scene.get("start", 0.0)))
        if abs(actual_duration - expected_duration) > max(1.0, expected_duration * 0.08):
            raise RuntimeError(
                f"Selected clip mapping mismatch at ordinal {ordinal}: "
                f"candidate={candidate_id}, expected={expected_duration:.3f}, actual={actual_duration:.3f}"
            )
        grids, frame_count = base.run_crv(
            clip=clip,
            output_dir=crv_root / f"scene-{ordinal:02d}-candidate-{candidate_id:02d}",
            repository_root=repository_root,
            overwrite=True,
        )
        start = float(scene.get("start", 0.0))
        end = float(scene.get("end", start + actual_duration))
        related = base.events_for_range(subtitles, start, end)
        text = base.event_text(related)
        self_contained = len(related) >= 2 and len(text) >= 14
        segment = segments.get(candidate_id, {})
        prepared.append(
            {
                "ordinal": ordinal,
                "scene": scene,
                "candidate_id": candidate_id,
                "clip": clip,
                "duration": actual_duration,
                "grids": grids,
                "frame_count": frame_count,
                "transcript": text,
                "self_contained": self_contained,
                "audio_score": float(segment.get("score", 0.0)),
                "semantic": base.semantic_raw(text),
            }
        )
        print(
            f"selected_pool_scene={ordinal}/{len(existing_scenes)} candidate={candidate_id} "
            f"duration={actual_duration:.3f} crv_frames={frame_count}",
            flush=True,
        )

    audio_norm = base.normalize([float(row["audio_score"]) for row in prepared])
    visual_norm = base.normalize([math.log1p(int(row["frame_count"])) for row in prepared])
    semantic_norm = base.normalize([float(row["semantic"]) for row in prepared])
    reviews: list[base.CandidateReview] = []
    ordinal_by_candidate: dict[int, int] = {}
    for index, row in enumerate(prepared):
        score = (
            3.8 * audio_norm[index]
            + 3.2 * visual_norm[index]
            + 2.0 * semantic_norm[index]
            + (1.0 if row["self_contained"] else 0.2 if row["transcript"] else 0.0)
        )
        score = round(max(0.0, min(10.0, score)), 3)
        scene = row["scene"]
        label = base.clean_label(row["transcript"] or str(scene.get("label") or ""))
        reason = " / ".join(
            [
                f"音量 {audio_norm[index]:.2f}",
                f"映像変化 {visual_norm[index]:.2f}（CRV {row['frame_count']}枚）",
                f"会話反応 {semantic_norm[index]:.2f}",
                "会話が場面内で成立" if row["self_contained"] else "会話の独立性は弱め",
            ]
        )
        duration = float(row["duration"])
        review = base.CandidateReview(
            candidate_id=int(row["candidate_id"]),
            candidate_start=round(float(scene.get("start", 0.0)), 3),
            candidate_end=round(float(scene.get("end", 0.0)), 3),
            peak=round(float(scene.get("start", 0.0)) + duration / 2.0, 3),
            clip_path=str(row["clip"]),
            audio_score=round(float(row["audio_score"]), 6),
            frame_count=int(row["frame_count"]),
            grid_paths=[str(path) for path in row["grids"]],
            transcript=str(row["transcript"]),
            label=label,
            reason=reason,
            clip_start=0.0,
            clip_end=round(duration, 3),
            start=round(float(scene.get("start", 0.0)), 3),
            end=round(float(scene.get("end", 0.0)), 3),
            score=score,
            self_contained=bool(row["self_contained"]),
            error="",
        )
        reviews.append(review)
        ordinal_by_candidate[review.candidate_id] = int(row["ordinal"])

    keep_count = max(1, min(args.keep_count, len(reviews)))
    selected = sorted(
        reviews,
        key=lambda review: (review.score, review.frame_count, review.audio_score),
        reverse=True,
    )[:keep_count]
    selected.sort(key=lambda review: review.start)
    selected_ids = {review.candidate_id for review in selected}
    for review in reviews:
        review.selected = review.candidate_id in selected_ids
    dropped = sorted(
        (review for review in reviews if not review.selected),
        key=lambda review: review.start,
    )

    pieces: list[Path] = []
    expected_render_duration = 0.0
    for index, review in enumerate(selected, start=1):
        pieces.extend(
            base.normalize_piece(
                clip=Path(review.clip_path),
                review=review,
                index=index,
                output_dir=render_dir,
                repository_root=repository_root,
            )
        )
        expected_render_duration += 1.25 + (review.clip_end - review.clip_start)
    render_validation = v2.concat_pieces_validated(
        pieces,
        review_video,
        repository_root=repository_root,
        expected_duration=expected_render_duration,
    )

    existing_video = base.find_existing_review_video(job_dir)
    if existing_video is None:
        raise FileNotFoundError("Existing Oracle review video was not found")
    shutil.copy2(existing_video, existing_copy)
    existing_copy_validation = {
        "duration_seconds": round(v2.probe_duration(existing_copy), 3),
        "size_bytes": existing_copy.stat().st_size,
    }

    comparison = {
        "existing_scene_count": len(existing_scenes),
        "crv_scene_count": len(selected),
        "same_candidate_ids": sorted(selected_ids),
        "same_candidate_count": len(selected_ids),
        "dropped_candidate_ids": [review.candidate_id for review in dropped],
        "dropped_count": len(dropped),
        "scope": "CRV post-filter over the existing Oracle-selected 13-scene pool",
    }
    payload = {
        "schema_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_id": args.video_id,
        "method": {
            "name": "claude-real-video deterministic post-filter",
            "oracle_called_in_this_run": False,
            "input_pool_was_oracle_selected": True,
            "selection_formula": {
                "audio_peak": 3.8,
                "crv_visual_change": 3.2,
                "subtitle_semantics": 2.0,
                "self_contained_bonus": 1.0,
            },
            "important_limit": (
                "This compares adding CRV after the existing Oracle selection. "
                "It does not prove that CRV can replace Oracle for full-stream candidate selection."
            ),
        },
        "paths": {
            "existing_review_video": str(existing_copy),
            "crv_review_video": str(review_video),
            "comparison_html": str(report_html),
            "review_board": str(review_board),
        },
        "render_validation": render_validation,
        "existing_copy_validation": existing_copy_validation,
        "comparison": comparison,
        "selected": [
            {**asdict(review), "existing_scene_ordinal": ordinal_by_candidate[review.candidate_id]}
            for review in selected
        ],
        "dropped": [
            {**asdict(review), "existing_scene_ordinal": ordinal_by_candidate[review.candidate_id]}
            for review in dropped
        ],
        "rescored_pool": [
            {**asdict(review), "existing_scene_ordinal": ordinal_by_candidate[review.candidate_id]}
            for review in reviews
        ],
        "existing_scenes": existing_scenes,
    }
    base.write_json(report_json, payload)
    base.make_review_board(selected, review_board)
    base.write_comparison_html(
        output=report_html,
        job_dir=job_dir,
        review_video=review_video,
        existing_video=existing_copy,
        selected=selected,
        existing=existing_scenes,
        comparison={
            "existing_scene_count": len(existing_scenes),
            "crv_scene_count": len(selected),
            "same_candidate_count": len(selected_ids),
            "timestamp_match_count": len(selected_ids),
        },
    )
    print(f"COMPARISON_SCOPE=existing-selected-pool", flush=True)
    print(f"SELECTED_IDS={','.join(map(str, sorted(selected_ids)))}", flush=True)
    print(f"DROPPED_IDS={','.join(str(review.candidate_id) for review in dropped)}", flush=True)
    print(f"RENDER_DURATION={render_validation['actual_duration_seconds']}", flush=True)
    print(f"CRV_REVIEW_VIDEO={review_video}", flush=True)
    print(f"EXISTING_REVIEW_COPY={existing_copy}", flush=True)
    print(f"COMPARISON_HTML={report_html}", flush=True)
    print(f"REVIEW_BOARD={review_board}", flush=True)
    print(f"COMPARISON_JSON={report_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
