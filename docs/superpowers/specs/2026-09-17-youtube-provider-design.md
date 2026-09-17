# YouTube Provider Support Design

## Goal

Extend the public Twitch highlights site so a YouTube live-stream archive can use the same highlight, activity-map, and playback UX without changing the existing Twitch workflow.

## Scope and preserved contracts

- Keep the current content_offset_seconds -> 10-second buckets -> z-score -> highlight/activity_map algorithm unchanged.
- Keep legacy JSON readable when provider is absent; absent provider means twitch.
- Keep initial playback autoplay=false, muted=true and user-triggered highlight, tab, map, and rewind playback autoplay=true, muted=false.
- Keep same-VOD seek, last-click-wins, page size, layout, and Twitch SDK/iframe fallback behavior.
- Do not resume scheduled VOD updates, publish, push, create a PR, or change the public deployment in this work.
- Never persist chat text, author data, raw chat, cookies, SSH keys, or transcript data.

## Source architecture

vod_sources.py remains the source boundary for Twitch and provider dispatch. A focused youtube_sources.py module owns YouTube URL parsing, the confirmed SSH transport to 64.110.102.170, and the transient live-chat parser. The transport executes the existing local Oracle script over SSH as ubuntu with the configured key; no direct local YouTube chat fallback is allowed. The remote script emits operational logs and a temporary TSV containing video offsets. The parser returns only normalized in-memory offsets and safe metadata.

update_vods.py gains an explicit --youtube-url mode. Normal mode remains Twitch-only and therefore the paused scheduled update cannot silently start ingesting YouTube. The explicit mode analyzes the selected archive with the existing vod_highlights.py functions, merges the result into the existing cache, and regenerates the public JSON through vod_serialization.py.

## Data contract

Add an optional provider field with values twitch or youtube to video and index entries. It is emitted for YouTube entries and may be absent on legacy Twitch entries. vod_id remains the provider playback identifier: a numeric Twitch VOD id or an 11-character YouTube video id. vod_url remains the canonical provider URL. No chat-level data is added to any persisted payload.

## Frontend architecture

The existing playback request becomes provider-aware while retaining a Twitch default. A shared player lifecycle in use-interactive-player.ts keeps request ordering, desired state, position polling, and portal sizing. Provider-specific side effects live in adapters/loaders:

- Twitch continues to use the current SDK and iframe fallback.
- YouTube loads the IFrame Player API once, wraps YT.Player as the same normalized operations (play, seek, setMuted, getCurrentTime, events, destroy), and mounts it in the existing portal.

App.tsx derives the provider from the entry, passing it with each initial, user-triggered, same-video, different-video, map, and rewind request. The player frame keeps stable data attributes for E2E assertions, with an additional provider marker. The UI copy and layout remain unchanged except for provider-neutral accessibility text.

## Error behavior

- Missing or invalid YouTube URL, malformed Oracle JSON, missing offsets, expected-id mismatch, nonzero remote exit, or absent Oracle command fails the YouTube ingestion with an actionable error and never writes a partial public result.
- YouTube API load/player errors set the existing visible player status to an error/blocked state and keep the selected card/map state intact.
- A browser autoplay rejection is not reported as successful playback; a user-triggered request must call the adapter seek and play path and expose a blocked status if YouTube refuses it.
- Older Twitch data and unknown/missing provider values continue to use Twitch behavior.

## Verification

1. Python RED/GREEN tests cover YouTube URL parsing, videoOffsetTimeMsec conversion, metadata/offset privacy, explicit provider dispatch, and legacy compatibility.
2. Frontend unit tests cover provider resolution, YouTube URL/player adapter operations, initial muted state, user playback state, same-video seek, different-video remount, last-click-wins, and rewind.
3. Isolated Playwright tests use the repository desktop/mobile projects, a fake YouTube API only for deterministic adapter assertions, and the real localhost Vite server. They capture console/page/network errors and click highlights, tabs, map, and rewind.
4. The real Oracle route is executed for https://www.youtube.com/watch?v=WGTrmrSvZH0; the output is consumed transiently, the result is analyzed and serialized, and the generated target is opened through the local UI.
5. Existing Twitch unit, Python, public-build, and E2E verification remains green. The final local Vite server remains alive on http://localhost:4174/.
