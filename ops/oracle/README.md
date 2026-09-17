# Oracle YouTube handoff

The Oracle VM is the only component that connects to YouTube. It fetches
live-chat offsets with the already verified `/home/ubuntu/yt-dlp`, Deno, and
`/home/ubuntu/youtube-cookies.txt` route, applies the repository's existing
chat z-score detector, and cuts only the selected highlight intervals.

The selected WAV and WEBP files are sent to one short-lived OCI Object Storage
object through a Pre-Authenticated Request (PAR). GitHub Actions reads that
object, runs Whisper and the public-data checks, and removes the object after
processing. The workflow never runs `yt-dlp` against YouTube.

## Install on Oracle

Install this repository at `/opt/youtube-highlight/repository`, or copy the
`scripts/`, `config/`, and `ops/` files there. Keep the existing verified
Oracle acquisition prerequisites in place:

- `/home/ubuntu/yt-dlp`
- `/home/ubuntu/.local/bin/deno`
- `/home/ubuntu/youtube-cookies.txt` with mode `600`
- `ffmpeg`

Create `/etc/youtube-highlight/youtube.env` with mode `600`. Use real values
only on the VM; never commit this file:

```text
YOUTUBE_ORACLE_VIDEO_URL=https://www.youtube.com/watch?v=...
YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL=https://objectstorage.../par/...
YOUTUBE_ORACLE_GITHUB_TOKEN=...
YOUTUBE_ORACLE_GITHUB_REPOSITORY=owner/repository
DISCORD_WEBHOOK_URL=...
```

The PAR used for upload must be scoped to the single temporary object and
permit the Oracle `PUT` and overwrite of that object; the read PAR is stored
separately in GitHub. Each PAR can be reused until its expiration, so they do
not need to be recreated daily. A six-month lifetime is acceptable for this
fixed, narrowly scoped object; rotate both PARs before they expire. OCI
pre-authenticated requests cannot delete objects, so configure an OCI
lifecycle rule that deletes the temporary object within one day. The GitHub token must be limited to this repository's
`repository_dispatch` operation.

Install and enable the timer:

```bash
sudo install -m 0644 ops/oracle/youtube-highlight.service /etc/systemd/system/youtube-highlight.service
sudo install -m 0644 ops/oracle/youtube-highlight.timer /etc/systemd/system/youtube-highlight.timer
sudo systemctl daemon-reload
sudo systemctl enable --now youtube-highlight.timer
systemctl list-timers youtube-highlight.timer
```

Useful one-shot checks are `systemctl start youtube-highlight.service` and
`journalctl -u youtube-highlight.service`. The job prints only classified
status and counts; it does not print cookies, keys, chat text, or PAR URLs.

## GitHub Actions secrets

Add these repository Actions secrets:

- `YOUTUBE_ORACLE_BUNDLE_READ_URL`: read-only PAR for the temporary object.

The workflow is triggered by the Oracle `repository_dispatch` event
`youtube-material-ready`. Its normal checked-PR publication path remains
separate from the paused legacy `update-vods.yml` schedule.
