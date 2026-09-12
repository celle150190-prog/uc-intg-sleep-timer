"""Persistent configuration for the Sleep Timer integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path

_LOG = logging.getLogger(__name__)
_CONFIG_FILE = "config.json"


@dataclass(slots=True)
class Settings:
    """Integration settings."""

    core_url: str = "http://127.0.0.1:8080"
    core_api_key: str = ""
    target_entity_id: str = ""
    target_command_id: str = "macro.start"
    emby_url: str = ""
    emby_api_key: str = ""
    emby_device_filter: str = ""
    emby_entity_id: str = ""
    shield_entity_id: str = ""
    poll_interval: float = 5.0
    end_tolerance: float = 5.0
    stopped_grace: float = 15.0

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Load known fields and ignore fields added by future versions."""
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})


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
