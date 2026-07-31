from __future__ import annotations

import argparse
import array
import base64
import html
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

from openai import OpenAI


VIDEO_ID = "kIujKrO80tk"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
ORACLE_IDS = [1, 3, 9, 11, 12, 13, 15, 16, 18, 20, 24, 26, 30]
MODEL_CANDIDATES = [
    "qwen/qwen3.6-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
]


def run(command: list[str], *, cwd: Path, timeout: int = 7200) -> str:
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-12000:]}"
        )
    return completed.stdout


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metadata(url: str, root: Path) -> dict[str, Any]:
    return json.loads(
        run(
            [sys.executable, "-m", "yt_dlp", "--dump-single-json", "--no-playlist", "--no-warnings", url],
            cwd=root,
            timeout=300,
        )
    )


def download_audio(url: str, runtime: Path, root: Path) -> Path:
    runtime.mkdir(parents=True, exist_ok=True)
    existing = sorted(runtime.glob("source-audio.*"))
    if existing:
        return existing[0]
    run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "-f",
            "ba/b",
            "-x",
            "--audio-format",
            "m4a",
            "-o",
            str(runtime / "source-audio.%(ext)s"),
            url,
        ],
        cwd=root,
        timeout=7200,
    )
    created = sorted(runtime.glob("source-audio.*"))
    if not created:
        raise RuntimeError("audio was not downloaded")
    return created[0]


def download_subtitles(url: str, runtime: Path, root: Path) -> list[Path]:
    existing = sorted(runtime.glob("subtitles*.json3"))
    if existing:
        return existing
    try:
        run(
            [
                sys.executable,
                "-m",
                "yt_dlp",
                "--no-playlist",
                "--no-warnings",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-format",
                "json3",
                "--sub-langs",
                "ja.*",
                "-o",
                str(runtime / "subtitles"),
                url,
            ],
            cwd=root,
            timeout=900,
        )
    except RuntimeError as exc:
        print(f"subtitle download skipped: {exc}", flush=True)
    return sorted(runtime.glob("subtitles*.json3"))


def subtitle_events(paths: list[Path]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for event in payload.get("events", []):
            start = float(event.get("tStartMs", 0)) / 1000
            duration = float(event.get("dDurationMs", 0)) / 1000
            text = "".join(str(item.get("utf8", "")) for item in event.get("segs", []))
            text = " ".join(text.replace("\n", " ").split()).strip()
            if text:
                result.append({"start": start, "end": start + duration, "text": text})
    result.sort(key=lambda item: item["start"])
    return result


def audio_levels(path: Path, root: Path, *, window: float = 0.5, rate: int = 16000) -> list[float]:
    samples_per_window = max(1, round(rate * window))
    bytes_per_window = samples_per_window * 2
    process = subprocess.Popen(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "s16le",
            "pipe:1",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    levels: list[float] = []
    while True:
        chunk = process.stdout.read(bytes_per_window)
        if not chunk:
            break
        samples = array.array("h")
        samples.frombytes(chunk[: len(chunk) - len(chunk) % 2])
        if not samples:
            continue
        rms = math.sqrt(sum(float(value) ** 2 for value in samples) / len(samples))
        levels.append(math.log10(max(1.0, rms)))
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    code = process.wait()
    if code != 0 or not levels:
        raise RuntimeError(f"audio analysis failed ({code}): {stderr[-4000:]}")
    return levels


def select_candidates(levels: list[float], duration: float) -> list[dict[str, Any]]:
    window = 0.5
    median = statistics.median(levels)
    mad = statistics.median(abs(value - median) for value in levels) or 1e-6
    radius = 4
    candidates: list[tuple[float, int]] = []
    for index, value in enumerate(levels):
        seconds = (index + 0.5) * window
        if seconds < 8 or seconds > duration - 8:
            continue
        left = max(0, index - radius)
        right = min(len(levels), index + radius + 1)
        if value < max(levels[left:right]):
            continue
        previous = levels[max(0, index - radius)]
        score = (value - median) / mad + max(0.0, value - previous) * 2
        candidates.append((score, index))
    chosen: list[tuple[float, int]] = []
    for score, index in sorted(candidates, reverse=True):
        peak = (index + 0.5) * window
        if all(abs(peak - (other + 0.5) * window) >= 30 for _, other in chosen):
            chosen.append((score, index))
        if len(chosen) == 30:
            break
    result = []
    for candidate_id, (_, index) in enumerate(sorted(chosen, key=lambda item: item[1]), start=1):
        peak = (index + 0.5) * window
        result.append(
            {
                "id": candidate_id,
                "start": round(max(0.0, peak - 30), 3),
                "end": round(min(duration, peak + 25), 3),
                "peak": round(peak, 3),
                "audio_score": round(levels[index], 6),
            }
        )
    if len(result) != 30:
        raise RuntimeError(f"expected 30 candidates, got {len(result)}")
    return result


def attach_transcripts(candidates: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        candidate["transcript"] = [
            event
            for event in events
            if event["end"] >= candidate["start"] and event["start"] <= candidate["end"]
        ]


def download_clip(url: str, candidate: dict[str, Any], clips: Path, root: Path) -> Path:
    clips.mkdir(parents=True, exist_ok=True)
    target = clips / f"{int(candidate['id']):02d}.mp4"
    if target.is_file() and target.stat().st_size:
        return target
    for old in clips.glob(f"{int(candidate['id']):02d}.*"):
        old.unlink(missing_ok=True)
    section = f"*{float(candidate['start']):.3f}-{float(candidate['end']):.3f}"
    run(
        [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--no-warnings",
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--download-sections",
            section,
            "--force-keyframes-at-cuts",
            "-f",
            "18/b[height<=480]",
            "--merge-output-format",
            "mp4",
            "-o",
            str(clips / f"{int(candidate['id']):02d}.%(ext)s"),
            url,
        ],
        cwd=root,
        timeout=1800,
    )
    files = sorted(clips.glob(f"{int(candidate['id']):02d}.*"))
    mp4 = next((path for path in files if path.suffix.lower() == ".mp4"), None)
    if mp4 is None:
        raise RuntimeError(f"candidate {candidate['id']} clip missing")
    if mp4 != target:
        mp4.replace(target)
    return target


def run_crv(clip: Path, output: Path, root: Path) -> tuple[list[Path], int]:
    if output.exists():
        shutil.rmtree(output)
    run(
        [
            sys.executable,
            "-m",
            "claude_real_video",
            str(clip),
            "-o",
            str(output),
            "--no-transcribe",
            "--grid",
            "--max-frames",
            "18",
        ],
        cwd=root,
        timeout=1800,
    )
    grids = sorted((output / "grids").glob("*.jpg"))
    frames = sorted((output / "frames").glob("*.jpg"))
    if not grids:
        grids = frames[:5]
    if not grids:
        raise RuntimeError(f"CRV generated no images for {clip}")
    return grids, len(frames)


def data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def choose_model(client: OpenAI) -> str:
    available = {item.id for item in client.models.list().data}
    explicit = os.environ.get("GROQ_VISION_MODEL", "").strip()
    for model in [explicit, *MODEL_CANDIDATES]:
        if model and model in available:
            return model
    raise RuntimeError(f"no supported Groq vision model found; available={sorted(available)}")


def model_decision(client: OpenAI, model: str, candidate: dict[str, Any], grids: list[Path]) -> dict[str, Any]:
    transcript = "\n".join(
        f"[{max(0.0, float(event['start']) - float(candidate['start'])):05.1f}s] {event['text']}"
        for event in candidate.get("transcript", [])
    ) or "(字幕なし)"
    prompt = textwrap.dedent(
        f"""
        55秒の日本語ゲーム配信候補から、単独で公開できる面白い8〜22秒を1つ選んでください。
        添付画像はclaude-real-videoが時系列に抽出・重複除去したキーフレームのグリッドです。
        音量だけでなく、画面上の出来事、前振り、失敗・成功、反応、オチ、珍しさを評価してください。
        メニュー、長い静止画、普通の移動、映像に意味がない雑談は低評価にしてください。

        candidate_id={candidate['id']}
        audio_peak_offset={float(candidate['peak']) - float(candidate['start']):.2f}s
        transcript:\n{transcript}

        JSONだけを返してください。キーは score(0-10), start_offset_seconds,
        end_offset_seconds, label(日本語24文字以内), reason(日本語), visual_summary(日本語) です。
        """
    ).strip()
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for grid in grids[:5]:
        content.append({"type": "image_url", "image_url": {"url": data_uri(grid)}})
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
        max_completion_tokens=600,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or "{}"
    return json.loads(text[text.find("{") : text.rfind("}") + 1])


def fallback_decision(candidate: dict[str, Any], frame_count: int, all_scores: list[float]) -> dict[str, Any]:
    low, high = min(all_scores), max(all_scores)
    audio = (float(candidate["audio_score"]) - low) / max(1e-6, high - low)
    chars = sum(len(str(event.get("text", ""))) for event in candidate.get("transcript", []))
    score = min(8.4, 2.5 + 2.2 * audio + 0.9 * math.log1p(frame_count) + min(2.0, chars / 180))
    peak_offset = float(candidate["peak"]) - float(candidate["start"])
    return {
        "score": round(score, 3),
        "start_offset_seconds": max(0.0, peak_offset - 8),
        "end_offset_seconds": min(55.0, peak_offset + 8),
        "label": f"CRV候補 {int(candidate['id']):02d}",
        "reason": "CRV保持フレーム数・字幕密度・音量の決定的フォールバック",
        "visual_summary": f"CRV保持フレーム{frame_count}枚",
    }


def normalize(candidate: dict[str, Any], decision: dict[str, Any], provider: str, model: str | None, preview: Path, frame_count: int) -> dict[str, Any]:
    duration = float(candidate["end"]) - float(candidate["start"])
    peak_offset = float(candidate["peak"]) - float(candidate["start"])
    try:
        start = float(decision.get("start_offset_seconds"))
        end = float(decision.get("end_offset_seconds"))
    except (TypeError, ValueError):
        start, end = peak_offset - 8, peak_offset + 8
    start = max(0.0, min(duration - 0.1, start))
    end = max(start + 0.1, min(duration, end))
    if end - start < 8:
        end = min(duration, start + 8)
        start = max(0.0, end - 8)
    if end - start > 22:
        end = start + 22
    try:
        score = max(0.0, min(10.0, float(decision.get("score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    label = " ".join(str(decision.get("label") or f"候補 {candidate['id']}").split())[:24]
    return {
        "candidate_id": int(candidate["id"]),
        "candidate_start": candidate["start"],
        "candidate_end": candidate["end"],
        "peak": candidate["peak"],
        "audio_score": candidate["audio_score"],
        "score": round(score, 3),
        "selected_start": round(float(candidate["start"]) + start, 3),
        "selected_end": round(float(candidate["start"]) + end, 3),
        "duration_seconds": round(end - start, 3),
        "label": label,
        "reason": " ".join(str(decision.get("reason") or "").split())[:300],
        "visual_summary": " ".join(str(decision.get("visual_summary") or "").split())[:300],
        "provider": provider,
        "model": model,
        "frame_count": frame_count,
        "preview_source": str(preview),
        "raw_decision": decision,
    }


def overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    overlap = max(0.0, min(left["selected_end"], right["selected_end"]) - max(left["selected_start"], right["selected_start"]))
    shorter = min(left["duration_seconds"], right["duration_seconds"])
    return overlap / max(0.001, shorter)


def select_final(analyses: list[dict[str, Any]], count: int = 13) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in sorted(analyses, key=lambda value: (value["score"], value["frame_count"]), reverse=True):
        if any(overlap_ratio(item, other) > 0.35 for other in selected):
            skipped.append(item)
        else:
            selected.append(item)
        if len(selected) == count:
            break
    for item in skipped:
        if len(selected) == count:
            break
        selected.append(item)
    return sorted(selected, key=lambda value: value["selected_start"])


def oracle_reference(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {int(item["id"]): item for item in candidates}
    exact = {
        1: (92.24, 105.52, "内心の自由は奪えない", 8.6),
        3: (186.48, 205.4, "謎コメントに困惑", 7.8),
    }
    result = []
    for candidate_id in ORACLE_IDS:
        candidate = by_id[candidate_id]
        if candidate_id in exact:
            start, end, label, score = exact[candidate_id]
        else:
            peak = float(candidate["peak"])
            start, end = peak - 7.5, peak + 7.5
            label, score = f"Oracle採用候補 {candidate_id:02d}", None
        result.append(
            {
                "candidate_id": candidate_id,
                "selected_start": round(max(float(candidate["start"]), start), 3),
                "selected_end": round(min(float(candidate["end"]), end), 3),
                "label": label,
                "score": score,
            }
        )
    return result


def font_file(root: Path) -> str:
    value = run(["fc-match", "-f", "%{file}", "Noto Sans CJK JP"], cwd=root, timeout=60).strip()
    return value or "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def filter_escape(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def render_scene(source: Path, offset: float, duration: float, output: Path, candidate_id: int, label: str, root: Path, font: str) -> None:
    label_file = output.with_suffix(".txt")
    label_file.write_text(f"#{candidate_id:02d}  {label}", encoding="utf-8")
    vf = (
        "scale=854:480:force_original_aspect_ratio=decrease,"
        "pad=854:480:(ow-iw)/2:(oh-ih)/2:black,fps=30,"
        f"drawtext=fontfile='{filter_escape(Path(font))}':textfile='{filter_escape(label_file)}':"
        "fontcolor=white:fontsize=27:box=1:boxcolor=black@0.65:boxborderw=10:x=(w-text_w)/2:y=22"
    )
    run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{offset:.3f}", "-t", f"{duration:.3f}", "-i", str(source),
            "-vf", vf, "-af", "aresample=48000:async=1:first_pts=0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(output),
        ],
        cwd=root,
        timeout=1200,
    )


def render_montage(name: str, selections: list[dict[str, Any]], candidates: list[dict[str, Any]], clips: Path, output: Path, root: Path) -> Path:
    work = output / f"render-{name}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    by_id = {int(item["id"]): item for item in candidates}
    font = font_file(root)
    pieces = []
    for index, item in enumerate(selections, start=1):
        candidate_id = int(item["candidate_id"])
        candidate = by_id[candidate_id]
        scene = work / f"{index:03d}.mp4"
        render_scene(
            clips / f"{candidate_id:02d}.mp4",
            max(0.0, float(item["selected_start"]) - float(candidate["start"])),
            float(item["selected_end"]) - float(item["selected_start"]),
            scene,
            candidate_id,
            str(item["label"]),
            root,
            font,
        )
        pieces.append(scene)
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in pieces), encoding="utf-8")
    final = output / f"{name}.mp4"
    run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(final)],
        cwd=root,
        timeout=1200,
    )
    return final


def metrics(selected: list[dict[str, Any]]) -> dict[str, Any]:
    crv = {int(item["candidate_id"]) for item in selected}
    oracle = set(ORACLE_IDS)
    common = crv & oracle
    union = crv | oracle
    return {
        "overlap_count": len(common),
        "overlap_candidate_ids": sorted(common),
        "crv_only_candidate_ids": sorted(crv - oracle),
        "oracle_only_candidate_ids": sorted(oracle - crv),
        "jaccard": round(len(common) / len(union), 4),
        "oracle_recall": round(len(common) / len(oracle), 4),
    }


def write_report(output: Path, analyses: list[dict[str, Any]], selected: list[dict[str, Any]], oracle: list[dict[str, Any]], info: dict[str, Any]) -> None:
    preview_dir = output / "previews"
    preview_dir.mkdir(exist_ok=True)
    selected_ids = {int(item["candidate_id"]) for item in selected}
    for item in analyses:
        source = Path(item.pop("preview_source"))
        target = preview_dir / f"candidate-{int(item['candidate_id']):02d}{source.suffix.lower()}"
        shutil.copy2(source, target)
        item["preview"] = target.relative_to(output).as_posix()
    comparison = metrics(selected)
    report = {
        "schema_version": 1,
        "video": info,
        "method": {
            "candidate_pool": "same audio RMS pool: 30 candidates, 30s min gap, -30/+25s",
            "crv": "claude-real-video scene-aware keyframes, dedup, max 18 frames, grid",
            "oracle_used_for_crv_selection": False,
            "decision_providers": sorted({item["provider"] for item in analyses}),
            "models": sorted({item["model"] for item in analyses if item["model"]}),
        },
        "metrics": comparison,
        "selected": selected,
        "oracle_reference": oracle,
        "all_candidates": analyses,
    }
    write_json(output / "comparison.json", report)
    write_json(output / "crv-selected-scenes.json", selected)
    write_json(output / "oracle-reference-scenes.json", oracle)
    cards = []
    for item in sorted(analyses, key=lambda value: value["score"], reverse=True):
        badges = []
        if item["candidate_id"] in selected_ids:
            badges.append("CRV採用")
        if item["candidate_id"] in ORACLE_IDS:
            badges.append("Oracle採用")
        cards.append(
            f"<article><img src='{html.escape(item['preview'])}' loading='lazy'><div><p>{' / '.join(badges)}</p>"
            f"<h3>#{item['candidate_id']:02d} {html.escape(item['label'])}</h3>"
            f"<p><b>{item['score']:.2f}</b>　{item['selected_start']:.2f}–{item['selected_end']:.2f}s</p>"
            f"<p>{html.escape(item['reason'])}</p><small>{html.escape(item['provider'])} / frames {item['frame_count']}</small></div></article>"
        )
    document = f"""<!doctype html><html lang='ja'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>CRV Oracle comparison</title><style>body{{font-family:system-ui;background:#0d1117;color:#eee;max-width:1400px;margin:auto;padding:24px}}.videos,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}}video,img{{width:100%}}article{{background:#171d27;border:1px solid #303b4c;border-radius:12px;overflow:hidden}}article div{{padding:12px}}section{{margin:24px 0}}small{{color:#aab4c3}}</style></head><body>
<h1>同一配信 CRV / Oracle 比較</h1><p>候補一致 {comparison['overlap_count']}/13、Jaccard {comparison['jaccard']}。CRV側の選定にOracleは使用していません。</p>
<p>Oracle動画は既存Oracle採用候補IDの参照モンタージュで、元完成版そのものではありません。</p>
<section class='videos'><div><h2>CRV追加経路</h2><video controls src='crv-vision-comparison.mp4'></video></div><div><h2>Oracle候補参照</h2><video controls src='oracle-reference-candidate-montage.mp4'></video></div></section>
<section class='grid'>{''.join(cards)}</section></body></html>"""
    (output / "comparison.html").write_text(document, encoding="utf-8")
    summary = textwrap.dedent(
        f"""
        # CRV / Oracle comparison

        - Video: `{VIDEO_ID}`
        - CRV selected IDs: `{[item['candidate_id'] for item in selected]}`
        - Oracle IDs: `{ORACLE_IDS}`
        - Overlap: `{comparison['overlap_count']} / 13`
        - Jaccard: `{comparison['jaccard']}`
        - CRV only: `{comparison['crv_only_candidate_ids']}`
        - Oracle only: `{comparison['oracle_only_candidate_ids']}`
        - Providers: `{report['method']['decision_providers']}`
        - Models: `{report['method']['models']}`
        """
    ).strip() + "\n"
    (output / "SUMMARY.md").write_text(summary, encoding="utf-8")
    print(summary, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=VIDEO_URL)
    parser.add_argument("--work", type=Path, default=Path(".crv-compare-work"))
    parser.add_argument("--output", type=Path, default=Path("crv-comparison-output"))
    args = parser.parse_args()
    root = Path.cwd()
    work = args.work.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime, clips, crv_root = work / "runtime", work / "clips", work / "crv"
    runtime.mkdir(parents=True, exist_ok=True)
    clips.mkdir(parents=True, exist_ok=True)
    crv_root.mkdir(parents=True, exist_ok=True)

    started = time.time()
    info = metadata(args.url, root)
    if str(info.get("id")) != VIDEO_ID:
        raise RuntimeError(f"wrong video: {info.get('id')}")
    candidate_file = work / "candidates.json"
    if candidate_file.exists():
        candidates = json.loads(candidate_file.read_text(encoding="utf-8"))
    else:
        audio = download_audio(args.url, runtime, root)
        events = subtitle_events(download_subtitles(args.url, runtime, root))
        candidates = select_candidates(audio_levels(audio, root), float(info["duration"]))
        attach_transcripts(candidates, events)
        write_json(candidate_file, candidates)
    print("candidate peaks:", [item["peak"] for item in candidates], flush=True)

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1") if api_key else None
    model = None
    if client:
        try:
            model = choose_model(client)
            print("vision model:", model, flush=True)
        except Exception as exc:
            print("vision initialization failed; fallback:", exc, flush=True)
            client = None
    scores = [float(item["audio_score"]) for item in candidates]
    analyses = []
    for candidate in candidates:
        candidate_id = int(candidate["id"])
        print(f"candidate {candidate_id:02d}/30", flush=True)
        clip = download_clip(args.url, candidate, clips, root)
        grids, frame_count = run_crv(clip, crv_root / f"candidate-{candidate_id:02d}", root)
        provider = "crv-deterministic-fallback"
        used_model = None
        if client and model:
            try:
                decision = model_decision(client, model, candidate, grids)
                provider = "crv+groq-vision"
                used_model = model
            except Exception as exc:
                print(f"vision failed for {candidate_id}: {exc}", flush=True)
                decision = fallback_decision(candidate, frame_count, scores)
        else:
            decision = fallback_decision(candidate, frame_count, scores)
        analyses.append(normalize(candidate, decision, provider, used_model, grids[0], frame_count))

    selected = select_final(analyses)
    oracle = oracle_reference(candidates)
    render_montage("crv-vision-comparison", selected, candidates, clips, output, root)
    render_montage("oracle-reference-candidate-montage", oracle, candidates, clips, output, root)
    info_summary = {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "duration_seconds": info.get("duration"),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    write_report(output, analyses, selected, oracle, info_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
