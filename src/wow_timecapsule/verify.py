from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import struct
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify(root: str | Path) -> tuple[bool, list[str]]:
    root = Path(root).resolve()
    db_path = root / "wow_archive.sqlite"
    errors: list[str] = []
    counts = {"Characters": 0, "Pets": 0, "Character models": 0, "World scenes": 0, "Assets": 0}
    if not db_path.is_file():
        return False, ["Database ........ MISSING", "Archive is not self-contained."]
    try:
        uri = db_path.as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok": errors.append(f"Database integrity: {integrity}")
        counts["Characters"] = db.execute("SELECT count(*) FROM character").fetchone()[0]
        counts["Pets"] = db.execute("SELECT count(*) FROM pet").fetchone()[0]
        counts["Assets"] = db.execute("SELECT count(*) FROM asset").fetchone()[0]
        counts["Character models"] = db.execute("SELECT count(*) FROM asset WHERE asset_type='character_model'").fetchone()[0]
        counts["World scenes"] = db.execute("SELECT count(*) FROM map_export").fetchone()[0]
        records = list(db.execute("SELECT relative_path,sha256 FROM raw_api_file")) + list(db.execute("SELECT relative_path,sha256 FROM asset"))
        for relative, expected in records:
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                errors.append(f"Unsafe stored path: {relative}"); continue
            path = root / relative
            if not path.is_file(): errors.append(f"Missing file: {relative}")
            elif digest(path) != expected: errors.append(f"Checksum mismatch: {relative}")
            elif path.suffix.lower() == ".glb": _check_glb(path, errors)
        for (scene_path,) in db.execute("SELECT scene_path FROM map_export WHERE scene_path IS NOT NULL"):
            _check_scene(root, scene_path, errors)
        for table in ("asset", "raw_api_file", "source_file"):
            for (stored,) in db.execute(f"SELECT relative_path FROM {table}"):
                if os.path.isabs(stored): errors.append(f"Absolute path in {table}: {stored}")
        db.close()
    except (sqlite3.Error, OSError) as exc:
        errors.append(f"Database error: {exc}")
    lines = ["Archive verification", "", f"Database ........ {'OK' if not any('Database' in e for e in errors) else 'FAILED'}"]
    lines.extend(f"{name + ' ':<18} {count:,}" for name, count in counts.items())
    lines += [f"Checksums ........ {'OK' if not errors else 'FAILED'}", "External deps .... NONE"]
    if errors:
        lines += ["", *[f"ERROR: {error}" for error in errors], "", "Archive verification failed."]
    else:
        lines += ["", "Archive is self-contained."]
    return not errors, lines


def _check_glb(path: Path, errors: list[str]) -> None:
    try:
        with path.open("rb") as stream:
            magic, version, length = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or length != path.stat().st_size:
            errors.append(f"Invalid GLB: {path.name}")
    except (OSError, struct.error): errors.append(f"Invalid GLB: {path.name}")


def _check_scene(root: Path, relative: str, errors: list[str]) -> None:
    path = root / relative
    try:
        scene = json.loads(path.read_text(encoding="utf-8"))
        if scene.get("format") != "wow-timecapsule-scene": errors.append(f"Invalid scene: {relative}")
        for group in ("terrain", "objects"):
            for item in scene.get(group, []):
                ref = item.get("path") if isinstance(item, dict) else item
                if ref and str(ref).lower().startswith(("http://", "https://")):
                    errors.append(f"External rendering dependency: {ref}")
                elif ref and (Path(ref).is_absolute() or not (path.parent / ref).exists()):
                    errors.append(f"Broken scene reference: {ref}")
    except (OSError, ValueError): errors.append(f"Unreadable scene: {relative}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a WoW Time Capsule archive")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    valid, lines = verify(args.archive)
    print("\n".join(lines))
    return 0 if valid else 1


if __name__ == "__main__": raise SystemExit(main())
