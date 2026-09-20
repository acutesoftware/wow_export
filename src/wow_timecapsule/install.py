from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WowProduct:
    product: str
    path: Path
    build: str | None
    version: str | None


def detect_products(root: str | Path) -> list[WowProduct]:
    root = Path(root)
    result: list[WowProduct] = []
    for product in ("_retail_", "_classic_", "_classic_era_"):
        directory = root / product
        if not directory.is_dir():
            continue
        build, version = _read_build(directory / ".build.info")
        result.append(WowProduct(product.strip("_"), directory, build, version))
    return result


def _read_build(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        if len(lines) < 2:
            return None, None
        headers = [re.sub(r"!.*$", "", h) for h in lines[0].split("|")]
        values = lines[1].split("|")
        row = dict(zip(headers, values, strict=False))
        return row.get("Build Key") or row.get("BuildKey"), row.get("Version")
    except OSError:
        return None, None

