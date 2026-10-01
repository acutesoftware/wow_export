from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .api import CharacterRef


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._") or "unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Archive:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "wow_archive.sqlite"
        self.db = sqlite3.connect(self.database)
        self._migrate_character_identity()
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.db.executescript(schema)
        self._migrate_achievement_reference_columns()
        self._migrate_quest_reference_columns()
        self._migrate_legacy_collections()
        self._backfill_profession_tiers()
        screenshot_columns = {
            row[1] for row in self.db.execute("PRAGMA table_info(screenshot)")
        }
        if "sha256" not in screenshot_columns:
            self.db.execute("ALTER TABLE screenshot ADD COLUMN sha256 TEXT")
        if "captured_at" not in screenshot_columns:
            self.db.execute("ALTER TABLE screenshot ADD COLUMN captured_at TEXT")
        if "source_path" not in screenshot_columns:
            self.db.execute("ALTER TABLE screenshot ADD COLUMN source_path TEXT")
        self._migrate_screenshots_to_global()
        screenshot_columns = {
            row[1] for row in self.db.execute("PRAGMA table_info(screenshot)")
        }
        screenshot_additions = {
            "screenshot_root_id": "INTEGER REFERENCES screenshot_root",
            "size_bytes": "INTEGER",
            "modified_ns": "INTEGER",
            "is_available": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, column_type in screenshot_additions.items():
            if name not in screenshot_columns:
                self.db.execute(f"ALTER TABLE screenshot ADD COLUMN {name} {column_type}")
        self.db.execute("DROP INDEX IF EXISTS screenshot_source_path_unique")
        self.db.execute(
            "CREATE UNIQUE INDEX screenshot_source_path_unique ON screenshot(source_path)"
        )
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.commit()

    def _migrate_achievement_reference_columns(self) -> None:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(achievement)")}
        additions = {
            "requirements": "TEXT",
            "reward_description": "TEXT",
            "is_account_wide": "INTEGER",
            "display_order": "INTEGER",
            "reference_json": "TEXT",
        }
        for name, column_type in additions.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE achievement ADD COLUMN {name} {column_type}")

    def _migrate_quest_reference_columns(self) -> None:
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(quest)")}
        for name in ("description", "requirements", "category", "reference_json"):
            if name not in columns:
                self.db.execute(f"ALTER TABLE quest ADD COLUMN {name} TEXT")

    def _migrate_screenshots_to_global(self) -> None:
        columns = {
            row[1]: row for row in self.db.execute("PRAGMA table_info(screenshot)")
        }
        if not columns or "character_id" not in columns:
            return
        self.db.executescript("""
            CREATE TABLE screenshot_global (
                screenshot_id INTEGER PRIMARY KEY,
                relative_path TEXT NOT NULL UNIQUE,
                caption TEXT,
                added_at TEXT NOT NULL,
                captured_at TEXT,
                source_path TEXT,
                sha256 TEXT
            );
            INSERT INTO screenshot_global(
                screenshot_id,relative_path,caption,added_at,
                captured_at,source_path,sha256
            )
            SELECT screenshot_id,relative_path,caption,added_at,
                   captured_at,source_path,sha256
            FROM screenshot;
            DROP TABLE screenshot;
            ALTER TABLE screenshot_global RENAME TO screenshot;
        """)

    def _backfill_profession_tiers(self) -> None:
        """Re-import preserved profession JSON from archives made before tier support."""
        rows = self.db.execute("""
            SELECT archive_run_id,relative_path,observed_at
            FROM raw_api_file WHERE relative_path LIKE '%_professions.json'
        """).fetchall()
        for run_id, relative_path, observed_at in rows:
            relative = Path(relative_path)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            source = self.root / relative
            if not source.is_file():
                continue
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            snapshots = self.db.execute(
                "SELECT character_snapshot_id,observed_at FROM character_snapshot "
                "WHERE archive_run_id=?",
                (run_id,),
            ).fetchall()
            for snapshot_id, snapshot_observed in snapshots:
                self._import_professions(
                    int(snapshot_id), data, snapshot_observed or observed_at or now()
                )

    def _migrate_character_identity(self) -> None:
        exists = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='character'"
        ).fetchone()
        if not exists:
            return
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(character)")}
        if "namespace" in columns:
            return
        self.db.executescript("""
            CREATE TABLE character_new (
                character_id INTEGER PRIMARY KEY,
                blizzard_character_id INTEGER,
                region TEXT NOT NULL,
                realm_id INTEGER,
                realm_slug TEXT NOT NULL,
                realm_name TEXT,
                character_name TEXT NOT NULL,
                namespace TEXT NOT NULL DEFAULT 'profile',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(region, realm_slug, character_name, namespace)
            );
            INSERT INTO character_new(
                character_id,blizzard_character_id,region,realm_id,realm_slug,
                realm_name,character_name,namespace,first_seen_at,last_seen_at
            )
            SELECT character_id,blizzard_character_id,region,realm_id,realm_slug,
                   realm_name,character_name,'profile',first_seen_at,last_seen_at
            FROM character;
            DROP TABLE character;
            ALTER TABLE character_new RENAME TO character;
        """)

    def _migrate_legacy_collections(self) -> None:
        """Move pre-shared-collection records without requiring another export."""
        legacy = {
            row[0] for row in self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('character_pet','character_mount')"
            )
        }
        definitions = (
            ("character_pet", "pets", "pet_id", "level,quality,breed,is_favorite", "collection_pet"),
            ("character_mount", "mounts", "mount_id", "is_collected", "collection_mount"),
        )
        for source, kind, item_column, value_columns, destination in definitions:
            if source not in legacy:
                continue
            runs = self.db.execute(f"""
                SELECT cs.archive_run_id,MIN(src.observed_at),COUNT(DISTINCT src.{item_column})
                FROM {source} src
                JOIN character_snapshot cs
                  ON cs.character_snapshot_id=src.character_snapshot_id
                GROUP BY cs.archive_run_id
            """).fetchall()
            for run_id, observed_at, count in runs:
                exists = self.db.execute(
                    "SELECT 1 FROM collection_snapshot WHERE archive_run_id=? AND kind=?",
                    (run_id, kind),
                ).fetchone()
                if exists:
                    continue
                collection_id = self.db.execute(
                    "INSERT INTO collection_snapshot(archive_run_id,kind,observed_at,status,record_count,detail) VALUES(?,?,?,?,?,?)",
                    (run_id, kind, observed_at or now(), "captured", count,
                     "Migrated from an older archive schema."),
                ).lastrowid
                selected_values = ",".join(f"src.{name}" for name in value_columns.split(","))
                self.db.execute(f"""
                    INSERT OR IGNORE INTO {destination}
                    SELECT ?,src.{item_column},{selected_values},NULL
                    FROM {source} src
                    JOIN character_snapshot cs
                      ON cs.character_snapshot_id=src.character_snapshot_id
                    WHERE cs.archive_run_id=?
                """, (collection_id, run_id))

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def run(self, *, region: str, locale: str) -> Iterator[int]:
        started = now()
        cursor = self.db.execute(
            "INSERT INTO archive_run(started_at,app_version,region,locale,status) VALUES(?,?,?,?,?)",
            (started, __version__, region, locale, "running"),
        )
        run_id = int(cursor.lastrowid)
        self.db.commit()
        try:
            yield run_id
        except Exception as exc:
            self.db.rollback()
            self.db.execute("UPDATE archive_run SET completed_at=?,status=?,notes=? WHERE archive_run_id=?", (now(), "failed", str(exc)[:2000], run_id))
            self.db.commit()
            raise
        else:
            self.db.execute("UPDATE archive_run SET completed_at=?,status=? WHERE archive_run_id=?", (now(), "complete", run_id))
            self.db.commit()
            self.write_readme()

    def save_raw(self, run_id: int, name: str, endpoint: str, payload: dict, status: int, observed: str | None = None) -> str:
        observed = observed or now()
        day = observed[:10]
        target = self.root / "raw" / "api" / day / f"run_{run_id}_{safe_name(name)}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        relative = target.relative_to(self.root).as_posix()
        self.db.execute("INSERT INTO raw_api_file(archive_run_id,endpoint,relative_path,sha256,http_status,observed_at) VALUES(?,?,?,?,?,?)", (run_id, endpoint, relative, sha256(target), status, observed))
        return relative

    def import_capture(self, run_id: int, character: CharacterRef, captured: dict[str, dict], observed: str | None = None) -> int:
        observed = observed or now()
        profile = captured["character_profile"]
        row = self.db.execute("SELECT character_id FROM character WHERE region=? AND realm_slug=? AND character_name=? COLLATE NOCASE AND namespace=?", (character.region, character.realm_slug, character.name, character.namespace)).fetchone()
        if row:
            character_id = row[0]
            self.db.execute("UPDATE character SET last_seen_at=?,blizzard_character_id=COALESCE(?,blizzard_character_id),realm_name=COALESCE(NULLIF(?,''),realm_name) WHERE character_id=?", (observed, character.character_id, character.realm_name, character_id))
        else:
            character_id = self.db.execute("INSERT INTO character(blizzard_character_id,region,realm_id,realm_slug,realm_name,character_name,namespace,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?)", (character.character_id, character.region, character.realm_id, character.realm_slug, character.realm_name, character.name, character.namespace, observed, observed)).lastrowid
        def named(obj: Any) -> Any:
            return obj.get("name") if isinstance(obj, dict) else obj
        snapshot = self.db.execute("""INSERT INTO character_snapshot(character_id,archive_run_id,observed_at,level,race_id,race_name,class_id,class_name,specialization,faction,guild_name,achievement_points,last_login_if_available,raw_json_path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            character_id, run_id, observed, profile.get("level"), profile.get("race", {}).get("id"), named(profile.get("race")), profile.get("character_class", {}).get("id"), named(profile.get("character_class")), named(profile.get("active_spec")), named(profile.get("faction")), named(profile.get("guild")), profile.get("achievement_points"), profile.get("last_login_timestamp"), self._raw_path(run_id, "character_profile"),
        )).lastrowid
        self._import_achievements(snapshot, captured.get("achievements", {}), observed)
        self._import_equipment(snapshot, captured.get("equipment", {}), observed)
        self._import_hunter_pets(snapshot, captured.get("hunter_pets", {}))
        outcomes = captured.get("_outcomes", {})
        pets_outcome = outcomes.get("pets") or ({"status": "captured", "count": len(captured["pets"].get("pets", []))} if "pets" in captured else {})
        mounts_outcome = outcomes.get("mounts") or ({"status": "captured", "count": len(captured["mounts"].get("mounts", []))} if "mounts" in captured else {})
        self._import_account_collection(run_id, "pets", captured.get("pets", {}), pets_outcome, observed)
        self._import_account_collection(run_id, "mounts", captured.get("mounts", {}), mounts_outcome, observed)
        self._import_professions(snapshot, captured.get("professions", {}), observed)
        self._import_simple(snapshot, captured.get("reputations", {}), "reputation", observed)
        self._import_stats(snapshot, captured.get("statistics", {}), observed)
        self._import_quests(snapshot, captured.get("quests", {}), observed)
        self._import_capture_outcomes(snapshot, run_id, outcomes)
        return int(snapshot)

    def _raw_path(self, run_id: int, name: str) -> str | None:
        row = self.db.execute("SELECT relative_path FROM raw_api_file WHERE archive_run_id=? AND relative_path LIKE ?", (run_id, f"%_{safe_name(name)}.json")).fetchone()
        return row[0] if row else None

    def _import_achievements(self, sid: int, data: dict, observed: str) -> None:
        references = data.get("_reference_details", {})
        for item in data.get("achievements", []):
            detail = item.get("achievement", item)
            aid = detail.get("id")
            if aid is None: continue
            reference = references.get(str(aid), references.get(aid, {}))
            category = reference.get("category", item.get("category", {}))
            category_name = category.get("name") if isinstance(category, dict) else str(category or "")
            self.db.execute("""
                INSERT INTO achievement(
                    achievement_id,name,description,points,category,requirements,
                    reward_description,is_account_wide,display_order,reference_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(achievement_id) DO UPDATE SET
                    name=COALESCE(excluded.name,achievement.name),
                    description=COALESCE(excluded.description,achievement.description),
                    points=COALESCE(excluded.points,achievement.points),
                    category=COALESCE(NULLIF(excluded.category,''),achievement.category),
                    requirements=COALESCE(excluded.requirements,achievement.requirements),
                    reward_description=COALESCE(excluded.reward_description,achievement.reward_description),
                    is_account_wide=COALESCE(excluded.is_account_wide,achievement.is_account_wide),
                    display_order=COALESCE(excluded.display_order,achievement.display_order),
                    reference_json=COALESCE(excluded.reference_json,achievement.reference_json)
            """, (
                aid, reference.get("name") or detail.get("name"),
                reference.get("description") or item.get("description"),
                reference.get("points", item.get("points")), category_name,
                self._achievement_requirements(reference.get("criteria", {})),
                reference.get("reward_description"),
                int(bool(reference.get("is_account_wide"))) if "is_account_wide" in reference else None,
                reference.get("display_order"),
                json.dumps(reference, ensure_ascii=False) if reference else None,
            ))
            completed = item.get("completed_timestamp")
            criteria = item.get("criteria", {})
            is_completed = bool(
                completed or item.get("is_completed") or
                (criteria.get("is_completed") if isinstance(criteria, dict) else False)
            )
            self.db.execute("INSERT OR IGNORE INTO character_achievement VALUES(?,?,?,?,?,?)", (sid, aid, int(is_completed), str(completed) if completed else None, json.dumps(criteria) if criteria else None, observed))

    @staticmethod
    def _achievement_requirements(criteria: Any) -> str | None:
        if not isinstance(criteria, dict) or not criteria:
            return None
        lines: list[str] = []

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            description = node.get("description") or node.get("name")
            amount = node.get("amount")
            if description:
                text = str(description)
                if amount not in (None, 0, 1):
                    text += f" ({amount})"
                lines.append(text)
            elif amount not in (None, 0):
                lines.append(f"Complete {amount} required objective(s)")
            for child in node.get("child_criteria", []):
                walk(child)

        walk(criteria)
        return "\n".join(dict.fromkeys(lines)) or None

    def achievement_reference_ids(self) -> set[int]:
        return {
            int(row[0]) for row in self.db.execute(
                "SELECT achievement_id FROM achievement WHERE reference_json IS NOT NULL"
            )
        }

    def quest_reference_ids(self) -> set[int]:
        return {
            int(row[0]) for row in self.db.execute(
                "SELECT quest_id FROM quest WHERE reference_json IS NOT NULL"
            )
        }

    def _import_equipment(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("equipped_items", []):
            iid, slot = item.get("item", {}).get("id"), item.get("slot", {}).get("type")
            if iid is None: continue
            self.db.execute("INSERT OR IGNORE INTO equipment(blizzard_item_id,name,slot_type) VALUES(?,?,?)", (iid, item.get("name"), slot))
            eid = self.db.execute("SELECT equipment_id FROM equipment WHERE blizzard_item_id=? AND slot_type IS ?", (iid, slot)).fetchone()[0]
            self.db.execute("INSERT OR IGNORE INTO character_equipment VALUES(?,?,?,?)", (sid, eid, observed, json.dumps(item)))

    def _import_account_collection(self, run_id: int, kind: str, data: dict,
                                   outcome: dict, observed: str) -> None:
        status = str(outcome.get("status") or "unavailable")
        collection_id = self.db.execute(
            "INSERT INTO collection_snapshot(archive_run_id,kind,observed_at,status,record_count,detail) VALUES(?,?,?,?,?,?)",
            (run_id, kind, observed, status, outcome.get("count"), outcome.get("detail")),
        ).lastrowid
        if status != "captured":
            return
        if kind == "mounts":
            self._import_collection_mounts(int(collection_id), data)
        else:
            self._import_collection_pets(int(collection_id), data)

    def _import_collection_pets(self, collection_id: int, data: dict) -> None:
        for item in data.get("pets", []):
            guid = item.get("id") or f"species:{item.get('species', {}).get('id')}:{item.get('name', '')}"
            species = item.get("species", {})
            display = item.get("creature_display", item.get("display", {}))
            self.db.execute("INSERT OR IGNORE INTO pet(pet_guid,species_id,display_id,creature_id,name,custom_name) VALUES(?,?,?,?,?,?)", (guid, species.get("id"), display.get("id"), item.get("creature", {}).get("id"), species.get("name") or item.get("name"), item.get("name")))
            pid = self.db.execute("SELECT pet_id FROM pet WHERE pet_guid=?", (guid,)).fetchone()[0]
            self.db.execute("INSERT OR IGNORE INTO collection_pet(collection_snapshot_id,pet_id,level,quality,breed,is_favorite,raw_json) VALUES(?,?,?,?,?,?,?)", (collection_id, pid, item.get("level"), str(item.get("quality", {}).get("name", "")), str(item.get("breed_id", "")), int(bool(item.get("is_favorite"))), json.dumps(item)))

    def _import_collection_mounts(self, collection_id: int, data: dict) -> None:
        for item in data.get("mounts", []):
            mount = item.get("mount", item); mid = mount.get("id")
            if mid is None: continue
            self.db.execute("INSERT OR IGNORE INTO mount VALUES(?,?)", (mid, mount.get("name")))
            self.db.execute("INSERT OR IGNORE INTO collection_mount VALUES(?,?,?,?)", (collection_id, mid, int(item.get("is_collected", True)), json.dumps(item)))

    def _import_hunter_pets(self, sid: int, data: dict) -> None:
        for index, item in enumerate(data.get("hunter_pets", [])):
            creature = item.get("creature", {})
            species = item.get("species", {})
            display = item.get("creature_display", {})
            key = str(item.get("id") or item.get("slot") or creature.get("id") or f"pet-{index}")
            self.db.execute(
                "INSERT OR IGNORE INTO character_hunter_pet(character_snapshot_id,pet_key,name,species_id,creature_id,display_id,level,slot,is_active,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (sid, key, item.get("name"), species.get("id"), creature.get("id"),
                 display.get("id"), item.get("level"), item.get("slot"),
                 int(bool(item.get("is_active") or item.get("is_selected"))), json.dumps(item)),
            )

    def _import_capture_outcomes(self, sid: int, run_id: int, outcomes: dict) -> None:
        for section, outcome in outcomes.items():
            self.db.execute(
                "INSERT OR REPLACE INTO capture_section(character_snapshot_id,section_name,status,record_count,detail,raw_json_path) VALUES(?,?,?,?,?,?)",
                (sid, section, outcome.get("status", "unavailable"), outcome.get("count"),
                 outcome.get("detail"), self._raw_path(run_id, section)),
            )

    def capture_summary(self, snapshot_id: int) -> list[dict[str, Any]]:
        return [
            {"section": row[0], "status": row[1], "count": row[2], "detail": row[3] or ""}
            for row in self.db.execute(
                "SELECT section_name,status,record_count,detail FROM capture_section WHERE character_snapshot_id=? ORDER BY section_name",
                (snapshot_id,),
            )
        ]

    def add_memory(self, character_id: int, title: str, body: str) -> None:
        self.db.execute(
            "INSERT INTO character_memory(character_id,title,body,created_at) VALUES(?,?,?,?)",
            (character_id, title.strip(), body.strip(), now()),
        )
        self.db.commit()

    def add_screenshot(
        self, source: str | Path, caption: str = "",
        captured_at: str | None = None,
    ) -> Path:
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        captured_at = captured_at or self._screenshot_date(source)
        stat = source.stat()
        absolute = str(source)
        self.db.execute(
            """INSERT INTO screenshot(
                   screenshot_root_id,relative_path,caption,added_at,captured_at,
                   source_path,size_bytes,modified_ns,is_available,sha256
               ) VALUES(NULL,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(source_path) DO UPDATE SET
                   caption=COALESCE(NULLIF(excluded.caption,''),screenshot.caption),
                   captured_at=excluded.captured_at,size_bytes=excluded.size_bytes,
                   modified_ns=excluded.modified_ns,is_available=1""",
            (absolute, caption.strip(), now(), captured_at, absolute,
             stat.st_size, stat.st_mtime_ns, 1),
        )
        self.db.commit()
        return source

    def import_screenshot_folder(
        self, root: str | Path,
        progress: Any = None,
    ) -> dict[str, int]:
        root = Path(root).resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        root_id = self.db.execute(
            "INSERT INTO screenshot_root(root_path,added_at) VALUES(?,?) "
            "ON CONFLICT(root_path) DO UPDATE SET root_path=excluded.root_path "
            "RETURNING screenshot_root_id",
            (str(root), now()),
        ).fetchone()[0]
        return self._scan_screenshot_root(int(root_id), root, progress)

    def rescan_screenshot_folders(self, progress: Any = None) -> dict[str, int]:
        totals = {
            "roots": 0, "scanned": 0, "imported": 0, "updated": 0,
            "unchanged": 0, "missing": 0, "errors": 0,
        }
        for root_id, root_path in self.db.execute(
            "SELECT screenshot_root_id,root_path FROM screenshot_root ORDER BY root_path"
        ).fetchall():
            totals["roots"] += 1
            try:
                result = self._scan_screenshot_root(
                    int(root_id), Path(root_path), None
                )
                for key in totals.keys() - {"roots"}:
                    totals[key] += result.get(key, 0)
            except (OSError, sqlite3.Error):
                totals["errors"] += 1
                totals["missing"] += self.db.execute(
                    "SELECT COUNT(*) FROM screenshot "
                    "WHERE screenshot_root_id=? AND is_available=0",
                    (root_id,),
                ).fetchone()[0]
            if progress:
                progress(dict(totals))
        return totals

    def _scan_screenshot_root(
        self, root_id: int, root: Path, progress: Any = None,
    ) -> dict[str, int]:
        if not root.is_dir():
            self.db.execute(
                "UPDATE screenshot SET is_available=0 WHERE screenshot_root_id=?",
                (root_id,),
            )
            self.db.commit()
            raise NotADirectoryError(root)
        extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
        result = {
            "roots": 1, "scanned": 0, "imported": 0, "updated": 0,
            "unchanged": 0, "missing": 0, "errors": 0,
        }
        self.db.execute(
            "UPDATE screenshot SET is_available=0 WHERE screenshot_root_id=?", (root_id,)
        )
        for source in root.rglob("*"):
            if not source.is_file() or source.suffix.lower() not in extensions:
                continue
            result["scanned"] += 1
            try:
                relative_source = source.relative_to(root).as_posix()
                absolute = str(source.resolve())
                stat = source.stat()
                existing = self.db.execute(
                    "SELECT size_bytes,modified_ns FROM screenshot WHERE source_path=?",
                    (absolute,),
                ).fetchone()
                captured_at = self._screenshot_date(source, read_exif=False)
                self.db.execute("""
                    INSERT INTO screenshot(
                        screenshot_root_id,relative_path,caption,added_at,captured_at,
                        source_path,size_bytes,modified_ns,is_available,sha256
                    ) VALUES(?,?,?,?,?,?,?,?,1,NULL)
                    ON CONFLICT(source_path) DO UPDATE SET
                        screenshot_root_id=excluded.screenshot_root_id,
                        relative_path=excluded.relative_path,
                        captured_at=excluded.captured_at,
                        size_bytes=excluded.size_bytes,
                        modified_ns=excluded.modified_ns,is_available=1
                """, (
                    root_id, absolute, relative_source, now(), captured_at,
                    absolute, stat.st_size, stat.st_mtime_ns,
                ))
                if existing is None:
                    result["imported"] += 1
                elif existing != (stat.st_size, stat.st_mtime_ns):
                    result["updated"] += 1
                else:
                    result["unchanged"] += 1
            except (OSError, ValueError, sqlite3.Error):
                result["errors"] += 1
            if progress and result["scanned"] % 25 == 0:
                progress(dict(result))
            if result["scanned"] % 100 == 0:
                self.db.commit()
        self.db.commit()
        result["missing"] = self.db.execute(
            "SELECT COUNT(*) FROM screenshot WHERE screenshot_root_id=? AND is_available=0",
            (root_id,),
        ).fetchone()[0]
        self.db.execute(
            "UPDATE screenshot_root SET last_scanned_at=? WHERE screenshot_root_id=?",
            (now(), root_id),
        )
        self.db.commit()
        if progress:
            progress(dict(result))
        return result

    @staticmethod
    def _screenshot_date(source: Path, read_exif: bool = True) -> str:
        match = re.search(
            r"(?:WoWScrnShot[_-])?(\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})",
            source.stem, re.IGNORECASE,
        )
        if match:
            try:
                parsed = datetime.strptime("".join(match.groups()), "%m%d%y%H%M%S")
                return parsed.astimezone().isoformat(timespec="seconds")
            except ValueError:
                pass
        try:
            if not read_exif:
                raise ImportError
            from PIL import Image

            with Image.open(source) as image:
                exif = image.getexif()
                for tag in (36867, 36868, 306):
                    value = exif.get(tag)
                    if value:
                        parsed = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                        return parsed.astimezone().isoformat(timespec="seconds")
        except (ImportError, OSError, ValueError):
            pass
        return datetime.fromtimestamp(source.stat().st_mtime).astimezone().isoformat(
            timespec="seconds"
        )

    def _import_simple(self, sid: int, data: dict, kind: str, observed: str) -> None:
        keys = ("reputations",)
        for key in keys:
            for item in data.get(key, []):
                obj = item.get(kind, item.get("faction", item)); oid = obj.get("id")
                if oid is None: continue
                self.db.execute(f"INSERT OR IGNORE INTO {kind} VALUES(?,?)", (oid, obj.get("name")))
                self.db.execute("INSERT OR IGNORE INTO character_reputation VALUES(?,?,?,?,?)", (sid, oid, str(item.get("standing", {}).get("name", "")), item.get("standing", {}).get("value"), observed))

    def _import_professions(self, sid: int, data: dict, observed: str) -> None:
        for group in ("primaries", "secondaries"):
            for item in data.get(group, []):
                profession = item.get("profession", item)
                profession_id = profession.get("id")
                if profession_id is None:
                    continue
                self.db.execute(
                    "INSERT INTO profession(profession_id,name) VALUES(?,?) "
                    "ON CONFLICT(profession_id) DO UPDATE SET "
                    "name=COALESCE(excluded.name,profession.name)",
                    (profession_id, profession.get("name")),
                )
                tiers = item.get("tiers", [])
                if tiers:
                    total_skill = sum(int(tier.get("skill_points") or 0) for tier in tiers)
                    total_max = sum(int(tier.get("max_skill_points") or 0) for tier in tiers)
                else:
                    total_skill = item.get("skill_points")
                    total_max = item.get("max_skill_points")
                self.db.execute(
                    "INSERT OR REPLACE INTO character_profession VALUES(?,?,?,?,?)",
                    (sid, profession_id, total_skill, total_max, observed),
                )
                for tier_item in tiers:
                    tier = tier_item.get("tier", tier_item)
                    tier_id = tier.get("id")
                    if tier_id is None:
                        continue
                    self.db.execute(
                        "INSERT INTO profession_tier(profession_tier_id,profession_id,name) "
                        "VALUES(?,?,?) ON CONFLICT(profession_tier_id) DO UPDATE SET "
                        "profession_id=excluded.profession_id,"
                        "name=COALESCE(excluded.name,profession_tier.name)",
                        (tier_id, profession_id, tier.get("name")),
                    )
                    recipes = tier_item.get("known_recipes", [])
                    self.db.execute(
                        "INSERT OR REPLACE INTO character_profession_tier VALUES(?,?,?,?,?,?,?)",
                        (sid, tier_id, tier_item.get("skill_points"),
                         tier_item.get("max_skill_points"), len(recipes), observed,
                         json.dumps(tier_item, ensure_ascii=False)),
                    )
                    for recipe in recipes:
                        recipe_id = recipe.get("id")
                        if recipe_id is None:
                            continue
                        self.db.execute(
                            "INSERT INTO recipe(recipe_id,name,reference_json) VALUES(?,?,?) "
                            "ON CONFLICT(recipe_id) DO UPDATE SET "
                            "name=COALESCE(excluded.name,recipe.name),"
                            "reference_json=COALESCE(excluded.reference_json,recipe.reference_json)",
                            (recipe_id, recipe.get("name"),
                             json.dumps(recipe, ensure_ascii=False)),
                        )
                        self.db.execute(
                            "INSERT OR IGNORE INTO character_known_recipe VALUES(?,?,?,?)",
                            (sid, tier_id, recipe_id, observed),
                        )

    def _import_stats(self, sid: int, data: dict, observed: str) -> None:
        for name, value in data.items():
            if isinstance(value, (int, float)):
                self.db.execute("INSERT INTO character_stat VALUES(?,?,?,?)", (sid, name, value, observed))

    def _import_quests(self, sid: int, data: dict, observed: str) -> None:
        references = data.get("_reference_details", {})
        for item in data.get("quests", []):
            qid = item.get("id");
            if qid is None: continue
            reference = references.get(str(qid), references.get(qid, {}))
            requirements = reference.get("requirements")
            category = reference.get("category", {})
            category_name = category.get("name") if isinstance(category, dict) else category
            self.db.execute("""
                INSERT INTO quest(
                    quest_id,name,description,requirements,category,reference_json
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(quest_id) DO UPDATE SET
                    name=COALESCE(excluded.name,quest.name),
                    description=COALESCE(excluded.description,quest.description),
                    requirements=COALESCE(excluded.requirements,quest.requirements),
                    category=COALESCE(excluded.category,quest.category),
                    reference_json=COALESCE(excluded.reference_json,quest.reference_json)
            """, (
                qid, reference.get("title") or reference.get("name") or item.get("name"),
                reference.get("description"),
                json.dumps(requirements, ensure_ascii=False) if requirements else None,
                category_name,
                json.dumps(reference, ensure_ascii=False) if reference else None,
            ))
            self.db.execute("INSERT OR IGNORE INTO character_quest VALUES(?,?,?,?,?)", (sid, qid, "completed", None, observed))

    def write_readme(self) -> None:
        chars = self.db.execute("SELECT character_name,realm_name,region FROM character ORDER BY character_name").fetchall()
        run = self.db.execute("SELECT completed_at FROM archive_run WHERE status='complete' ORDER BY archive_run_id DESC LIMIT 1").fetchone()
        lines = ["# WoW Time Capsule Archive", "", "This is a local, preservation-oriented archive of character information obtained from Blizzard's APIs. It contains original JSON responses, a standard SQLite index, and a local HTML album.", "", "## Characters", ""]
        lines += [f"- {name} — {realm or 'unknown realm'} ({region.upper()})" for name, realm, region in chars] or ["- None yet"]
        lines += ["", "## Latest export", "", f"- Exported: {run[0] if run else 'unknown'}", "- Exporter version: " + __version__]
        lines += ["", "## Opening and formats", "", "Open `index.html` in a browser to view the album. Open `wow_archive.sqlite` with any SQLite 3 browser. Original Blizzard API responses are under `raw/api/` as UTF-8 JSON. Screenshot folders are external links registered in SQLite and can be refreshed with Rescan Screenshot Folders. Run `python -m wow_timecapsule.verify .` from this directory to verify database integrity, saved API files, and screenshot link availability.", "", "## Limitations", "", "This archive records what Blizzard's supported APIs exposed at each observation time. It is not a complete historical activity log and contains no game assets or 3D models. Screenshot images are not copied into this archive.", ""]
        (self.root / "README.md").write_text("\n".join(lines), encoding="utf-8")
