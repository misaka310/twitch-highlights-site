from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from array import array
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont

VIDEO_ID = "kIujKrO80tk"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
ROOT = Path("artifacts") / f"crv-compare-{VIDEO_ID}"
WORK = Path(".crv-compare-work")
AUDIO = WORK / "source.m4a"
SUBTITLE_DIR = WORK / "subtitles"
CANDIDATE_DIR = WORK / "candidates"
CRV_DIR = WORK / "crv"
NORMALIZED_DIR = WORK / "normalized"
OUTPUT_MP4 = ROOT / f"{VIDEO_ID}-crv-review.mp4"
COMPARISON_JSON = ROOT / "comparison.json"
COMPARISON_HTML = ROOT / "comparison.html"
RUN_INFO = ROOT / "run-info.json"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b").strip()

CANDIDATE_COUNT = 24
SELECT_COUNT = 13
MIN_PEAK_GAP = 90.0
PRE_ROLL = 24.0
POST_ROLL = 22.0
WINDOW_SEC = PRE_ROLL + POST_ROLL
AUDIO_SAMPLE_RATE = 16000
RMS_WINDOW_SEC = 0.5

ORACLE_REFERENCE = [
    {"candidate_id": 1, "start": 92.24, "end": 105.52, "label": "内心の自由は奪えない", "score": 8.6},
    {"candidate_id": 3, "start": 186.48, "end": 205.40, "label": "謎コメントに困惑", "score": 7.8},
    {"candidate_id": 9, "start": 964.12, "end": 985.079, "label": "二人きりが気まずい理由", "score": 8.0},
]
ORACLE_SELECTED_IDS = [1, 3, 9, 11, 12, 13, 15, 16, 18, 20, 24, 26, 30]


@dataclass
class Candidate:
    candidate_id: int
    peak: float
    start: float
    end: float
    audio_score: float
    clip_path: str = ""
    crv_dir: str = ""
    transcript: str = ""
    frame_count: int = 0
    grid_paths: list[str] | None = None
    llm_score: float = 0.0
    label: str = ""
    reason: str = ""
    visual_event: str = ""
    self_contained: bool = False
    trim_start: float = 0.0
    trim_end: float = 0.0
    evaluator: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["grid_paths"] = self.grid_paths or []
        return value


def run(cmd: list[str], *, check: bool = True, capture: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=check,
        timeout=timeout,
    )


def safe_name(text: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[\r\n\t]+", " ", text).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.replace('"', "").replace("'", "")
    return cleaned[:limit] or "場面"


def ensure_tools() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe", "yt-dlp", "crv") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"missing tools: {', '.join(missing)}")
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is empty")


def reset_dirs() -> None:
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    ROOT.mkdir(parents=True, exist_ok=True)
    SUBTITLE_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    CRV_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)


def yt_common() -> list[str]:
    return [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--retries", "5",
        "--fragment-retries", "5",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
    ]


def fetch_metadata() -> dict[str, Any]:
    proc = run(yt_common() + ["--dump-single-json", "--skip-download", URL], capture=True, timeout=180)
    return json.loads(proc.stdout)


def download_audio() -> None:
    output = str(WORK / "source.%(ext)s")
    run(
        yt_common()
        + [
            "-f", "ba[ext=m4a]/ba/b",
            "-o", output,
            URL,
        ],
        timeout=1800,
    )
    candidates = sorted(WORK.glob("source.*"))
    candidates = [p for p in candidates if p.suffix.lower() not in {".json", ".part", ".ytdl"}]
    if not candidates:
        raise RuntimeError("audio download produced no file")
    source = max(candidates, key=lambda p: p.stat().st_size)
    if source != AUDIO:
        if AUDIO.exists():
            AUDIO.unlink()
        source.rename(AUDIO)


def download_subtitles() -> Path | None:
    cmd = yt_common() + [
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", "ja.*,ja",
        "--sub-format", "vtt",
        "-o", str(SUBTITLE_DIR / "%(id)s.%(ext)s"),
        URL,
    ]
    run(cmd, check=False, timeout=300)
    files = sorted(SUBTITLE_DIR.glob("*.vtt"))
    return files[0] if files else None


def analyze_audio(duration: float) -> list[Candidate]:
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(AUDIO),
        "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE),
        "-f", "f32le", "-",
    ]
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    samples_per_window = int(AUDIO_SAMPLE_RATE * RMS_WINDOW_SEC)
    values: list[float] = []
    carry = b""
    bytes_per_window = samples_per_window * 4
    while True:
        chunk = proc.stdout.read(1024 * 1024)
        if not chunk:
            break
        carry += chunk
        while len(carry) >= bytes_per_window:
            block, carry = carry[:bytes_per_window], carry[bytes_per_window:]
            samples = array("f")
            samples.frombytes(block)
            if sys.byteorder != "little":
                samples.byteswap()
            power = sum(float(v) * float(v) for v in samples) / max(1, len(samples))
            values.append(20.0 * math.log10(max(math.sqrt(power), 1e-8)))
    stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg audio analysis failed: {stderr[-2000:]}")
    if len(values) < 10:
        raise RuntimeError("audio analysis produced too few windows")

    sorted_values = sorted(values)
    floor = sorted_values[max(0, int(len(sorted_values) * 0.5) - 1)]
    upper = sorted_values[max(0, int(len(sorted_values) * 0.95) - 1)]
    spread = max(1.0, upper - floor)
    pool: list[tuple[float, int]] = []
    radius = 4
    for i in range(radius, len(values) - radius):
        v = values[i]
        local = values[i - radius:i + radius + 1]
        if v < max(local):
            continue
        prominence = v - (sum(local) - v) / (len(local) - 1)
        normalized = (v - floor) / spread
        score = normalized + max(0.0, prominence) * 0.12
        t = (i + 0.5) * RMS_WINDOW_SEC
        if t < PRE_ROLL or t > duration - POST_ROLL:
            continue
        pool.append((score, i))
    pool.sort(reverse=True)

    selected: list[tuple[float, int]] = []
    for score, i in pool:
        t = (i + 0.5) * RMS_WINDOW_SEC
        if any(abs(t - (j + 0.5) * RMS_WINDOW_SEC) < MIN_PEAK_GAP for _, j in selected):
            continue
        selected.append((score, i))
        if len(selected) >= CANDIDATE_COUNT:
            break
    selected.sort(key=lambda item: item[1])

    result: list[Candidate] = []
    for idx, (score, i) in enumerate(selected, start=1):
        peak = (i + 0.5) * RMS_WINDOW_SEC
        result.append(
            Candidate(
                candidate_id=idx,
                peak=round(peak, 3),
                start=round(max(0.0, peak - PRE_ROLL), 3),
                end=round(min(duration, peak + POST_ROLL), 3),
                audio_score=round(float(score), 5),
            )
        )
    return result


def parse_vtt(path: Path | None) -> list[tuple[float, float, str]]:
    if path is None or not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    cue_re = re.compile(
        r"(?m)^(?P<a>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<b>\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n(?P<t>(?:(?!\n\n).|\n)+)"
    )

    def stamp(value: str) -> float:
        h, m, s = value.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    cues: list[tuple[float, float, str]] = []
    for match in cue_re.finditer(text):
        body = re.sub(r"<[^>]+>", "", match.group("t"))
        body = re.sub(r"(?m)^(?:[A-Za-z]+:)?\s*$", "", body)
        body = html.unescape(body)
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            cues.append((stamp(match.group("a")), stamp(match.group("b")), body))
    return cues


def transcript_for(cues: list[tuple[float, float, str]], start: float, end: float) -> str:
    lines: list[str] = []
    previous = ""
    for a, b, text in cues:
        if b < start or a > end:
            continue
        if text == previous:
            continue
        lines.append(f"[{max(0.0, a-start):05.1f}] {text}")
        previous = text
    return "\n".join(lines)[:5000]


def download_candidate(candidate: Candidate) -> Path:
    clip = CANDIDATE_DIR / f"candidate-{candidate.candidate_id:02d}.mp4"
    section = f"*{candidate.start:.3f}-{candidate.end:.3f}"
    cmd = yt_common() + [
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=480]+ba/b[height<=480]/b",
        "--merge-output-format", "mp4",
        "-o", str(clip),
        URL,
    ]
    run(cmd, timeout=900)
    if not clip.exists():
        matches = sorted(CANDIDATE_DIR.glob(f"candidate-{candidate.candidate_id:02d}.*"))
        if matches:
            run([
                "ffmpeg", "-y", "-v", "error", "-i", str(matches[0]),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                "-c:a", "aac", "-b:a", "160k", str(clip)
            ], timeout=600)
    if not clip.exists():
        raise RuntimeError(f"candidate clip missing: {candidate.candidate_id}")
    candidate.clip_path = str(clip)
    return clip


def run_crv(candidate: Candidate, clip: Path) -> Path:
    out = CRV_DIR / f"candidate-{candidate.candidate_id:02d}"
    run([
        "crv", str(clip),
        "-o", str(out),
        "--grid",
        "--viewer",
        "--no-transcribe",
        "--max-frames", "27",
        "--why", "配信ハイライトとして前振り・出来事・反応・オチが映像と会話の両方で成立するか評価する",
    ], timeout=600)
    grids = sorted((out / "grids").glob("*.jpg"))
    frames = sorted((out / "frames").glob("*.jpg"))
    candidate.crv_dir = str(out)
    candidate.frame_count = len(frames)
    candidate.grid_paths = [str(p) for p in grids]
    return out


def image_data_url(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1280, 1280))
        temp = WORK / f"api-{path.parent.name}-{path.name}"
        image.save(temp, format="JPEG", quality=76, optimize=True)
    encoded = base64.b64encode(temp.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError(f"no JSON object in response: {text[:300]}")
    return json.loads(match.group(0))


def evaluate_candidate(candidate: Candidate) -> None:
    grids = [Path(p) for p in (candidate.grid_paths or []) if Path(p).exists()][:3]
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": (
            "あなたは配信ハイライト編集者です。添付画像は時系列のCRVコンタクトシートです。"
            "字幕と映像を合わせ、単独で見ても意味が通り、面白さ・反応・出来事が成立する区間を評価してください。\n"
            f"候補全体は0.0〜{WINDOW_SEC:.1f}秒です。音量ピークは{PRE_ROLL:.1f}秒付近です。\n"
            "8〜22秒を原則とし、必要時のみ30秒まで。会話の頭やオチを切らないでください。\n"
            "JSONのみ返してください。schema:\n"
            '{"score":0.0,"label":"24文字以内","reason":"日本語","visual_event":"日本語",'
            '"self_contained":true,"start_offset":0.0,"end_offset":18.0}\n\n'
            f"字幕:\n{candidate.transcript or '(字幕なし)'}"
        )
    }]
    for grid in grids:
        content.append({"type": "image_url", "image_url": {"url": image_data_url(grid)}})

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0.15,
        "max_completion_tokens": 700,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "映像と字幕の根拠だけで厳しく評価する。数合わせで高得点にしない。"},
            {"role": "user", "content": content},
        ],
    }
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=180,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Groq {response.status_code}: {response.text[:1000]}")
    body = response.json()
    raw = body["choices"][0]["message"]["content"]
    data = extract_json(raw)
    candidate.llm_score = round(max(0.0, min(10.0, float(data.get("score", 0.0)))), 2)
    candidate.label = safe_name(str(data.get("label", "")))
    candidate.reason = str(data.get("reason", "")).strip()[:500]
    candidate.visual_event = str(data.get("visual_event", "")).strip()[:500]
    candidate.self_contained = bool(data.get("self_contained", False))
    start = max(0.0, min(WINDOW_SEC - 8.0, float(data.get("start_offset", 0.0))))
    end = max(start + 8.0, min(WINDOW_SEC, float(data.get("end_offset", start + 18.0))))
    if end - start > 30.0:
        end = start + 30.0
    candidate.trim_start = round(start, 3)
    candidate.trim_end = round(end, 3)
    candidate.evaluator = GROQ_MODEL


def fallback_evaluation(candidate: Candidate, error: Exception) -> None:
    candidate.error = f"{type(error).__name__}: {error}"
    transcript_bonus = min(1.5, len(candidate.transcript) / 900)
    visual_bonus = min(1.5, candidate.frame_count / 18)
    candidate.llm_score = round(min(7.0, 3.5 + transcript_bonus + visual_bonus + min(0.8, candidate.audio_score * 0.2)), 2)
    candidate.label = safe_name(next((line.split("] ", 1)[-1] for line in candidate.transcript.splitlines() if "] " in line), "音量ピーク場面"))
    candidate.reason = "画像または字幕の自動評価に失敗したため、音量・字幕量・映像変化量で暫定評価した。"
    candidate.visual_event = f"CRV抽出フレーム{candidate.frame_count}枚"
    candidate.self_contained = bool(candidate.transcript)
    candidate.trim_start = max(0.0, PRE_ROLL - 8.0)
    candidate.trim_end = min(WINDOW_SEC, PRE_ROLL + 12.0)
    candidate.evaluator = "fallback"


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    def effective(c: Candidate) -> float:
        return c.llm_score + (0.35 if c.self_contained else -0.25) + min(0.25, c.frame_count / 100.0)

    ranked = sorted(candidates, key=lambda c: (effective(c), c.audio_score), reverse=True)
    selected: list[Candidate] = []
    for candidate in ranked:
        absolute_start = candidate.start + candidate.trim_start
        absolute_end = candidate.start + candidate.trim_end
        if any(not (absolute_end + 5 <= s.start + s.trim_start or absolute_start >= s.start + s.trim_end + 5) for s in selected):
            continue
        selected.append(candidate)
        if len(selected) >= SELECT_COUNT:
            break
    selected.sort(key=lambda c: c.start + c.trim_start)
    return selected


def font_path() -> str:
    choices = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    return next((p for p in choices if Path(p).exists()), choices[-1])


def make_title_card(candidate: Candidate, index: int) -> Path:
    path = NORMALIZED_DIR / f"title-{index:02d}.png"
    image = Image.new("RGB", (1280, 720), (18, 18, 22))
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(font_path(), 52)
    body_font = ImageFont.truetype(font_path(), 30)
    time_font = ImageFont.truetype(font_path(), 26)
    absolute_start = candidate.start + candidate.trim_start
    absolute_end = candidate.start + candidate.trim_end
    draw.text((70, 120), f"{index:02d}  {candidate.label}", font=title_font, fill=(245, 245, 245))
    draw.text((72, 220), f"{absolute_start:.2f} – {absolute_end:.2f} sec", font=time_font, fill=(180, 180, 190))
    reason = candidate.reason
    lines: list[str] = []
    line = ""
    for ch in reason:
        if len(line) >= 32:
            lines.append(line)
            line = ""
        line += ch
    if line:
        lines.append(line)
    draw.multiline_text((72, 300), "\n".join(lines[:5]), font=body_font, fill=(215, 215, 220), spacing=12)
    image.save(path)
    return path


def normalize_selected(selected: list[Candidate]) -> list[Path]:
    pieces: list[Path] = []
    for index, candidate in enumerate(selected, start=1):
        clip = Path(candidate.clip_path)
        title = make_title_card(candidate, index)
        title_mp4 = NORMALIZED_DIR / f"title-{index:02d}.mp4"
        run([
            "ffmpeg", "-y", "-v", "error",
            "-loop", "1", "-t", "1.35", "-i", str(title),
            "-f", "lavfi", "-t", "1.35", "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", "format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", "-shortest", str(title_mp4)
        ], timeout=300)
        segment = NORMALIZED_DIR / f"scene-{index:02d}.mp4"
        duration = max(8.0, candidate.trim_end - candidate.trim_start)
        run([
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{candidate.trim_start:.3f}", "-t", f"{duration:.3f}", "-i", str(clip),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p",
            "-af", "aresample=48000",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", str(segment)
        ], timeout=600)
        pieces.extend([title_mp4, segment])
    return pieces


def concat_video(pieces: list[Path]) -> None:
    concat_file = NORMALIZED_DIR / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in pieces) + "\n",
        encoding="utf-8",
    )
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c", "copy", "-movflags", "+faststart", str(OUTPUT_MP4)
    ], timeout=1200)


def copy_grids(selected: list[Candidate]) -> None:
    dst = ROOT / "selected-grids"
    dst.mkdir(parents=True, exist_ok=True)
    for candidate in selected:
        for grid_path in candidate.grid_paths or []:
            source = Path(grid_path)
            if source.exists():
                shutil.copy2(source, dst / f"candidate-{candidate.candidate_id:02d}-{source.name}")


def write_outputs(metadata: dict[str, Any], candidates: list[Candidate], selected: list[Candidate], started_at: float) -> None:
    selected_ids = {c.candidate_id for c in selected}
    payload = {
        "schema_version": 1,
        "video": {
            "id": VIDEO_ID,
            "url": URL,
            "title": metadata.get("title"),
            "duration": metadata.get("duration"),
        },
        "method": {
            "name": "claude-real-video + Groq vision, Oracle-free",
            "crv_version": "0.7.17",
            "vision_model": GROQ_MODEL,
            "candidate_count": len(candidates),
            "selected_count": len(selected),
        },
        "oracle_reference": {
            "selected_candidate_ids_from_prior_run": ORACLE_SELECTED_IDS,
            "verified_entries_available_here": ORACLE_REFERENCE,
            "note": "既存Oracle完成版は変更していない。CRV版と動画・時刻・採用候補を並べて比較するための参照。",
        },
        "selected": [
            {
                **c.to_dict(),
                "absolute_start": round(c.start + c.trim_start, 3),
                "absolute_end": round(c.start + c.trim_end, 3),
            }
            for c in selected
        ],
        "candidates": [
            {
                **c.to_dict(),
                "selected": c.candidate_id in selected_ids,
                "absolute_start": round(c.start + c.trim_start, 3),
                "absolute_end": round(c.start + c.trim_end, 3),
            }
            for c in candidates
        ],
    }
    COMPARISON_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    RUN_INFO.write_text(json.dumps({
        "elapsed_sec": round(time.time() - started_at, 2),
        "output_mp4_bytes": OUTPUT_MP4.stat().st_size if OUTPUT_MP4.exists() else 0,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "groq_model": GROQ_MODEL,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = []
    for c in sorted(candidates, key=lambda x: x.candidate_id):
        absolute_start = c.start + c.trim_start
        absolute_end = c.start + c.trim_end
        rows.append(
            "<tr class='{}'><td>{}</td><td>{:.2f}–{:.2f}</td><td>{:.2f}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                "selected" if c.candidate_id in selected_ids else "",
                c.candidate_id,
                absolute_start,
                absolute_end,
                c.llm_score,
                html.escape(c.label),
                html.escape(c.reason),
                c.frame_count,
                html.escape(c.evaluator),
            )
        )
    oracle_rows = "".join(
        f"<tr><td>{x['candidate_id']}</td><td>{x['start']:.2f}–{x['end']:.2f}</td><td>{html.escape(x['label'])}</td><td>{x['score']}</td></tr>"
        for x in ORACLE_REFERENCE
    )
    page = f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>CRV comparison {VIDEO_ID}</title>
<style>
body{{font-family:system-ui,'Noto Sans CJK JP',sans-serif;margin:28px;background:#111;color:#eee}}
table{{border-collapse:collapse;width:100%;margin:18px 0}}th,td{{border:1px solid #444;padding:8px;vertical-align:top}}
th{{background:#252525}}tr.selected{{background:#18351f}}code{{background:#222;padding:2px 5px}}
.note{{padding:12px;background:#28231a;border-left:4px solid #b58b2a}}
</style>
<h1>同一配信 CRV比較版</h1>
<p><code>{VIDEO_ID}</code> / {html.escape(str(metadata.get('title') or ''))}</p>
<div class="note">既存Oracle版は変更していません。この成果物はOracleを呼ばず、CRVコンタクトシート・字幕・音量候補をGroq Visionで独立評価した版です。緑色が採用候補です。</div>
<h2>CRV版 全候補</h2>
<table><thead><tr><th>ID</th><th>絶対時刻</th><th>点</th><th>ラベル</th><th>理由</th><th>frames</th><th>判定</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>既存Oracle参照（確認できた項目）</h2>
<p>既存採用candidate IDs: {', '.join(map(str, ORACLE_SELECTED_IDS))}</p>
<table><thead><tr><th>ID</th><th>時刻</th><th>ラベル</th><th>点</th></tr></thead><tbody>{oracle_rows}</tbody></table>
</html>"""
    COMPARISON_HTML.write_text(page, encoding="utf-8")


def main() -> int:
    started_at = time.time()
    ensure_tools()
    reset_dirs()
    metadata = fetch_metadata()
    duration = float(metadata.get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("video duration unavailable")
    download_audio()
    subtitle_path = download_subtitles()
    cues = parse_vtt(subtitle_path)
    candidates = analyze_audio(duration)
    print(f"candidate_count={len(candidates)} subtitle_cues={len(cues)}", flush=True)

    for candidate in candidates:
        try:
            candidate.transcript = transcript_for(cues, candidate.start, candidate.end)
            clip = download_candidate(candidate)
            run_crv(candidate, clip)
            try:
                evaluate_candidate(candidate)
            except Exception as exc:
                print(f"evaluation fallback candidate={candidate.candidate_id}: {exc}", flush=True)
                fallback_evaluation(candidate, exc)
        except Exception as exc:
            candidate.error = f"{type(exc).__name__}: {exc}"
            fallback_evaluation(candidate, exc)
            print(f"candidate failed id={candidate.candidate_id}: {exc}", flush=True)
        print(
            f"candidate={candidate.candidate_id} score={candidate.llm_score} "
            f"frames={candidate.frame_count} label={candidate.label}",
            flush=True,
        )

    selected = rank_candidates(candidates)
    if not selected:
        raise RuntimeError("no candidates selected")
    downloadable = [c for c in selected if c.clip_path and Path(c.clip_path).exists()]
    if len(downloadable) < min(8, SELECT_COUNT):
        raise RuntimeError(f"too few renderable selected candidates: {len(downloadable)}")
    selected = downloadable[:SELECT_COUNT]
    pieces = normalize_selected(selected)
    concat_video(pieces)
    copy_grids(selected)
    write_outputs(metadata, candidates, selected, started_at)
    print(f"RESULT mp4={OUTPUT_MP4} json={COMPARISON_JSON} html={COMPARISON_HTML}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
