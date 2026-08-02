from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG_RULES_PATH = REPO_ROOT / "config" / "tag-rules.json"


def _read_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"tag rules config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid tag rules config JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"tag rules config must be a JSON object: {path}")
    return payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _parse_tag_rules(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(value, list):
        return ()
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for row in value:
        item = _mapping(row)
        label = _string(item.get("tag"))
        raw_patterns = item.get("patterns")
        if not label or not isinstance(raw_patterns, list):
            continue
        patterns = tuple(_string(pattern) for pattern in raw_patterns if _string(pattern))
        if patterns:
            parsed.append((label, patterns))
    return tuple(parsed)


def load_extra_tag_rules(
    path: Path | None = None,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    config_path = path or DEFAULT_TAG_RULES_PATH
    source = _read_config(config_path)
    return _parse_tag_rules(source.get("extra_tag_rules"))
