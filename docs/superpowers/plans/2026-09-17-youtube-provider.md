# YouTube Provider Support Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Add a real Oracle-backed YouTube live-chat provider to the public Twitch highlights site while preserving legacy data and Twitch playback UX.

Architecture: Keep the existing highlight algorithm and update orchestration. Add a focused YouTube source/Oracle parser, an explicit --youtube-url ingestion mode, optional provider metadata in the public contract, and provider-specific frontend player adapters behind the existing playback lifecycle.

Tech Stack: Python 3, unittest, React 19, TypeScript, Vite, YouTube IFrame Player API, Twitch Player SDK, Playwright.

Spec: docs/superpowers/specs/2026-09-17-youtube-provider-design.md

## Global Constraints

- Legacy data with no provider remains Twitch-compatible.
- YouTube chat must use Local pipeline -> Oracle VM -> YouTube live_chat; no direct local YouTube chat fallback.
- Only normalized offsets and safe video metadata may leave the Oracle process; chat text, authors, raw chat, cookies, and SSH keys are never persisted.
- Existing vod_highlights.py bucketing, z-score, selection, activity-map, page size, and Twitch UX remain unchanged.
- Initial playback is not autoplayed and is muted; user-triggered playback requests sound.
- Do not resume scheduled VOD updates or publish/push/PR/merge.
- The final Vite server remains available at http://localhost:4174/.

---

### Task 1: Freeze the provider contract in canonical docs

Files:
- Modify: docs/PUBLIC_SITE_SPEC.md
- Modify: docs/PLAYBACK_SPEC.md
- Modify: docs/data-contract.md
- Modify: docs/site-architecture.md
- Modify: README.md
- Modify: docs/OPERATIONS.md
- Test: tests/test_repository_architecture.py

Interfaces:
- Produces the documented provider field and explicit --youtube-url/Oracle configuration contract used by later tasks.

- [ ] Step 1: Write failing documentation-contract assertions.
  Add assertions for provider support, the explicit YouTube ingestion command, and the Oracle-only route to the existing architecture/docs tests.
- [ ] Step 2: Run the focused repository test.
  Run: python -m unittest tests.test_repository_architecture.RepositoryArchitectureTests.test_public_site_specification_is_canonical_and_complete -v
  Expected: FAIL because the canonical docs do not mention the new provider contract.
- [ ] Step 3: Update the canonical docs minimally.
  Document provider-neutral player wording, optional provider, vod_id semantics, the explicit Oracle route, and that scheduled updates remain paused. Do not change unrelated UX limits.
- [ ] Step 4: Run the focused test again.
  Run: python -m unittest tests.test_repository_architecture.RepositoryArchitectureTests.test_public_site_specification_is_canonical_and_complete -v
  Expected: PASS.
- [ ] Step 5: Commit the docs/spec baseline.
  Run: git add docs README.md tests/test_repository_architecture.py; git commit -m "docs: define YouTube provider contract"

### Task 2: Add a privacy-safe YouTube Oracle source parser

Files:
- Create: scripts/youtube_sources.py
- Modify: scripts/vod_sources.py
- Create: tests/test_youtube_sources.py

Interfaces:
- YoutubeOracleConfig(command: list[str], timeout_sec: int = 300)
- parse_youtube_video_id(value: str) -> str
- parse_youtube_oracle_output(output: str, expected_video_id: str) -> YoutubeFetchResult
- build_youtube_oracle_command(command: list[str], url: str) -> list[str]
- fetch_youtube_video(url: str, cfg: YoutubeOracleConfig, runner=...) -> YoutubeFetchResult
- vod_sources.fetch_chat_data(..., provider="twitch", vod_url="") dispatches YouTube without changing the Twitch default.

- [ ] Step 1: Write failing parser tests.
  Cover a watch URL and short URL, conversion of "123456" milliseconds to 123.456 seconds, malformed/missing offsets, expected-id mismatch, optional duration/metadata, and the fact that returned comments contain only content_offset_seconds.
- [ ] Step 2: Run the focused tests.
  Run: python -m unittest tests.test_youtube_sources -v
  Expected: FAIL because the module and parser do not exist.
- [ ] Step 3: Implement the pure parser and command builder.
  Parse the Oracle script's transport logs and temporary `video_offset` TSV, normalize finite nonnegative values, retain only safe metadata, reject wrong video ids, and never expose raw lines or chat text in the result.
- [ ] Step 4: Run the focused tests.
  Run: python -m unittest tests.test_youtube_sources -v
  Expected: PASS.
- [ ] Step 5: Add subprocess transport and Twitch-preserving dispatch.
  Run the configured `ssh -i <key> <user>@<host> bash -s` transport with the existing Oracle script supplied over stdin, normalize its temporary TSV output, surface nonzero/timeout errors, and dispatch only when provider == "youtube".
- [ ] Step 6: Add transport tests with an injected runner.
  Assert the command receives the target URL, the output is parsed, and a runner exception is surfaced without falling back to direct local HTTP.
- [ ] Step 7: Run the focused tests again.
  Run: python -m unittest tests.test_youtube_sources -v
  Expected: PASS.
- [ ] Step 8: Commit the source boundary.
  Run: git add scripts/vod_sources.py scripts/youtube_sources.py tests/test_youtube_sources.py; git commit -m "feat: add Oracle-backed YouTube source"

### Task 3: Make update and serialization provider-aware

Files:
- Modify: scripts/update_vods.py
- Modify: scripts/vod_serialization.py
- Modify: tests/test_core_data_contract.py
- Create or modify: tests/test_update_vods_youtube.py

Interfaces:
- normalize_provider(value: object) -> str
- analyze_video_entry(video, now) accepts a YouTube source entry and uses its normalized chat offsets.
- --youtube-url URL performs one explicit YouTube analysis/merge without changing normal Twitch mode.
- Public entries include provider for YouTube and omit it for legacy Twitch where possible.

- [ ] Step 1: Write failing provider contract and orchestration tests.
  Assert legacy entries default to Twitch, YouTube entries retain provider/id/url, YouTube analysis invokes the existing detector with normalized offsets, sanitizer removes raw chat fields, and the CLI parser rejects invalid combinations.
- [ ] Step 2: Run the focused tests.
  Run: python -m unittest tests.test_core_data_contract tests.test_update_vods_youtube -v
  Expected: FAIL because provider-aware serialization and the explicit mode do not exist.
- [ ] Step 3: Implement provider normalization and whitelist support.
  Preserve the existing whitelist and add only provider; keep all retired/private keys rejected.
- [ ] Step 4: Implement explicit YouTube analysis mode.
  Load the existing cache, fetch one YouTube source through the Oracle adapter, pass content_offset_seconds to build_activity_map and detect_items, merge it, and call the existing public writers. Normal mode remains unchanged.
- [ ] Step 5: Run the focused tests again.
  Run: python -m unittest tests.test_core_data_contract tests.test_update_vods_youtube -v
  Expected: PASS.
- [ ] Step 6: Run all Python tests.
  Run: python -m unittest discover -s tests -p "test_*.py"
  Expected: PASS with no privacy or architecture regressions.
- [ ] Step 7: Commit the provider-aware pipeline.
  Run: git add scripts/update_vods.py scripts/vod_serialization.py tests/test_core_data_contract.py tests/test_update_vods_youtube.py; git commit -m "feat: analyze YouTube archives with existing highlights"

### Task 4: Add provider-neutral frontend domain and YouTube player adapters

Files:
- Modify: frontend/src/domain/vod.ts
- Modify: frontend/src/lib/vod-data.ts
- Modify: frontend/src/player/playback-types.ts
- Modify: frontend/src/player/playback-request.ts
- Create: frontend/src/player/youtube-player-adapter.ts
- Create: frontend/src/player/youtube-sdk-loader.ts
- Modify: frontend/src/player/twitch-player-adapter.ts
- Create or modify: frontend/tests/unit/youtube-player.test.ts
- Modify: frontend/tests/unit/player-logic.test.ts
- Modify: frontend/tests/unit/vod-domain.test.ts

Interfaces:
- type Provider = "twitch" | "youtube"
- getVodProvider(vod: Pick<VodData, "provider" | "vod_url">): Provider
- PlaybackRequest.provider defaults to "twitch" for old callers.
- YoutubePlayerAdapter maps YT.Player operations/events to the normalized player interface.

- [ ] Step 1: Write failing TypeScript tests.
  Cover provider inference, YouTube IDs/URLs, default Twitch request compatibility, YouTube mute/play/seek/current-time forwarding, and API state mapping.
- [ ] Step 2: Run the focused unit tests.
  Run: npm --prefix frontend run test:unit -- --test-name-pattern="provider|YouTube"
  Expected: FAIL because provider types and adapters do not exist.
- [ ] Step 3: Implement domain/request types and pure provider resolution.
  Keep old request call sites valid by defaulting provider to Twitch.
- [ ] Step 4: Implement the YouTube loader and adapter.
  Load https://www.youtube.com/iframe_api once, wrap YT.Player, map onReady, onStateChange, and onError, and expose only normalized operations.
- [ ] Step 5: Run the focused unit tests again.
  Run: npm --prefix frontend run test:unit
  Expected: PASS.
- [ ] Step 6: Commit the frontend adapter boundary.
  Run: git add frontend/src frontend/tests/unit; git commit -m "feat: add provider-aware player adapters"

### Task 5: Integrate YouTube playback without changing Twitch UX

Files:
- Modify: frontend/src/hooks/use-interactive-player.ts
- Modify: frontend/src/twitch-player.tsx
- Modify: frontend/src/App.tsx
- Modify: frontend/src/hooks/use-player-portal.ts
- Modify: frontend/src/player/iframe-fallback.ts
- Modify: frontend/src/components/activity-map.tsx
- Modify: frontend/src/components/highlight-list.tsx
- Modify: frontend/src/components/vod-rail.tsx
- Modify: frontend/src/components/stream-summary.tsx
- Modify: frontend/src/styles.css

Interfaces:
- requestPlayback(vodId, startSec, options) accepts provider through options/request creation.
- .player-frame exposes data-player-provider plus existing autoplay/muted/status/current-id/current-start attributes and one body portal.

- [ ] Step 1: Write failing component/E2E assertions.
  Add assertions for YouTube initial muted/no-autoplay, highlight click sound, same-video seek without remount, different-video remount, map seek, rewind, mobile one-column layout, and provider marker.
- [ ] Step 2: Run the relevant existing E2E/unit tests.
  Run: npm --prefix frontend run test:e2e -- --project=desktop --grep "same-VOD|latest click"
  Expected: the new YouTube assertions fail while existing Twitch behavior remains the baseline.
- [ ] Step 3: Integrate provider branching in the existing lifecycle.
  Select the provider-specific loader/adapter at mount time, preserve desired request ordering, start/stop polling, portal sync, last-click-wins, and status behavior, and avoid duplicate iframes/players.
- [ ] Step 4: Update App request creation.
  Pass the active VOD provider for initial load, VOD selection, highlight selection, map click, and rewind. Do not change displayed labels or page size.
- [ ] Step 5: Run unit and existing Twitch E2E tests.
  Run: npm --prefix frontend run typecheck; npm --prefix frontend run lint; npm --prefix frontend run test:unit; npm --prefix frontend run test:e2e
  Expected: PASS.
- [ ] Step 6: Commit the lifecycle integration.
  Run: git add frontend/src frontend/tests; git commit -m "feat: integrate YouTube playback into highlights UX"

### Task 6: Add isolated YouTube Playwright coverage and verify the real UI

Files:
- Create: frontend/tests/fake-youtube.ts
- Create: frontend/tests/youtube.spec.ts
- Modify: frontend/tests/preview.spec.ts
- Modify: frontend/playwright.config.ts only if a stable project-level option is required.

Interfaces:
- Fake API log records mounts, video id, seekTo, playVideo, mute state, current time, and player state.
- Each scenario fails on console errors, page errors, failed 4xx/5xx requests, and uncaught exceptions.

- [ ] Step 1: Write the isolated YouTube click tests.
  Use test routes for deterministic YouTube/Twitch fixtures, but exercise the production React/player path. Click the first three highlights, map, rewind, VOD tab, and back to YouTube; assert video id, current time, paused/playing state, and no same-video remount.
- [ ] Step 2: Run the new tests to verify the expected failure.
  Run: npm --prefix frontend run test:e2e -- youtube.spec.ts
  Expected: FAIL until the provider lifecycle integration is complete.
- [ ] Step 3: Implement the fake YouTube API only in test support.
  Do not use it as proof of real Oracle data; it only makes the adapter operations observable and deterministic.
- [ ] Step 4: Run desktop and mobile YouTube tests.
  Run: npm --prefix frontend run test:e2e -- youtube.spec.ts --project=desktop
  Run: npm --prefix frontend run test:e2e -- youtube.spec.ts --project=mobile
  Expected: PASS with zero console/page/network errors.
- [ ] Step 5: Commit the regression coverage.
  Run: git add frontend/tests frontend/playwright.config.ts; git commit -m "test: cover YouTube highlight playback"

### Task 7: Execute Oracle data generation and localhost acceptance

Files:
- Modify: .env.example only for non-secret variable names and examples.
- Modify: docs/OPERATIONS.md or README.md if the verified command/output differs from the design.
- Generated by existing pipeline: data/processed_vods.json, data/vods.json, data/vod_index.json, data/vods/WGTrmrSvZH0.json, public/.
- Test evidence: frontend/artifacts/ or repository-approved verification artifact location; do not commit raw chat.

Interfaces:
- The configured SSH transport reaches the configured Oracle host as the configured user, runs the existing Oracle script, and emits the documented temporary TSV.
- python scripts/update_vods.py --youtube-url https://www.youtube.com/watch?v=WGTrmrSvZH0 produces normalized public data.

- [ ] Step 1: Preflight Oracle and runtime configuration.
  Confirm the configured SSH route resolves to the Oracle VM, yt-dlp/Deno/cookies remain remote, no cookies/keys are in the repository, and no same-port server is running unexpectedly.
- [ ] Step 2: Run the real Oracle fetch.
  Run the explicit YouTube command with the target URL. Record only the count of normalized offsets, duration, and safe metadata; remove any raw temporary output after parsing.
- [ ] Step 3: Run public data generation.
  Run the explicit update mode and inspect JSON keys, provider/id/url, item count, activity bucket count, and absence of raw/private fields.
- [ ] Step 4: Start or reuse localhost:4174.
  Run: npm start
  Expected: http://localhost:4174/ responds and the process remains running for the user.
- [ ] Step 5: Run Playwright against the real generated data.
  Open the root and the page containing WGTrmrSvZH0 as needed; click highlights, map, rewind, and VOD tabs. Assert the real generated video id and times, then run desktop/mobile and inspect the required screenshot at display size.
- [ ] Step 6: Run the complete repository gate.
  Run: npm run verify
  Expected: PASS, with the known scheduled update remaining paused and no raw chat committed.
- [ ] Step 7: Final diff and process check.
  Run: git status --short --branch; git diff --check; Get-NetTCPConnection -LocalPort 4174 -State Listen
  Confirm only requested source/docs/tests/generated public data changed, localhost remains live, and no raw temporary files or credentials exist.
