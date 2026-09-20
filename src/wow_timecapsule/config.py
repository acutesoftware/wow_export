from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
    return base / "WoWTimeCapsule" / "config.json"


@dataclass(slots=True)
class Config:
    wow_path: str = ""
    wow_export_path: str = ""
    archive_path: str = ""
    region: str = "us"
    locale: str = "en_US"
    client_id: str = ""
    client_secret: str = ""

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{key: values.get(key, "") for key in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

