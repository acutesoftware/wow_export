from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .api import CharacterRef
from .world import SpawnPoint, scene_entry


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
        self.db.execute("PRAGMA foreign_keys=ON")
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.db.executescript(schema)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def run(self, *, region: str, locale: str, product: str = "", build: str = "", wow_export_version: str | None = None) -> Iterator[int]:
        started = now()
        cursor = self.db.execute(
            "INSERT INTO archive_run(started_at,app_version,wow_export_version,wow_client_build,wow_product,region,locale,status) VALUES(?,?,?,?,?,?,?,?)",
            (started, __version__, wow_export_version, build, product, region, locale, "running"),
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

    def add_asset(self, run_id: int, source: Path, destination: Path, *, asset_type: str,
                  source_name: str, source_id: str | None = None) -> int:
        """Copy an exported file into the archive and index its preservation metadata."""
        source = source.resolve()
        destination = destination.resolve()
        if destination != self.root and self.root not in destination.parents:
            raise ValueError("asset destination is outside archive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_checksum = sha256(source)
        if destination.exists():
            existing = self.db.execute(
                "SELECT asset_id,sha256 FROM asset WHERE relative_path=?",
                (destination.relative_to(self.root).as_posix(),),
            ).fetchone()
            if existing and existing[1] == source_checksum:
                return int(existing[0])
            stem, suffix = destination.stem, destination.suffix
            counter = 2
            while destination.exists():
                destination = destination.with_name(f"{stem}_{counter}{suffix}"); counter += 1
        if source != destination:
            shutil.copy2(source, destination)
        relative = destination.relative_to(self.root).as_posix()
        checksum = source_checksum
        cursor = self.db.execute(
            "INSERT INTO asset(asset_type,relative_path,format,source,source_id,sha256,file_size,created_at,archive_run_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (asset_type, relative, destination.suffix.lower().lstrip("."), source_name, source_id,
             checksum, destination.stat().st_size, now(), run_id),
        )
        return int(cursor.lastrowid)

    def add_source_file(self, run_id: int, path: Path) -> None:
        relative = path.resolve().relative_to(self.root).as_posix()
        self.db.execute(
            "INSERT INTO source_file(relative_path,sha256,file_size,archive_run_id) VALUES(?,?,?,?) ON CONFLICT(relative_path) DO UPDATE SET sha256=excluded.sha256,file_size=excluded.file_size,archive_run_id=excluded.archive_run_id",
            (relative, sha256(path), path.stat().st_size, run_id),
        )

    def preserve_character_export(self, run_id: int, snapshot_id: int, character: CharacterRef,
                                  observed: str, character_spec: dict, files: tuple[Path, ...],
                                  bridge_metadata: dict) -> Path:
        character_dir = self.root / "characters" / safe_name(
            f"{character.region}_{character.realm_slug}_{character.name}"
        )
        stamp = observed.replace(":", "").replace("-", "")
        snapshot_dir = character_dir / "snapshots" / stamp
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        descriptor = character_dir / "character.json"
        descriptor.write_text(
            json.dumps(character_spec, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        metadata_path = snapshot_dir / "source.json"
        metadata_path.write_text(
            json.dumps(self._portable_metadata(bridge_metadata), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.add_source_file(run_id, descriptor)
        self.add_source_file(run_id, metadata_path)
        primary: Path | None = None
        used: set[str] = set()
        for source in files:
            name = self._unique_name(source.name, used)
            destination = snapshot_dir / ("character.glb" if source.suffix.lower() == ".glb" and primary is None else name)
            used.add(destination.name.lower())
            asset_id = self.add_asset(run_id, source, destination, asset_type="character_model" if destination.suffix.lower() in {".glb", ".gltf", ".obj"} else "character_support", source_name="wow.export", source_id=str(character.character_id or character.name))
            self.db.execute("INSERT INTO character_asset VALUES(?,?,?)", (snapshot_id, asset_id, "primary" if destination.name == "character.glb" else "support"))
            if destination.name == "character.glb":
                relative = self.db.execute("SELECT relative_path FROM asset WHERE asset_id=?", (asset_id,)).fetchone()[0]
                primary = self.root / relative
        if primary is None:
            raise ValueError("character export has no GLB")
        return primary

    def preserve_pet_export(self, run_id: int, snapshot_id: int, pet_data: dict,
                            files: tuple[Path, ...], bridge_metadata: dict) -> Path:
        guid = str(pet_data.get("id") or pet_data.get("species", {}).get("id") or "unknown")
        pet_dir = self.root / "assets" / "pets" / safe_name(guid)
        pet_dir.mkdir(parents=True, exist_ok=True)
        pet_path = pet_dir / "pet.json"; source_path = pet_dir / "source.json"
        pet_path.write_text(json.dumps(pet_data, ensure_ascii=False, indent=2), encoding="utf-8")
        source_path.write_text(json.dumps(self._portable_metadata(bridge_metadata), ensure_ascii=False, indent=2), encoding="utf-8")
        self.add_source_file(run_id, pet_path); self.add_source_file(run_id, source_path)
        primary: Path | None = None
        used: set[str] = set()
        for source in files:
            name = "pet.glb" if source.suffix.lower() == ".glb" and primary is None else self._unique_name(source.name, used)
            used.add(name.lower()); destination = pet_dir / name
            asset_id = self.add_asset(run_id, source, destination, asset_type="pet_model" if destination.suffix.lower() in {".glb", ".gltf", ".obj"} else "pet_support", source_name="wow.export", source_id=guid)
            self.db.execute("INSERT INTO character_asset VALUES(?,?,?)", (snapshot_id, asset_id, "companion" if name == "pet.glb" else "pet_support"))
            if name == "pet.glb":
                relative = self.db.execute("SELECT relative_path FROM asset WHERE asset_id=?", (asset_id,)).fetchone()[0]
                primary = self.root / relative
        row = self.db.execute("SELECT pet_id FROM pet WHERE pet_guid=?", (guid,)).fetchone()
        if row:
            self.db.execute("UPDATE character_pet SET preserve_for_viewer=1 WHERE character_snapshot_id=? AND pet_id=?", (snapshot_id, row[0]))
        if primary is None:
            raise ValueError("pet export has no GLB")
        return primary

    def preserve_map_export(self, run_id: int, map_id: int, name: str, source_build: str,
                            files: tuple[Path, ...], bridge_metadata: dict,
                            spawn: SpawnPoint | None = None) -> Path:
        """Preserve one deliberately bounded map export and write its stable scene manifest."""
        if map_id < 0:
            raise ValueError("map_id must be non-negative")
        if not name.strip():
            raise ValueError("map export name is required")
        scene_dir = self.root / "world" / safe_name(name)
        if scene_dir.exists():
            base = scene_dir
            counter = 2
            while scene_dir.exists():
                scene_dir = base.with_name(f"{base.name}_{counter}")
                counter += 1
        scene_dir.mkdir(parents=True)
        self.db.execute("INSERT OR IGNORE INTO map(map_id,name) VALUES(?,?)", (map_id, name.strip()))
        map_export_id = self.db.execute(
            "INSERT INTO map_export(map_id,archive_run_id,name,observed_at) VALUES(?,?,?,?)",
            (map_id, run_id, name.strip(), now()),
        ).lastrowid

        terrain: list[dict] = []
        objects: list[dict] = []
        metadata_by_file = {
            str(item.get("path")): item for item in bridge_metadata.get("entries", [])
            if isinstance(item, dict) and item.get("path")
        }
        used: set[str] = set()
        for source in files:
            suffix = source.suffix.lower()
            if suffix in {".obj", ".glb", ".gltf"}:
                category = "objects" if metadata_by_file.get(source.name, {}).get("kind") in {"wmo", "m2", "object"} else "terrain"
            elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".tga", ".blp", ".mtl"}:
                category = "textures"
            else:
                category = "source"
            name_on_disk = self._unique_name(source.name, used)
            used.add(name_on_disk.lower())
            destination = scene_dir / category / name_on_disk
            asset_id = self.add_asset(run_id, source, destination, asset_type=f"world_{category.rstrip('s')}", source_name="wow.export", source_id=str(map_id))
            self.db.execute("INSERT INTO map_asset VALUES(?,?)", (map_export_id, asset_id))
            if category in {"terrain", "objects"}:
                relative = destination.relative_to(scene_dir).as_posix()
                metadata = metadata_by_file.get(source.name) or metadata_by_file.get(str(source))
                (terrain if category == "terrain" else objects).append(scene_entry(relative, metadata))

        source_path = scene_dir / "source" / "bridge-response.json"
        source_path.parent.mkdir(exist_ok=True)
        source_path.write_text(json.dumps(self._portable_metadata(bridge_metadata), ensure_ascii=False, indent=2), encoding="utf-8")
        self.add_source_file(run_id, source_path)
        scene = {"format": "wow-timecapsule-scene", "version": 1, "name": name.strip(),
                 "map_id": map_id, "source_build": source_build, "terrain": terrain,
                 "objects": objects, "spawn": (spawn or SpawnPoint()).as_dict()}
        scene_path = scene_dir / "scene.json"
        scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        self.add_source_file(run_id, scene_path)
        relative_scene = scene_path.relative_to(self.root).as_posix()
        self.db.execute("UPDATE map_export SET scene_path=? WHERE map_export_id=?", (relative_scene, map_export_id))
        return scene_path

    @staticmethod
    def _unique_name(name: str, used: set[str]) -> str:
        candidate = safe_name(name)
        stem, suffix = Path(candidate).stem, Path(candidate).suffix
        counter = 2
        while candidate.lower() in used:
            candidate = f"{stem}_{counter}{suffix}"; counter += 1
        return candidate

    @classmethod
    def _portable_metadata(cls, value: Any) -> Any:
        """Remove machine-specific absolute paths from bridge operational metadata."""
        if isinstance(value, dict):
            return {key: cls._portable_metadata(item) for key, item in value.items() if key != "output_dir"}
        if isinstance(value, list):
            return [cls._portable_metadata(item) for item in value]
        if isinstance(value, str) and Path(value).is_absolute():
            return Path(value).name
        return value

    def import_capture(self, run_id: int, character: CharacterRef, captured: dict[str, dict], observed: str | None = None) -> int:
        observed = observed or now()
        profile = captured["character_profile"]
        row = self.db.execute("SELECT character_id FROM character WHERE region=? AND realm_slug=? AND character_name=? COLLATE NOCASE", (character.region, character.realm_slug, character.name)).fetchone()
        if row:
            character_id = row[0]
            self.db.execute("UPDATE character SET last_seen_at=?,blizzard_character_id=COALESCE(?,blizzard_character_id),realm_name=COALESCE(NULLIF(?,''),realm_name) WHERE character_id=?", (observed, character.character_id, character.realm_name, character_id))
        else:
            character_id = self.db.execute("INSERT INTO character(blizzard_character_id,region,realm_id,realm_slug,realm_name,character_name,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?)", (character.character_id, character.region, character.realm_id, character.realm_slug, character.realm_name, character.name, observed, observed)).lastrowid
        def named(obj: Any) -> Any:
            return obj.get("name") if isinstance(obj, dict) else obj
        snapshot = self.db.execute("""INSERT INTO character_snapshot(character_id,archive_run_id,observed_at,level,race_id,race_name,class_id,class_name,specialization,faction,guild_name,achievement_points,last_login_if_available,raw_json_path) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            character_id, run_id, observed, profile.get("level"), profile.get("race", {}).get("id"), named(profile.get("race")), profile.get("character_class", {}).get("id"), named(profile.get("character_class")), named(profile.get("active_spec")), named(profile.get("faction")), named(profile.get("guild")), profile.get("achievement_points"), profile.get("last_login_timestamp"), self._raw_path(run_id, "character_profile"),
        )).lastrowid
        self._import_achievements(snapshot, captured.get("achievements", {}), observed)
        self._import_equipment(snapshot, captured.get("equipment", {}), observed)
        self._import_pets(snapshot, captured.get("pets", {}), observed)
        self._import_mounts(snapshot, captured.get("mounts", {}), observed)
        self._import_simple(snapshot, captured.get("professions", {}), "profession", observed)
        self._import_simple(snapshot, captured.get("reputations", {}), "reputation", observed)
        self._import_stats(snapshot, captured.get("statistics", {}), observed)
        self._import_quests(snapshot, captured.get("quests", {}), observed)
        return int(snapshot)

    def _raw_path(self, run_id: int, name: str) -> str | None:
        row = self.db.execute("SELECT relative_path FROM raw_api_file WHERE archive_run_id=? AND relative_path LIKE ?", (run_id, f"%_{safe_name(name)}.json")).fetchone()
        return row[0] if row else None

    def _import_achievements(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("achievements", []):
            detail = item.get("achievement", item)
            aid = detail.get("id")
            if aid is None: continue
            self.db.execute("INSERT OR IGNORE INTO achievement(achievement_id,name,description,points,category) VALUES(?,?,?,?,?)", (aid, detail.get("name"), item.get("description"), item.get("points"), str(item.get("category", ""))))
            completed = item.get("completed_timestamp")
            self.db.execute("INSERT INTO character_achievement VALUES(?,?,?,?,?,?)", (sid, aid, int(bool(completed or item.get("is_completed"))), str(completed) if completed else None, json.dumps(item.get("criteria")) if item.get("criteria") else None, observed))

    def _import_equipment(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("equipped_items", []):
            iid, slot = item.get("item", {}).get("id"), item.get("slot", {}).get("type")
            if iid is None: continue
            self.db.execute("INSERT OR IGNORE INTO equipment(blizzard_item_id,name,slot_type) VALUES(?,?,?)", (iid, item.get("name"), slot))
            eid = self.db.execute("SELECT equipment_id FROM equipment WHERE blizzard_item_id=? AND slot_type IS ?", (iid, slot)).fetchone()[0]
            self.db.execute("INSERT INTO character_equipment VALUES(?,?,?,?)", (sid, eid, observed, json.dumps(item)))

    def _import_pets(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("pets", []):
            guid = item.get("id") or f"species:{item.get('species', {}).get('id')}:{item.get('name', '')}"
            species = item.get("species", {})
            self.db.execute("INSERT OR IGNORE INTO pet(pet_guid,species_id,display_id,creature_id,name,custom_name) VALUES(?,?,?,?,?,?)", (guid, species.get("id"), item.get("display", {}).get("id"), item.get("creature", {}).get("id"), species.get("name") or item.get("name"), item.get("name")))
            pid = self.db.execute("SELECT pet_id FROM pet WHERE pet_guid=?", (guid,)).fetchone()[0]
            self.db.execute("INSERT INTO character_pet(character_snapshot_id,pet_id,level,quality,breed,is_favorite,observed_at) VALUES(?,?,?,?,?,?,?)", (sid, pid, item.get("level"), str(item.get("quality", {}).get("name", "")), str(item.get("breed_id", "")), int(bool(item.get("is_favorite"))), observed))

    def _import_mounts(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("mounts", []):
            mount = item.get("mount", item); mid = mount.get("id")
            if mid is None: continue
            self.db.execute("INSERT OR IGNORE INTO mount VALUES(?,?)", (mid, mount.get("name")))
            self.db.execute("INSERT INTO character_mount VALUES(?,?,?,?)", (sid, mid, int(item.get("is_collected", True)), observed))

    def _import_simple(self, sid: int, data: dict, kind: str, observed: str) -> None:
        keys = ("primaries", "secondaries") if kind == "profession" else ("reputations",)
        for key in keys:
            for item in data.get(key, []):
                obj = item.get(kind, item.get("faction", item)); oid = obj.get("id")
                if oid is None: continue
                self.db.execute(f"INSERT OR IGNORE INTO {kind} VALUES(?,?)", (oid, obj.get("name")))
                if kind == "profession":
                    self.db.execute("INSERT INTO character_profession VALUES(?,?,?,?,?)", (sid, oid, item.get("skill_points"), item.get("max_skill_points"), observed))
                else:
                    self.db.execute("INSERT INTO character_reputation VALUES(?,?,?,?,?)", (sid, oid, str(item.get("standing", {}).get("name", "")), item.get("standing", {}).get("value"), observed))

    def _import_stats(self, sid: int, data: dict, observed: str) -> None:
        for name, value in data.items():
            if isinstance(value, (int, float)):
                self.db.execute("INSERT INTO character_stat VALUES(?,?,?,?)", (sid, name, value, observed))

    def _import_quests(self, sid: int, data: dict, observed: str) -> None:
        for item in data.get("quests", []):
            qid = item.get("id");
            if qid is None: continue
            self.db.execute("INSERT OR IGNORE INTO quest VALUES(?,?)", (qid, item.get("name")))
            self.db.execute("INSERT INTO character_quest VALUES(?,?,?,?,?)", (sid, qid, "completed", None, observed))

    def write_readme(self) -> None:
        chars = self.db.execute("SELECT character_name,realm_name,region FROM character ORDER BY character_name").fetchall()
        run = self.db.execute("SELECT completed_at,wow_client_build,wow_export_version FROM archive_run WHERE status='complete' ORDER BY archive_run_id DESC LIMIT 1").fetchone()
        lines = ["# WoW Time Capsule Archive", "", "This is a local, preservation-oriented archive. It contains original JSON responses and a standard SQLite index.", "", "## Characters", ""]
        lines += [f"- {name} — {realm or 'unknown realm'} ({region.upper()})" for name, realm, region in chars] or ["- None yet"]
        assets = self.db.execute("SELECT format,count(*) FROM asset GROUP BY format ORDER BY format").fetchall()
        lines += ["", "## Latest export", "", f"- Exported: {run[0] if run else 'unknown'}", f"- WoW client build: {(run[1] if run else None) or 'unknown'}", f"- wow.export version: {(run[2] if run else None) or 'not available'}", "- Exporter version: " + __version__, "", "## Preserved asset formats", ""]
        lines += [f"- {fmt.upper()}: {count}" for fmt, count in assets] or ["- No binary assets"]
        lines += ["", "## Opening and formats", "", "Open `wow_archive.sqlite` with any SQLite 3 browser. Raw Blizzard API responses are under `raw/api/` as UTF-8 JSON. Character and pet models use GLB. World areas are under `world/`; each `scene.json` is the stable entry point and preserves terrain, objects, textures, and original exporter metadata. Run `python -m wow_timecapsule.verify .` from this directory to verify integrity.", "", "## Limitations", "", "This archive records what supported APIs exposed at each observation time. It is not a complete historical activity log. 3D export requires a compatible localhost wow.export bridge. World export is intentionally limited to small, manually selected areas; the offline viewer is a later phase.", ""]
        (self.root / "README.md").write_text("\n".join(lines), encoding="utf-8")
