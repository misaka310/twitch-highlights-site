from __future__ import annotations

import argparse
import html
import json
import math
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REACTION_WORDS = (
    "うわ", "えっ", "やば", "怖", "痛", "無理", "待って", "なんで",
    "嘘", "マジ", "笑", "草", "ふふ", "違", "逆", "失礼", "最悪",
)
SETUP_WORDS = ("絶対", "余裕", "大丈夫", "できる", "簡単", "だったら", "けど", "なのに")


@dataclass
class CandidateReview:
    candidate_id: int
    candidate_start: float
    candidate_end: float
    peak: float
    clip_path: str
    audio_score: float
    frame_count: int
    grid_paths: list[str]
    transcript: str
    label: str
    reason: str
    clip_start: float
    clip_end: float
    start: float
    end: float
    score: float
    self_contained: bool
    selected: bool = False
    error: str = ""


def run(command: list[str], *, cwd: Path, timeout: int = 1800) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_subtitle_events(paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        payload = read_json(path)
        for event in payload.get("events", []):
            start = float(event.get("tStartMs", 0)) / 1000.0
            duration = float(event.get("dDurationMs", 0)) / 1000.0
            text = "".join(str(segment.get("utf8", "")) for segment in event.get("segs", []))
            text = " ".join(text.replace("\n", " ").split()).strip()
            if text:
                events.append({"start": start, "end": start + duration, "text": text})
    return sorted(events, key=lambda event: float(event["start"]))


def require_executable(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} was not found on PATH")


def clean_text(value: str) -> str:
    return " ".join(str(value).replace("\n", " ").split()).strip()


def clean_label(value: str, limit: int = 34) -> str:
    text = clean_text(value).strip(" -–—。、,.!！?？")
    if not text:
        return "映像変化の大きい場面"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def event_text(events: list[dict[str, Any]]) -> str:
    return clean_text(" ".join(str(event.get("text") or "") for event in events))


def events_for_range(events: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if float(event.get("end", 0.0)) >= start and float(event.get("start", 0.0)) <= end
    ]


def choose_trim(candidate: dict[str, Any], events: list[dict[str, Any]]) -> tuple[float, float, str, bool]:
    candidate_start = float(candidate["start"])
    candidate_end = float(candidate["end"])
    duration = max(0.0, candidate_end - candidate_start)
    peak = float(candidate.get("peak", (candidate_start + candidate_end) / 2.0))
    related = events_for_range(events, candidate_start, candidate_end)

    if not related:
        source_start = max(candidate_start, peak - 8.0)
        source_end = min(candidate_end, peak + 10.0)
        if source_end - source_start < min(8.0, duration):
            source_start = candidate_start
            source_end = candidate_end
        return round(source_start - candidate_start, 3), round(source_end - candidate_start, 3), "", False

    anchor_index = min(
        range(len(related)),
        key=lambda index: abs(
            (float(related[index].get("start", 0.0)) + float(related[index].get("end", 0.0))) / 2.0 - peak
        ),
    )
    first = anchor_index
    while first > 0:
        gap = float(related[first].get("start", 0.0)) - float(related[first - 1].get("end", 0.0))
        span = float(related[anchor_index].get("start", 0.0)) - float(related[first - 1].get("start", 0.0))
        if gap > 1.6 or span > 10.0:
            break
        first -= 1

    last = anchor_index
    while last + 1 < len(related):
        gap = float(related[last + 1].get("start", 0.0)) - float(related[last].get("end", 0.0))
        span = float(related[last + 1].get("end", 0.0)) - float(related[anchor_index].get("end", 0.0))
        if gap > 1.8 or span > 8.0:
            break
        last += 1

    selected_events = related[first : last + 1]
    source_start = max(candidate_start, float(selected_events[0].get("start", candidate_start)) - 0.35)
    source_end = min(candidate_end, float(selected_events[-1].get("end", candidate_end)) + 0.45)
    if source_end - source_start < 8.0:
        center = min(max(peak, source_start + 4.0), source_end - 4.0)
        source_start = max(candidate_start, center - 4.0)
        source_end = min(candidate_end, source_start + 8.0)
        source_start = max(candidate_start, source_end - 8.0)
    if source_end - source_start > 22.0:
        source_start = max(candidate_start, peak - 11.0)
        source_end = min(candidate_end, source_start + 22.0)
        source_start = max(candidate_start, source_end - 22.0)

    text = event_text(selected_events)
    self_contained = len(selected_events) >= 2 and len(text) >= 14
    return round(source_start - candidate_start, 3), round(source_end - candidate_start, 3), text, self_contained


def semantic_raw(text: str) -> float:
    value = clean_text(text)
    lowered = value.lower()
    score = sum(lowered.count(word.lower()) for word in REACTION_WORDS) * 1.8
    score += sum(lowered.count(word.lower()) for word in SETUP_WORDS) * 1.0
    score += min(3.0, value.count("?") + value.count("？") + value.count("!") + value.count("！"))
    if 18 <= len(value) <= 220:
        score += 2.0
    elif value:
        score += 0.5
    if "けど" in value or "なのに" in value or "逆" in value:
        score += 1.2
    return score


def normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if math.isclose(low, high):
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def locate_clip(clips_dir: Path, candidate_id: int) -> Path | None:
    direct = clips_dir / f"{candidate_id:02d}.mp4"
    if direct.is_file() and direct.stat().st_size > 0:
        return direct
    matches = sorted(clips_dir.glob(f"{candidate_id:02d}.*"))
    return next((path for path in matches if path.is_file() and path.stat().st_size > 0), None)


def run_crv(*, clip: Path, output_dir: Path, repository_root: Path, overwrite: bool) -> tuple[list[Path], int]:
    frames_dir = output_dir / "frames"
    grids_dir = output_dir / "grids"
    if overwrite and output_dir.exists():
        shutil.rmtree(output_dir)
    if not frames_dir.is_dir() or not list(frames_dir.glob("*.jpg")):
        command = [
            "crv", str(clip), "-o", str(output_dir), "--grid", "--viewer", "--no-transcribe",
            "--max-frames", "27", "--why",
            "配信ハイライトとして、映像変化・出来事・反応が単独の場面として成立するか比較する",
        ]
        if output_dir.exists():
            command.append("--overwrite")
        run(command, cwd=repository_root, timeout=900)
    frames = sorted(frames_dir.glob("*.jpg"))
    grids = sorted(grids_dir.glob("*.jpg"))
    if not frames:
        raise RuntimeError("CRV did not create any frames")
    return grids, len(frames)


def font_path() -> Path:
    candidates = (
        Path(r"C:\Windows\Fonts\YuGothB.ttc"),
        Path(r"C:\Windows\Fonts\meiryob.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    return next((path for path in candidates if path.is_file()), candidates[-1])


def make_title_card(review: CandidateReview, index: int, output: Path) -> None:
    image = Image.new("RGB", (1280, 720), (18, 18, 22))
    draw = ImageDraw.Draw(image)
    font = font_path()
    title_font = ImageFont.truetype(str(font), 50)
    body_font = ImageFont.truetype(str(font), 30)
    small_font = ImageFont.truetype(str(font), 25)
    draw.text((72, 105), f"{index:02d}  {review.label}", font=title_font, fill=(245, 245, 245))
    draw.text((74, 205), f"{review.start:.2f} – {review.end:.2f} sec   CRV score {review.score:.2f}", font=small_font, fill=(185, 185, 198))
    lines: list[str] = []
    current = ""
    for character in review.reason:
        current += character
        if len(current) >= 34:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    draw.multiline_text((74, 300), "\n".join(lines[:5]), font=body_font, fill=(220, 220, 225), spacing=12)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def normalize_piece(*, clip: Path, review: CandidateReview, index: int, output_dir: Path, repository_root: Path) -> list[Path]:
    title_png = output_dir / f"title-{index:02d}.png"
    title_mp4 = output_dir / f"title-{index:02d}.mp4"
    scene_mp4 = output_dir / f"scene-{index:02d}.mp4"
    make_title_card(review, index, title_png)
    run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", "1.25", "-i", str(title_png),
        "-f", "lavfi", "-t", "1.25", "-i", "anullsrc=r=48000:cl=stereo", "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
        "-shortest", str(title_mp4),
    ], cwd=repository_root, timeout=300)
    duration = max(1.5, review.clip_end - review.clip_start)
    run([
        "ffmpeg", "-y", "-v", "error", "-ss", f"{review.clip_start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(clip), "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
        "-af", "aresample=48000", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", str(scene_mp4),
    ], cwd=repository_root, timeout=600)
    return [title_mp4, scene_mp4]


def concat_pieces(pieces: list[Path], output: Path, *, repository_root: Path) -> None:
    manifest = output.parent / "concat.txt"
    manifest.write_text("\n".join(f"file '{path.resolve().as_posix()}'" for path in pieces) + "\n", encoding="utf-8")
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-c", "copy", "-movflags", "+faststart", str(output),
    ], cwd=repository_root, timeout=1200)


def read_existing_scenes(job_dir: Path) -> list[dict[str, Any]]:
    path = job_dir / "edit-manifest.json"
    if not path.is_file():
        return []
    payload = read_json(path)
    rows = payload.get("scenes") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def interval_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def compare_with_existing(selected: list[CandidateReview], existing: list[dict[str, Any]]) -> dict[str, Any]:
    exact_ids = sorted(
        set(review.candidate_id for review in selected)
        & set(int(row.get("candidate_id", row.get("id", 0))) for row in existing)
    )
    timestamp_matches: list[dict[str, Any]] = []
    for review in selected:
        best: tuple[float, dict[str, Any] | None] = (0.0, None)
        for row in existing:
            overlap = interval_overlap(review.start, review.end, float(row.get("start", 0.0)), float(row.get("end", 0.0)))
            if overlap > best[0]:
                best = overlap, row
        if best[0] >= 1.0 and best[1] is not None:
            timestamp_matches.append({
                "crv_candidate_id": review.candidate_id,
                "existing_candidate_id": int(best[1].get("candidate_id", best[1].get("id", 0))),
                "overlap_seconds": round(best[0], 3),
            })
    return {
        "existing_scene_count": len(existing), "crv_scene_count": len(selected),
        "same_candidate_ids": exact_ids, "same_candidate_count": len(exact_ids),
        "timestamp_matches": timestamp_matches, "timestamp_match_count": len(timestamp_matches),
    }


def make_review_board(selected: list[CandidateReview], output: Path) -> None:
    width, cell_width, cell_height, columns = 1600, 520, 330, 3
    rows = math.ceil(len(selected) / columns)
    image = Image.new("RGB", (width, rows * cell_height + 100), (22, 22, 26))
    draw = ImageDraw.Draw(image)
    font = font_path()
    title_font = ImageFont.truetype(str(font), 34)
    body_font = ImageFont.truetype(str(font), 23)
    draw.text((40, 28), "CRV比較版 採用候補一覧", font=title_font, fill=(245, 245, 245))
    for index, review in enumerate(selected):
        x = (index % columns) * cell_width + 20
        y = (index // columns) * cell_height + 90
        grid = next((Path(path) for path in review.grid_paths if Path(path).is_file()), None)
        if grid is not None:
            with Image.open(grid) as source:
                thumbnail = source.convert("RGB")
                thumbnail.thumbnail((480, 245))
                image.paste(thumbnail, (x, y))
        draw.text((x, y + 250), f"{index + 1:02d} / candidate {review.candidate_id:02d} / {review.score:.2f}", font=body_font, fill=(235, 235, 235))
        draw.text((x, y + 282), clean_label(review.label, 24), font=body_font, fill=(190, 210, 235))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=90)


def write_comparison_html(*, output: Path, job_dir: Path, review_video: Path, existing_video: Path | None, selected: list[CandidateReview], existing: list[dict[str, Any]], comparison: dict[str, Any]) -> None:
    def relative(path: Path) -> str:
        return Path(os.path.relpath(path, output.parent)).as_posix()
    existing_video_html = (
        f'<video controls preload="metadata" src="{html.escape(relative(existing_video))}"></video>'
        if existing_video is not None else "<p>既存レビュー動画が見つかりませんでした。</p>"
    )
    rows = "".join(
        "<tr>" f"<td>{review.candidate_id}</td>" f"<td>{review.start:.2f}–{review.end:.2f}</td>"
        f"<td>{review.score:.2f}</td>" f"<td>{html.escape(review.label)}</td>"
        f"<td>{html.escape(review.reason)}</td>" f"<td>{review.frame_count}</td>" "</tr>"
        for review in selected
    )
    existing_rows = "".join(
        "<tr>" f"<td>{int(row.get('candidate_id', row.get('id', 0)))}</td>"
        f"<td>{float(row.get('start', 0.0)):.2f}–{float(row.get('end', 0.0)):.2f}</td>"
        f"<td>{html.escape(str(row.get('label') or ''))}</td>" f"<td>{float(row.get('score', 0.0)):.2f}</td>" "</tr>"
        for row in existing
    )
    output.write_text(f"""<!doctype html><html lang="ja"><meta charset="utf-8"><title>CRV comparison</title>
<style>body{{font-family:system-ui,'Yu Gothic UI',sans-serif;margin:28px;background:#111;color:#eee}}.videos{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}video{{width:100%;background:#000}}table{{border-collapse:collapse;width:100%;margin:18px 0}}th,td{{border:1px solid #444;padding:8px;vertical-align:top}}th{{background:#252525}}.summary{{padding:14px;background:#1d2b22;border-left:4px solid #65a875}}code{{background:#222;padding:2px 5px}}</style>
<h1>同一配信の比較</h1><p><code>{html.escape(job_dir.name)}</code></p>
<div class="summary">既存版 {comparison['existing_scene_count']}場面 / CRV版 {comparison['crv_scene_count']}場面 / 同じcandidate ID {comparison['same_candidate_count']}件 / 時刻重複 {comparison['timestamp_match_count']}件</div>
<div class="videos"><section><h2>既存版</h2>{existing_video_html}</section><section><h2>CRV版</h2><video controls preload="metadata" src="{html.escape(relative(review_video))}"></video></section></div>
<h2>CRV版の採用場面</h2><table><thead><tr><th>ID</th><th>時刻</th><th>点</th><th>ラベル</th><th>理由</th><th>CRV frames</th></tr></thead><tbody>{rows}</tbody></table>
<h2>既存版の採用場面</h2><table><thead><tr><th>ID</th><th>時刻</th><th>ラベル</th><th>点</th></tr></thead><tbody>{existing_rows}</tbody></table></html>""", encoding="utf-8")


def find_existing_review_video(job_dir: Path) -> Path | None:
    output_dir = job_dir / "output"
    preferred = sorted(output_dir.glob("*highlight-review*.mp4"))
    if preferred:
        return preferred[0]
    candidates = sorted(output_dir.glob("*.mp4"))
    return candidates[0] if candidates else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run claude-real-video against an existing stream-highlight job without Oracle.")
    parser.add_argument("--video-id", default="kIujKrO80tk")
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--select-count", type=int, default=13)
    parser.add_argument("--max-candidates", type=int, default=30)
    parser.add_argument("--overwrite-crv", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository_root = args.repository_root.resolve() if args.repository_root else Path(__file__).resolve().parents[1]
    work_root = args.work_root.resolve() if args.work_root else repository_root / "work"
    job_dir = work_root / args.video_id
    segments_path, clips_dir, runtime_dir = job_dir / "segments.json", job_dir / "clips", job_dir / "runtime"
    output_dir = job_dir / "output-crv-comparison"
    crv_root, render_dir = output_dir / "crv", output_dir / "render"
    review_video = output_dir / f"{args.video_id}-crv-highlight-review.mp4"
    report_json, report_html = output_dir / "comparison.json", output_dir / "comparison.html"
    review_board = output_dir / "selected-crv-review-board.jpg"

    for executable in ("ffmpeg", "ffprobe", "crv"):
        require_executable(executable)
    if not segments_path.is_file():
        raise FileNotFoundError(f"Existing candidate manifest was not found: {segments_path}")
    if not clips_dir.is_dir():
        raise FileNotFoundError(f"Existing candidate clips were not found: {clips_dir}")
    for directory in (output_dir, crv_root, render_dir):
        directory.mkdir(parents=True, exist_ok=True)

    raw_segments = read_json(segments_path)
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("segments.json must contain a non-empty array")
    segments = raw_segments[: max(1, args.max_candidates)]
    subtitle_events = load_subtitle_events(sorted(runtime_dir.glob("subtitles*.json3")))
    existing_scenes = read_existing_scenes(job_dir)

    prepared: list[dict[str, Any]] = []
    for candidate in segments:
        candidate_id = int(candidate["id"])
        clip = locate_clip(clips_dir, candidate_id)
        if clip is None:
            print(f"skip candidate {candidate_id}: clip not found", flush=True)
            continue
        candidate_start, candidate_end = float(candidate["start"]), float(candidate["end"])
        clip_start, clip_end, text, self_contained = choose_trim(candidate, subtitle_events)
        grids: list[Path] = []
        frame_count = 0
        error = ""
        try:
            grids, frame_count = run_crv(clip=clip, output_dir=crv_root / f"candidate-{candidate_id:02d}", repository_root=repository_root, overwrite=args.overwrite_crv)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"candidate {candidate_id} CRV failed: {error}", flush=True)
        prepared.append({
            "candidate": candidate, "candidate_id": candidate_id, "clip": clip,
            "candidate_start": candidate_start, "candidate_end": candidate_end,
            "peak": float(candidate.get("peak", (candidate_start + candidate_end) / 2.0)),
            "audio_score": float(candidate.get("score", 0.0)), "clip_start": clip_start, "clip_end": clip_end,
            "transcript": text, "self_contained": self_contained, "grids": grids,
            "frame_count": frame_count, "semantic": semantic_raw(text), "error": error,
        })
    if not prepared:
        raise RuntimeError("No existing candidate clips could be reviewed")

    audio_norm = normalize([float(row["audio_score"]) for row in prepared])
    visual_norm = normalize([math.log1p(int(row["frame_count"])) for row in prepared])
    semantic_norm = normalize([float(row["semantic"]) for row in prepared])
    reviews: list[CandidateReview] = []
    for index, row in enumerate(prepared):
        score = 3.8 * audio_norm[index] + 2.8 * visual_norm[index] + 2.2 * semantic_norm[index] + (1.2 if row["self_contained"] else 0.2 if row["transcript"] else 0.0)
        if row["error"]:
            score -= 0.8
        score = round(max(0.0, min(10.0, score)), 3)
        label = clean_label(row["transcript"] or str(row["candidate"].get("label") or ""))
        reason_parts = [f"音量 {audio_norm[index]:.2f}", f"映像変化 {visual_norm[index]:.2f}（CRV {row['frame_count']}枚）", f"会話反応 {semantic_norm[index]:.2f}"]
        if row["self_contained"]:
            reason_parts.append("会話が候補内で成立")
        if row["error"]:
            reason_parts.append("CRV失敗あり")
        start, end = row["candidate_start"] + row["clip_start"], row["candidate_start"] + row["clip_end"]
        reviews.append(CandidateReview(
            candidate_id=int(row["candidate_id"]), candidate_start=round(float(row["candidate_start"]), 3),
            candidate_end=round(float(row["candidate_end"]), 3), peak=round(float(row["peak"]), 3),
            clip_path=str(row["clip"]), audio_score=round(float(row["audio_score"]), 6),
            frame_count=int(row["frame_count"]), grid_paths=[str(path) for path in row["grids"]],
            transcript=str(row["transcript"]), label=label, reason=" / ".join(reason_parts),
            clip_start=round(float(row["clip_start"]), 3), clip_end=round(float(row["clip_end"]), 3),
            start=round(start, 3), end=round(end, 3), score=score,
            self_contained=bool(row["self_contained"]), error=str(row["error"]),
        ))

    selected = sorted(reviews, key=lambda review: (review.score, review.frame_count, review.audio_score), reverse=True)[: max(1, min(args.select_count, len(reviews)))]
    selected.sort(key=lambda review: review.start)
    selected_ids = {review.candidate_id for review in selected}
    for review in reviews:
        review.selected = review.candidate_id in selected_ids

    pieces: list[Path] = []
    for index, review in enumerate(selected, start=1):
        pieces.extend(normalize_piece(clip=Path(review.clip_path), review=review, index=index, output_dir=render_dir, repository_root=repository_root))
    concat_pieces(pieces, review_video, repository_root=repository_root)

    comparison = compare_with_existing(selected, existing_scenes)
    existing_video = find_existing_review_video(job_dir)
    payload = {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "video_id": args.video_id,
        "method": {"name": "claude-real-video local heuristic, Oracle-free", "selection_formula": {"audio_peak": 3.8, "crv_visual_change": 2.8, "subtitle_semantics": 2.2, "self_contained_bonus": 1.2}},
        "paths": {"existing_review_video": str(existing_video) if existing_video else None, "crv_review_video": str(review_video), "comparison_html": str(report_html), "review_board": str(review_board)},
        "comparison": comparison, "selected": [asdict(review) for review in selected],
        "candidates": [asdict(review) for review in reviews], "existing_scenes": existing_scenes,
    }
    write_json(report_json, payload)
    make_review_board(selected, review_board)
    write_comparison_html(output=report_html, job_dir=job_dir, review_video=review_video, existing_video=existing_video, selected=selected, existing=existing_scenes, comparison=comparison)
    print(f"CRV_REVIEW_VIDEO={review_video}", flush=True)
    print(f"COMPARISON_HTML={report_html}", flush=True)
    print(f"REVIEW_BOARD={review_board}", flush=True)
    print(f"COMPARISON_JSON={report_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
