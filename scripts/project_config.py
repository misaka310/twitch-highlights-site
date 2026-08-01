from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "site.json"
CHANNEL_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,25}$")


@dataclass(frozen=True)
class ProjectConfig:
    site_name: str
    site_description: str
    site_base_url: str
    site_language: str
    goatcounter_code: str
    twitch_channel_login: str
    twitch_channel_id: str
    extra_tag_rules: tuple[tuple[str, tuple[str, ...]], ...]

    @property
    def twitch_channel_url(self) -> str:
        return f"https://www.twitch.tv/{self.twitch_channel_login}"

    @property
    def twitchmetrics_url(self) -> str:
        if not self.twitch_channel_id:
            return ""
        return (
            f"https://www.twitchmetrics.net/c/{self.twitch_channel_id}-"
            f"{self.twitch_channel_login}/videos?sort=published_at-desc"
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "site": {
                "name": self.site_name,
                "description": self.site_description,
                "base_url": self.site_base_url,
                "language": self.site_language,
                "analytics": {"goatcounter_code": self.goatcounter_code},
            },
            "twitch": {
                "channel_login": self.twitch_channel_login,
                "channel_id": self.twitch_channel_id,
            },
        }


def _read_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"site config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid site config JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"site config must be a JSON object: {path}")
    return payload


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _env_or_config(env: Mapping[str, str], key: str, value: object) -> str:
    env_value = _string(env.get(key))
    return env_value if env_value else _string(value)


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


def load_project_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    source = _read_config(config_path)
    environment = env or os.environ

    site = _mapping(source.get("site"))
    analytics = _mapping(site.get("analytics"))
    twitch = _mapping(source.get("twitch"))
    analysis = _mapping(source.get("analysis"))

    channel_login = _env_or_config(environment, "TWITCH_CHANNEL", twitch.get("channel_login")).lower()
    if not CHANNEL_LOGIN_PATTERN.fullmatch(channel_login):
        raise RuntimeError(
            "TWITCH_CHANNEL or config.twitch.channel_login must contain only letters, numbers, "
            "or underscores and be 1-25 characters long"
        )

    site_name = _env_or_config(environment, "SITE_NAME", site.get("name")) or "Twitch Highlights"
    site_description = _env_or_config(environment, "SITE_DESCRIPTION", site.get("description"))
    if not site_description:
        site_description = "Twitch VODのコメント量から見どころを表示する非公式サイトです。"

    return ProjectConfig(
        site_name=site_name,
        site_description=site_description,
        site_base_url=_env_or_config(environment, "SITE_BASE_URL", site.get("base_url")).rstrip("/"),
        site_language=_env_or_config(environment, "SITE_LANGUAGE", site.get("language")) or "ja",
        goatcounter_code=_env_or_config(environment, "GOATCOUNTER_CODE", analytics.get("goatcounter_code")),
        twitch_channel_login=channel_login,
        twitch_channel_id=_env_or_config(environment, "TWITCH_CHANNEL_ID", twitch.get("channel_id")),
        extra_tag_rules=_parse_tag_rules(analysis.get("extra_tag_rules")),
    )
