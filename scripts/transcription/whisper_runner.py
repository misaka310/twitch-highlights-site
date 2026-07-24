from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class FasterWhisperModelCache:
    def __init__(self, *, device: str, compute_type: str) -> None:
        self.device = device
        self.compute_type = compute_type
        self._models: dict[str, Any] = {}

    def get_model(self, model_name: str) -> Any:
        cached = self._models.get(model_name)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device=self.device, compute_type=self.compute_type)
        self._models[model_name] = model
        return model


def transcribe_media(
    media_path: Path,
    *,
    model_cache: FasterWhisperModelCache,
    model_name: str,
    result_factory: Callable[..., Any],
    optional_float: Callable[[Any], float | None],
    vad_filter: bool = True,
    word_timestamps: bool = False,
    condition_on_previous_text: bool = False,
    beam_size: int = 1,
    vad_parameters: dict[str, Any] | None = None,
) -> Any:
    model = model_cache.get_model(model_name)
    transcribe_kwargs: dict[str, Any] = {
        "beam_size": max(1, int(beam_size)),
        "vad_filter": bool(vad_filter),
        "word_timestamps": bool(word_timestamps),
        "condition_on_previous_text": bool(condition_on_previous_text),
    }
    if vad_parameters:
        transcribe_kwargs["vad_parameters"] = dict(vad_parameters)

    segments, info = model.transcribe(str(media_path), **transcribe_kwargs)
    texts: list[str] = []
    normalized_segments: list[dict[str, Any]] = []
    for segment in segments:
        value = str(getattr(segment, "text", "") or "").strip()
        if not value:
            continue
        texts.append(value)
        words: list[dict[str, Any]] = []
        for word in getattr(segment, "words", None) or []:
            word_text = str(getattr(word, "word", "") or "").strip()
            if not word_text:
                continue
            words.append(
                {
                    "word": word_text,
                    "start": optional_float(getattr(word, "start", None)),
                    "end": optional_float(getattr(word, "end", None)),
                    "probability": optional_float(getattr(word, "probability", None)),
                }
            )
        normalized_segments.append(
            {
                "start": optional_float(getattr(segment, "start", None)),
                "end": optional_float(getattr(segment, "end", None)),
                "text": value,
                "words": words,
            }
        )

    merged_text = " ".join(texts).strip()
    return result_factory(
        text=merged_text,
        language=str(getattr(info, "language", "") or ""),
        language_probability=optional_float(getattr(info, "language_probability", None)),
        segments=normalized_segments or None,
        source_text=merged_text,
    )

