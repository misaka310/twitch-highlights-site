from __future__ import annotations

import argparse
import html
import json
from collections.abc import Mapping
from pathlib import Path


PLACEHOLDERS = {
    "__SITE_NAME__": "name",
    "__SITE_DESCRIPTION__": "description",
    "__SITE_BASE_URL__": "base_url",
    "__SITE_LANGUAGE__": "language",
}
DEFAULTS = {
    "name": "Twitch Highlights",
    "description": "Twitch VODのコメント量から見どころを表示する非公式サイトです。",
    "base_url": "",
    "language": "ja",
}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _metadata_values(config: Mapping[str, object]) -> dict[str, str]:
    site = _mapping(config.get("site"))
    values: dict[str, str] = {}
    for key, fallback in DEFAULTS.items():
        value = str(site.get(key) or fallback).strip()
        if key == "base_url":
            value = value.rstrip("/")
        values[key] = html.escape(value, quote=True)
    return values


def render_site_metadata(template: str, config: Mapping[str, object]) -> str:
    missing = [placeholder for placeholder in PLACEHOLDERS if placeholder not in template]
    if missing:
        raise RuntimeError(f"metadata placeholder missing from HTML template: {', '.join(missing)}")

    rendered = template
    values = _metadata_values(config)
    for placeholder, key in PLACEHOLDERS.items():
        rendered = rendered.replace(placeholder, values[key])
    return rendered


def apply_site_metadata(html_path: Path, config_path: Path) -> None:
    template = html_path.read_text(encoding="utf-8")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, Mapping):
        raise RuntimeError(f"site configuration must be a JSON object: {config_path}")
    rendered = render_site_metadata(template, config)
    html_path.write_text(rendered, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render static site metadata into a built index.html file.")
    parser.add_argument("html_path", type=Path)
    parser.add_argument("config_path", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    apply_site_metadata(args.html_path, args.config_path)


if __name__ == "__main__":
    main()
