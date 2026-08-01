from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from transcribe_segments import is_publishable_headline, validate_final_headline_japanese


DATA_PATH = ROOT / "data" / "vods.json"


def main() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8-sig"))
    videos = payload.get("videos") or []
    if not videos:
        raise RuntimeError("public VOD payload is empty")

    failures: list[str] = []
    for video in videos[:3]:
        vod_id = str(video.get("vod_id") or "unknown")
        items = video.get("items") or []
        if not items:
            failures.append(f"vod_id={vod_id}: no highlight items")
            continue

        for item in items[:3]:
            segment_id = str(item.get("id") or "unknown")
            headline = str(item.get("headline") or "").strip()
            screenshot_url = str(item.get("screenshot_url") or "").strip()
            if not headline:
                failures.append(f"segment_id={segment_id}: headline missing")
            else:
                validation = validate_final_headline_japanese(headline)
                if not is_publishable_headline(headline):
                    reasons = ",".join(validation.reasons) or "publish_quality"
                    failures.append(f"segment_id={segment_id}: invalid headline ({reasons})")
            if not screenshot_url:
                failures.append(f"segment_id={segment_id}: screenshot_url missing")
                continue
            screenshot_path = ROOT / screenshot_url.lstrip("/")
            if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
                failures.append(f"segment_id={segment_id}: screenshot file missing")

    if failures:
        raise RuntimeError("public enrichment incomplete: " + "; ".join(failures[:12]))

    print(f"public enrichment verified for {min(3, len(videos))} VODs")


if __name__ == "__main__":
    main()
