from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def fetch_json_bytes(url: str) -> tuple[bytes, Any]:
    request = urllib.request.Request(
        f"{url}?deployment-check={int(time.time())}",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return raw, json.loads(raw)


def configured_base_url() -> str:
    payload = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    configured = str(payload.get("site", {}).get("base_url") or "").strip()
    overridden = str(os.environ.get("LIVE_BASE_URL") or configured).strip().rstrip("/")
    if not overridden:
        raise SystemExit("LIVE_BASE_URL or config/site.json site.base_url is required")
    return overridden


def main() -> None:
    expected_bytes = (ROOT / "data" / "vods.json").read_bytes()
    expected = json.loads(expected_bytes.decode("utf-8-sig"))
    url = f"{configured_base_url()}/data/vods.json"
    timeout_sec = max(1, int(os.environ.get("LIVE_VERIFY_TIMEOUT_SEC", "600")))
    deadline = time.monotonic() + timeout_sec
    last_observation = "no response"
    live_bytes = b""

    while time.monotonic() < deadline:
        try:
            live_bytes, live = fetch_json_bytes(url)
            if live == expected:
                break
            expected_videos = expected.get("videos") or [{}]
            live_videos = live.get("videos") or [{}]
            last_observation = (
                f"expected updated_at={expected.get('updated_at')} latest={expected_videos[0].get('vod_id')}; "
                f"live updated_at={live.get('updated_at')} latest={live_videos[0].get('vod_id')}"
            )
        except Exception as exc:  # network and remote JSON errors are retried until the deadline
            last_observation = f"{type(exc).__name__}: {exc}"
        print(f"deployment data not ready: {last_observation}")
        time.sleep(min(10, max(1, timeout_sec)))
    else:
        raise SystemExit(
            f"production VOD data did not match main within {timeout_sec} seconds: {last_observation}"
        )

    expected_videos = expected.get("videos") or [{}]
    marker = {
        "verified": True,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "main_sha": os.environ.get("GITHUB_SHA", "local"),
        "updated_at": expected.get("updated_at"),
        "latest_vod_id": expected_videos[0].get("vod_id"),
        "expected_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "live_sha256": hashlib.sha256(live_bytes).hexdigest(),
    }
    (ROOT / "production-verification.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(marker, ensure_ascii=False))


if __name__ == "__main__":
    main()
