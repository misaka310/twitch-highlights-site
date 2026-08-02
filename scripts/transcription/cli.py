from __future__ import annotations

import argparse
from dataclasses import dataclass

from .config import PipelineSettings


@dataclass(frozen=True)
class RunOptions:
    force_transcript_refresh: bool
    force_headline_refresh: bool
    max_segments: int
    headline_only: bool
    only_item_id: str | None
    only_vod_id: str | None
    print_headline_results: bool
    print_source_selection: bool
    source_sentence_limit: int
    use_game_term_dictionary: bool
    second_pass_selection_mode: str
    second_pass_top_n: int
    second_pass_extra_padding_sec: int
    second_pass_word_timestamps: bool
    second_pass_preprocess_profile: str
    dry_run: bool


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe segments and generate headlines")
    parser.add_argument("--force-transcript-refresh", action="store_true")
    parser.add_argument("--force-headline-refresh", action="store_true")
    parser.add_argument("--max-segments", type=int, default=None)
    parser.add_argument("--headline-only", action="store_true")
    parser.add_argument("--item-id", "--only-item-id", dest="only_item_id", default=None)
    parser.add_argument("--vod-id", "--only-vod-id", dest="only_vod_id", default=None)
    parser.add_argument("--print-headline-results", action="store_true")
    parser.add_argument("--print-source-selection", action="store_true")
    parser.add_argument("--source-sentence-limit", type=int, default=None)
    parser.add_argument(
        "--second-pass-selection-mode",
        choices=("rank", "zscore", "quality", "hybrid"),
        default=None,
    )
    parser.add_argument("--second-pass-top-n", type=int, default=None)
    parser.add_argument("--second-pass-extra-padding-sec", type=int, default=None)
    timestamps = parser.add_mutually_exclusive_group()
    timestamps.add_argument(
        "--second-pass-word-timestamps",
        dest="second_pass_word_timestamps",
        action="store_true",
    )
    timestamps.add_argument(
        "--no-second-pass-word-timestamps",
        dest="second_pass_word_timestamps",
        action="store_false",
    )
    parser.add_argument("--second-pass-preprocess-profile", default=None)
    game_terms = parser.add_mutually_exclusive_group()
    game_terms.add_argument(
        "--use-game-term-dictionary",
        dest="use_game_term_dictionary",
        action="store_true",
    )
    game_terms.add_argument(
        "--no-game-term-dictionary",
        dest="use_game_term_dictionary",
        action="store_false",
    )
    parser.set_defaults(use_game_term_dictionary=None, second_pass_word_timestamps=None)
    return parser.parse_args(argv)


def _normalize_cli_id(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def build_run_options(args: argparse.Namespace, settings: PipelineSettings) -> RunOptions:
    max_segments = settings.TRANSCRIPT_MAX_SEGMENTS if args.max_segments is None else max(1, int(args.max_segments))
    headline_only = bool(args.headline_only)
    force_headline_refresh = bool(
        settings.FORCE_HEADLINE_REFRESH or args.force_headline_refresh or headline_only
    )
    source_sentence_limit_raw = (
        settings.SOURCE_SENTENCE_LIMIT_DEFAULT
        if args.source_sentence_limit is None
        else int(args.source_sentence_limit)
    )
    source_sentence_limit = max(1, min(2, source_sentence_limit_raw))
    use_game_term_dictionary = (
        settings.USE_GAME_TERM_DICTIONARY_DEFAULT
        if args.use_game_term_dictionary is None
        else bool(args.use_game_term_dictionary)
    )
    second_pass_selection_mode = (
        settings.TRANSCRIPT_SECOND_PASS_SELECTION_MODE
        if args.second_pass_selection_mode is None
        else str(args.second_pass_selection_mode).strip().lower()
    ) or "hybrid"
    second_pass_top_n = (
        settings.TRANSCRIPT_SECOND_PASS_TOP_N
        if args.second_pass_top_n is None
        else max(0, int(args.second_pass_top_n))
    )
    second_pass_extra_padding_sec = (
        settings.TRANSCRIPT_SECOND_PASS_EXTRA_PADDING_SEC
        if args.second_pass_extra_padding_sec is None
        else max(0, int(args.second_pass_extra_padding_sec))
    )
    second_pass_word_timestamps = (
        settings.TRANSCRIPT_SECOND_PASS_WORD_TIMESTAMPS
        if args.second_pass_word_timestamps is None
        else bool(args.second_pass_word_timestamps)
    )
    second_pass_preprocess_profile = (
        settings.TRANSCRIPT_SECOND_PASS_PREPROCESS_PROFILE
        if args.second_pass_preprocess_profile is None
        else str(args.second_pass_preprocess_profile).strip().lower()
    ) or settings.TRANSCRIPT_PREPROCESS_PROFILE
    return RunOptions(
        force_transcript_refresh=bool(settings.FORCE_TRANSCRIPT_REFRESH or args.force_transcript_refresh),
        force_headline_refresh=force_headline_refresh,
        max_segments=max_segments,
        headline_only=headline_only,
        only_item_id=_normalize_cli_id(args.only_item_id),
        only_vod_id=_normalize_cli_id(args.only_vod_id),
        print_headline_results=bool(args.print_headline_results),
        print_source_selection=bool(settings.PRINT_SOURCE_SELECTION_DEFAULT or args.print_source_selection),
        source_sentence_limit=source_sentence_limit,
        use_game_term_dictionary=use_game_term_dictionary,
        second_pass_selection_mode=second_pass_selection_mode,
        second_pass_top_n=second_pass_top_n,
        second_pass_extra_padding_sec=second_pass_extra_padding_sec,
        second_pass_word_timestamps=second_pass_word_timestamps,
        second_pass_preprocess_profile=second_pass_preprocess_profile,
        dry_run=settings.TRANSCRIPT_DRY_RUN,
    )
