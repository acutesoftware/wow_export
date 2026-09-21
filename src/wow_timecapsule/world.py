from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MapTile:
    x: int
    y: int

    def as_bridge_value(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True, slots=True)
class SpawnPoint:
    x: float = 0
    y: float = 0
    z: float = 0
    heading: float = 0

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "heading": self.heading}


def scene_entry(path: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"path": path}
    if source:
        for key in ("kind", "position", "rotation", "scale", "tile", "source_id"):
            if key in source:
                entry[key] = source[key]
    return entry
