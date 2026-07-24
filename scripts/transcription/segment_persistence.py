from __future__ import annotations

from typing import Any, Callable

import transcript_io as tio


def apply_transcript_result(
    item: dict[str, Any],
    target: Any,
    result: Any,
    *,
    transcript_model: str,
    now_iso: Callable[[], str],
) -> None:
    tio.apply_transcript_result(
        item,
        target,
        result,
        transcript_model=transcript_model,
        now_iso=now_iso,
    )


clear_transcript_artifacts = tio.clear_transcript_artifacts
clear_headline_artifacts = tio.clear_headline_artifacts
log_item_snapshot = tio.log_item_snapshot

