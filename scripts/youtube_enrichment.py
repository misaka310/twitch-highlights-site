"""Whisper/headline enrichment for Oracle-selected YouTube highlights."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


from youtube_media import (
    YOUTUBE_MEDIA_INCLUDE_VIDEO_ENV,
    fetch_youtube_highlight_media_files,
    fetch_youtube_highlight_screenshot_files,
)


@dataclass(frozen=True)
class YoutubeEnrichmentSummary:
    attempted: int
    transcribed: int
    headlines: int
    screenshots: int


MediaFetcher = Callable[[str, int, int, Path], Path]


def enrich_youtube_video(
    video: dict[str, Any],
    *,
    media_fetcher: MediaFetcher | None = None,
    transcriber: Any | None = None,
    headline_generator: Any | None = None,
) -> tuple[dict[str, Any], YoutubeEnrichmentSummary]:
    """Enrich each selected item from a transient Oracle media section.

    Transcript fields are useful only during this process and are stripped by
    the public serializer.  A missing transcript never falls back to reaction
    tags or the stream title.
    """

    import transcribe_segments as ts
    from transcription.config import PipelineSettings

    from transcribe_segments import (
        SEGMENT_SCREENSHOT_GENERATION_ENABLED,
        SegmentTarget,
        WhisperTranscriber,
        apply_transcript_result,
        build_first_pass_config,
        build_segment_screenshot_file_path,
        build_segment_screenshot_public_path,
        maybe_generate_segment_screenshot,
    )

    ts.apply_pipeline_settings(PipelineSettings.from_env(os.environ))
    ts.refresh_runtime_configuration()

    active_transcriber = transcriber or WhisperTranscriber()
    active_headline_generator = headline_generator or ts.build_headline_generator()
    if headline_generator is None and getattr(active_headline_generator, "groq", None) is None:
        raise RuntimeError("youtube enrichment requires the Groq headline provider")
    pass_config = build_first_pass_config()
    attempted = 0
    transcribed = 0
    headlines = 0
    screenshots = 0
    include_video = str(os.environ.get(YOUTUBE_MEDIA_INCLUDE_VIDEO_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    vod_url = str(video.get("vod_url") or "").strip()
    if not vod_url:
        raise RuntimeError("youtube enrichment requires vod_url")

    with tempfile.TemporaryDirectory(prefix="youtube-enrichment-") as tmp_dir:
        work_dir = Path(tmp_dir)
        items = [item for item in video.get("items") or [] if isinstance(item, dict)]
        batch_paths: dict[int, Path] = {}
        if media_fetcher is None:
            intervals = []
            for item in items:
                try:
                    start_sec = int(item["start_sec"])
                    end_sec = max(start_sec + 1, int(item["end_sec"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError("youtube enrichment found an invalid highlight interval") from exc
                intervals.append((start_sec, end_sec))
            batch_paths = fetch_youtube_highlight_media_files(vod_url, intervals, work_dir)
        screenshot_paths: dict[int, Path] = {}
        screenshot_item_indexes: dict[int, int] = {}
        if media_fetcher is None and SEGMENT_SCREENSHOT_GENERATION_ENABLED:
            missing_screenshot_intervals: list[tuple[int, int]] = []
            for index, item in enumerate(items):
                vod_id = str(video.get("vod_id") or "").strip()
                segment_id = str(item.get("id") or "").strip()
                existing_path = build_segment_screenshot_file_path(vod_id, segment_id)
                if existing_path.is_file() and existing_path.stat().st_size > 0:
                    item["screenshot_url"] = build_segment_screenshot_public_path(vod_id, segment_id)
                    continue
                screenshot_item_indexes[len(missing_screenshot_intervals)] = index
                missing_screenshot_intervals.append(intervals[index])
            if missing_screenshot_intervals:
                screenshot_paths = fetch_youtube_highlight_screenshot_files(
                    vod_url,
                    missing_screenshot_intervals,
                    work_dir,
                )
        for index, item in enumerate(items):
            try:
                start_sec = int(item["start_sec"])
                end_sec = max(start_sec + 1, int(item["end_sec"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("youtube enrichment found an invalid highlight interval") from exc
            attempted += 1
            target = SegmentTarget(
                video=video,
                item=item,
                start_sec=start_sec,
                end_sec=end_sec,
                needs_transcript=True,
                needs_headline=True,
            )
            media_path = (
                batch_paths[index]
                if media_fetcher is None
                else media_fetcher(vod_url, start_sec, end_sec, work_dir)
            )
            try:
                before = str(item.get("screenshot_url") or "").strip()
                screenshot_index = next(
                    (remote_index for remote_index, item_index in screenshot_item_indexes.items() if item_index == index),
                    None,
                )
                if screenshot_index is not None and screenshot_index in screenshot_paths:
                    vod_id = str(video.get("vod_id") or "").strip()
                    segment_id = str(item.get("id") or "").strip()
                    output_path = build_segment_screenshot_file_path(vod_id, segment_id)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(screenshot_paths[screenshot_index].read_bytes())
                    item["screenshot_url"] = build_segment_screenshot_public_path(vod_id, segment_id)
                    screenshots += 1
                elif include_video:
                    maybe_generate_segment_screenshot(
                        target,
                        media_path=media_path,
                        clip_start_sec=start_sec,
                        clip_end_sec=end_sec,
                    )
                after = str(item.get("screenshot_url") or "").strip()
                if after and after != before:
                    screenshots += 1
            except Exception as exc:
                print(f"warn: YouTube screenshot enrichment failed item={item.get('id')} ({exc})")

            result = active_transcriber.transcribe(
                media_path,
                model_name=pass_config.model,
                vad_filter=pass_config.vad_filter,
                word_timestamps=pass_config.word_timestamps,
                condition_on_previous_text=pass_config.condition_on_previous_text,
                beam_size=pass_config.beam_size,
                vad_parameters=pass_config.vad_parameters,
            )
            transcript = str(getattr(result, "text", "") or "").strip()
            if not transcript:
                raise RuntimeError(f"youtube enrichment produced no transcript for {item.get('id')}")
            transcribed += 1
            apply_transcript_result(item, target, result)
            source_text = ts.build_headline_source_text(transcript, ts.HEADLINE_SOURCE_CONFIG)
            source_validation = ts.is_valid_headline_source_text(source_text, ts.HEADLINE_SOURCE_CONFIG)
            headline_result = active_headline_generator.generate(
                transcript=transcript,
                video_title=str(video.get("title") or "").strip(),
                start_time=str(item.get("start_time") or ts.format_section_time(start_sec)).strip(),
                end_time=str(item.get("end_time") or ts.format_section_time(end_sec)).strip(),
                prepared_transcript=source_text,
                source_validation=source_validation,
            )
            if headline_result.source != "groq" or (headline_generator is None and headline_result.model != ts.GROQ_MODEL):
                raise RuntimeError(
                    "youtube enrichment headline provider/model mismatch "
                    f"item={item.get('id')} source={headline_result.source} model={headline_result.model}"
                )
            if headline_result.generation_mode == "fallback_extractive":
                raise RuntimeError(f"youtube enrichment refused extractive fallback for {item.get('id')}")
            if not ts.is_publishable_headline(headline_result.text, source_text=source_text):
                raise RuntimeError(f"youtube enrichment produced an unpublishable LLM headline for {item.get('id')}")
            item["headline"] = headline_result.text
            item["headline_source"] = headline_result.source
            item["headline_model"] = headline_result.model
            item["headline_status"] = "ok"
            item["headline_generation_mode"] = headline_result.generation_mode
            item["headline_confidence"] = headline_result.confidence
            headlines += 1

    if attempted == 0 or transcribed != attempted or headlines != attempted:
        raise RuntimeError(
            f"youtube enrichment incomplete attempted={attempted} transcribed={transcribed} headlines={headlines}"
        )
    return video, YoutubeEnrichmentSummary(
        attempted=attempted,
        transcribed=transcribed,
        headlines=headlines,
        screenshots=screenshots,
    )


__all__ = ["YoutubeEnrichmentSummary", "enrich_youtube_video"]
