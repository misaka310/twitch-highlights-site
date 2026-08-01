from __future__ import annotations

import update_vods as uv


def main() -> int:
    try:
        status = uv.fetch_current_stream_status(uv.CHANNEL)
    except Exception as exc:
        print(f"twitch_live_status_error: channel={uv.CHANNEL} error={exc}")
        return 2

    if bool(status.get("live")):
        print(
            f"twitch_live_status: channel={uv.CHANNEL} live=true"
            f" stream_id={status.get('stream_id') or ''}"
            f" started_at={status.get('started_at') or ''}"
        )
        return 0

    print(f"twitch_live_status: channel={uv.CHANNEL} live=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
