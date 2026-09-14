"""Persistent configuration for the Sleep Timer integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path

_LOG = logging.getLogger(__name__)
_CONFIG_FILE = "config.json"


@dataclass(frozen=True, slots=True)
class TargetAction:
    """One Core entity command executed when the timer expires."""

    entity_id: str
    command_id: str
    name: str = ""


@dataclass(slots=True)
class Settings:
    """Integration settings."""

    core_url: str = "http://127.0.0.1:8080"
    core_api_key: str = ""
    # Legacy single-target fields are kept so existing configurations migrate
    # without requiring the user to recreate the integration.
    target_entity_id: str = ""
    target_command_id: str = "macro.start"
    target_actions: list[TargetAction] = field(default_factory=list)
    emby_url: str = ""
    emby_api_key: str = ""
    emby_device_filter: str = ""
    emby_entity_id: str = ""
    shield_entity_id: str = ""
    poll_interval: float = 5.0
    end_tolerance: float = 5.0
    stopped_grace: float = 15.0
    ui_schema_version: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Load known fields and migrate the legacy single-target format."""
        known = cls.__dataclass_fields__
        values = {key: value for key, value in data.items() if key in known}
        raw_actions = values.pop("target_actions", [])
        settings = cls(**values)
        if isinstance(raw_actions, list):
            settings.target_actions = [
                TargetAction(
                    entity_id=str(item.get("entity_id", "")).strip(),
                    command_id=str(item.get("command_id", "")).strip(),
                    name=str(item.get("name", "")).strip(),
                )
                for item in raw_actions
                if isinstance(item, dict)
                and str(item.get("entity_id", "")).strip()
                and str(item.get("command_id", "")).strip()
            ]
        if not settings.target_actions and settings.target_entity_id:
            settings.target_actions = [
                TargetAction(
                    settings.target_entity_id,
                    settings.target_command_id or "macro.start",
                )
            ]
        return settings

    def resolved_target_actions(self) -> list[TargetAction]:
        """Return valid, de-duplicated actions including legacy settings."""
        source: list[TargetAction | dict] = list(self.target_actions)
        if not source and self.target_entity_id:
            source = [
                TargetAction(
                    self.target_entity_id,
                    self.target_command_id or "macro.start",
                )
            ]

        actions: list[TargetAction] = []
        seen: set[tuple[str, str]] = set()
        for item in source:
            if isinstance(item, TargetAction):
                action = item
            elif isinstance(item, dict):
                action = TargetAction(
                    entity_id=str(item.get("entity_id", "")).strip(),
                    command_id=str(item.get("command_id", "")).strip(),
                    name=str(item.get("name", "")).strip(),
                )
            else:
                continue
            key = (action.entity_id.strip(), action.command_id.strip())
            if not all(key) or key in seen:
                continue
            seen.add(key)
            actions.append(TargetAction(*key, action.name.strip()))
        return actions


class ConfigStore:
    """Read and atomically persist the integration settings."""

    def __init__(self, config_dir: str) -> None:
        self._path = Path(config_dir) / _CONFIG_FILE
        self.settings = Settings()
        self.load()

    def load(self) -> bool:
        """Load settings if a configuration exists."""
        try:
            with self._path.open(encoding="utf-8") as file:
                self.settings = Settings.from_dict(json.load(file))
            return True
        except FileNotFoundError:
            return False
        except (OSError, ValueError, TypeError):
            _LOG.exception("Cannot load configuration")
            return False

    def save(self, settings: Settings) -> bool:
        """Persist settings without exposing secrets in logs."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(asdict(settings), file, ensure_ascii=False, indent=2)
            temporary.replace(self._path)
            self.settings = settings
            return True
        except OSError:
            _LOG.exception("Cannot store configuration")
            return False
