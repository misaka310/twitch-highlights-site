from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

VIDEO_ID = "kIujKrO80tk"
TIMEOUT = 18
USER_AGENT = "Mozilla/5.0 CRV-comparison-source-probe/1.0"


def get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def probe_piped() -> list[dict[str, Any]]:
    endpoints = {
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.adminforge.de",
        "https://piped-api.garudalinux.org",
        "https://pipedapi.reallyaweso.me",
        "https://pipedapi-libre.kavin.rocks",
    }
    try:
        markdown = get_text(
            "https://raw.githubusercontent.com/TeamPiped/documentation/main/content/docs/public-instances/index.md"
        )
        endpoints.update(
            item.rstrip("/.,)")
            for item in re.findall(r"https://[A-Za-z0-9._:-]+", markdown)
            if "api" in item.lower() and "piped" in item.lower()
        )
    except Exception as exc:
        print(f"Piped instance-list fetch failed: {exc}", file=sys.stderr)

    found = []
    for base in sorted(endpoints):
        try:
            payload = get_json(f"{base}/streams/{VIDEO_ID}")
            duration = int(payload.get("duration") or 0)
            audio = [item for item in payload.get("audioStreams", []) if item.get("url")]
            video = [item for item in payload.get("videoStreams", []) if item.get("url")]
            if duration > 19000 and audio and video:
                found.append(
                    {
                        "provider": "piped",
                        "base_url": base,
                        "title": payload.get("title"),
                        "duration": duration,
                        "audio_stream_count": len(audio),
                        "video_stream_count": len(video),
                        "audio_url": max(audio, key=lambda item: int(item.get("bitrate") or 0))["url"],
                        "video_url": max(
                            video,
                            key=lambda item: (
                                int(item.get("height") or 0) <= 720,
                                min(int(item.get("height") or 0), 720),
                                int(item.get("bitrate") or 0),
                            ),
                        )["url"],
                    }
                )
                print(f"PIPED_OK {base} duration={duration} audio={len(audio)} video={len(video)}")
                break
            print(f"PIPED_EMPTY {base} duration={duration} audio={len(audio)} video={len(video)}")
        except Exception as exc:
            print(f"PIPED_FAIL {base}: {type(exc).__name__}: {exc}")
    return found


def probe_invidious() -> list[dict[str, Any]]:
    endpoints: list[str] = []
    try:
        instances = get_json("https://api.invidious.io/instances.json")
        for _, details in instances:
            if not isinstance(details, dict) or not details.get("api"):
                continue
            uri = details.get("uri")
            if isinstance(uri, str) and uri.startswith("https://"):
                endpoints.append(uri.rstrip("/"))
    except Exception as exc:
        print(f"Invidious instance-list fetch failed: {exc}", file=sys.stderr)

    found = []
    for base in endpoints[:40]:
        try:
            payload = get_json(f"{base}/api/v1/videos/{VIDEO_ID}?local=true")
            duration = int(payload.get("lengthSeconds") or 0)
            adaptive = [item for item in payload.get("adaptiveFormats", []) if item.get("url")]
            progressive = [item for item in payload.get("formatStreams", []) if item.get("url")]
            audio = [item for item in adaptive if str(item.get("type", "")).startswith("audio/")]
            video = [item for item in adaptive if str(item.get("type", "")).startswith("video/")]
            if duration > 19000 and audio and (video or progressive):
                video_pool = video or progressive
                found.append(
                    {
                        "provider": "invidious",
                        "base_url": base,
                        "title": payload.get("title"),
                        "duration": duration,
                        "audio_stream_count": len(audio),
                        "video_stream_count": len(video_pool),
                        "audio_url": max(audio, key=lambda item: int(item.get("bitrate") or 0))["url"],
                        "video_url": max(
                            video_pool,
                            key=lambda item: (
                                int(str(item.get("qualityLabel") or item.get("quality") or "0").rstrip("p") or 0) <= 720,
                                min(int(str(item.get("qualityLabel") or item.get("quality") or "0").rstrip("p") or 0), 720),
                                int(item.get("bitrate") or 0),
                            ),
                        )["url"],
                    }
                )
                print(f"INVIDIOUS_OK {base} duration={duration} audio={len(audio)} video={len(video_pool)}")
                break
            print(f"INVIDIOUS_EMPTY {base} duration={duration} audio={len(audio)} video={len(video_pool)}")
        except Exception as exc:
            print(f"INVIDIOUS_FAIL {base}: {type(exc).__name__}: {exc}")
    return found


def main() -> int:
    results = [*probe_piped(), *probe_invidious()]
    safe_results = []
    for item in results:
        safe_results.append({key: value for key, value in item.items() if not key.endswith("_url")})
    Path("alternative-source-probe.json").write_text(
        json.dumps(safe_results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not results:
        print("No alternative source API could resolve this video", file=sys.stderr)
        return 1
    chosen = results[0]
    Path("alternative-source.json").write_text(
        json.dumps(chosen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"CHOSEN {chosen['provider']} {chosen['base_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
