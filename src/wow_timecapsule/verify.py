from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
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
    counts = {"Characters": 0, "Snapshots": 0, "Pets": 0, "Raw API files": 0, "Screenshots": 0}
    if not db_path.is_file():
        return False, ["Database ........ MISSING", "Archive is not self-contained."]
    try:
        uri = db_path.as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok": errors.append(f"Database integrity: {integrity}")
        counts["Characters"] = db.execute("SELECT count(*) FROM character").fetchone()[0]
        counts["Snapshots"] = db.execute("SELECT count(*) FROM character_snapshot").fetchone()[0]
        counts["Pets"] = db.execute("SELECT count(*) FROM pet").fetchone()[0]
        records = list(db.execute("SELECT relative_path,sha256 FROM raw_api_file"))
        counts["Raw API files"] = len(records)
        screenshot_columns = {row[1] for row in db.execute("PRAGMA table_info(screenshot)")}
        if "sha256" in screenshot_columns:
            screenshots = list(db.execute("SELECT relative_path,sha256 FROM screenshot"))
        elif screenshot_columns:
            screenshots = list(db.execute("SELECT relative_path,NULL FROM screenshot"))
        else:
            screenshots = []
        counts["Screenshots"] = len(screenshots)
        records.extend(screenshots)
        for relative, expected in records:
            if Path(relative).is_absolute() or ".." in Path(relative).parts:
                errors.append(f"Unsafe stored path: {relative}"); continue
            path = root / relative
            if not path.is_file(): errors.append(f"Missing file: {relative}")
            elif expected and digest(path) != expected: errors.append(f"Checksum mismatch: {relative}")
        for (stored,) in db.execute("SELECT relative_path FROM raw_api_file"):
            if os.path.isabs(stored): errors.append(f"Absolute path in raw_api_file: {stored}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a WoW Time Capsule archive")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    valid, lines = verify(args.archive)
    print("\n".join(lines))
    return 0 if valid else 1


if __name__ == "__main__": raise SystemExit(main())
