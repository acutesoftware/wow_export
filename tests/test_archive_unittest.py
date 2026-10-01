import tempfile
import unittest
import sqlite3
from pathlib import Path

from wow_timecapsule.api import CharacterRef
from wow_timecapsule.archive import Archive
from wow_timecapsule.html_view import generate_html
from wow_timecapsule.verify import verify


class ArchiveTests(unittest.TestCase):
    def test_new_archive_has_character_information_tables_only(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            tables = {
                row[0] for row in archive.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertNotIn("asset", tables)
            self.assertNotIn("character_asset", tables)
            self.assertNotIn("map", tables)
            self.assertNotIn("map_export", tables)
            self.assertNotIn("map_asset", tables)
            self.assertNotIn("source_file", tables)
            run_columns = {
                row[1] for row in archive.db.execute("PRAGMA table_info(archive_run)")
            }
            self.assertEqual(
                run_columns,
                {
                    "archive_run_id", "started_at", "completed_at", "app_version",
                    "region", "locale", "status", "notes",
                },
            )
            archive.close()

    def test_snapshot_is_preserved_and_verifies(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = Archive(root)
            character = CharacterRef("us", 1, "test-realm", "Test Realm", 42, "Example")
            captured = {
                "character_profile": {"level": 80, "character_class": {"id": 8, "name": "Mage"}},
                "achievements": {"achievements": [{"achievement": {"id": 6, "name": "Level 10"}, "completed_timestamp": 1000}]},
                "equipment": {"equipped_items": [{"item": {"id": 100}, "name": "Hat", "slot": {"type": "HEAD"}}]},
                "pets": {"pets": [{"id": "pet-1", "species": {"id": 39, "name": "Cat"}}]},
            }
            with archive.run(region="us", locale="en_US") as run_id:
                for name, payload in captured.items():
                    archive.save_raw(run_id, name, "/" + name, payload, 200, "2026-09-20T00:00:00Z")
                archive.import_capture(run_id, character, captured, "2026-09-20T00:00:00Z")
            archive.close()
            valid, messages = verify(root)
            self.assertTrue(valid, "\n".join(messages))
            self.assertTrue((root / "README.md").exists())

    def test_repeated_exports_create_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            character = CharacterRef("eu", None, "realm", "Realm", None, "Name")
            for level in (10, 11):
                with archive.run(region="eu", locale="en_GB") as run_id:
                    data = {"character_profile": {"level": level}}
                    archive.save_raw(run_id, "character_profile", "/profile", data["character_profile"], 200)
                    archive.import_capture(run_id, character, data)
            self.assertEqual(archive.db.execute("SELECT count(*) FROM character_snapshot").fetchone()[0], 2)
            archive.close()

    def test_duplicate_api_records_are_deduplicated_within_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            character = CharacterRef("us", 1, "realm-one", "Realm One", 42, "SameName")
            duplicate_quest = {"id": 1234, "name": "A Quest Blizzard Listed Twice"}
            captured = {
                "character_profile": {"level": 80},
                "quests": {
                    "quests": [duplicate_quest, duplicate_quest],
                    "_reference_details": {"1234": {
                        "id": 1234,
                        "title": "A Quest Blizzard Listed Twice",
                        "description": "Complete the important test objective.",
                        "category": {"name": "Testing"},
                    }},
                },
            }
            with archive.run(region="us", locale="en_US") as run_id:
                archive.save_raw(run_id, "character_profile", "/profile", captured["character_profile"], 200)
                snapshot_id = archive.import_capture(run_id, character, captured)

            count = archive.db.execute(
                "SELECT count(*) FROM character_quest WHERE character_snapshot_id=?",
                (snapshot_id,),
            ).fetchone()[0]
            self.assertEqual(count, 1)
            archive.close()

            page = generate_html(folder).read_text(encoding="utf-8")
            self.assertIn("A Quest Blizzard Listed Twice", page)
            self.assertIn("Complete the important test objective.", page)
            self.assertIn('"kind": "quests"', page)

    def test_shared_collections_hunter_pets_outcomes_and_html(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = Archive(root)
            character = CharacterRef(
                "us", 1, "realm", "Realm", 42, "Ranger", 80,
                "Hunter", "profile", 3,
            )
            captured = {
                "character_profile": {
                    "level": 80,
                    "race": {"id": 1, "name": "Human"},
                    "character_class": {"id": 3, "name": "Hunter"},
                },
                "hunter_pets": {"hunter_pets": [{
                    "name": "Bitey", "level": 80, "slot": 1,
                    "creature": {"id": 99}, "creature_display": {"id": 100},
                    "is_active": True,
                }]},
                "pets": {"pets": [{
                    "id": "pet-1", "name": "Pocket Cat",
                    "species": {"id": 39, "name": "Cat"},
                }]},
                "mounts": {"mounts": [{"mount": {"id": 7, "name": "Pony"}}]},
                "_outcomes": {
                    "character_profile": {"status": "captured", "count": 1, "detail": ""},
                    "hunter_pets": {"status": "captured", "count": 1, "detail": ""},
                    "pets": {"status": "captured", "count": 1, "detail": ""},
                    "mounts": {"status": "captured", "count": 1, "detail": ""},
                    "achievements": {"status": "request_failed", "count": None, "detail": "404"},
                },
            }
            with archive.run(region="us", locale="en_US") as run_id:
                for name in ("character_profile", "hunter_pets", "pets", "mounts"):
                    archive.save_raw(run_id, name, "/" + name, captured[name], 200)
                snapshot_id = archive.import_capture(run_id, character, captured)
            character_id = archive.db.execute(
                "SELECT character_id FROM character WHERE character_name='Ranger'"
            ).fetchone()[0]
            archive.add_memory(character_id, "First tame", "Met Bitey in the forest.")
            image = root / "source.png"
            image.write_bytes(b"not-a-real-image-but-preserved")
            saved_image = archive.add_screenshot(image, "At home")
            self.assertNotIn(
                "character_id",
                {row[1] for row in archive.db.execute("PRAGMA table_info(screenshot)")},
            )
            self.assertEqual(
                archive.db.execute("SELECT count(*) FROM character_hunter_pet").fetchone()[0], 1
            )
            self.assertEqual(
                archive.db.execute("SELECT count(*) FROM collection_pet").fetchone()[0], 1
            )
            self.assertEqual(
                archive.db.execute("SELECT count(*) FROM collection_mount").fetchone()[0], 1
            )
            summary = {item["section"]: item for item in archive.capture_summary(snapshot_id)}
            self.assertEqual(summary["achievements"]["status"], "request_failed")
            archive.close()

            page = generate_html(root).read_text(encoding="utf-8")
            self.assertIn("Ranger", page)
            self.assertIn("Bitey", page)
            self.assertIn("Pocket Cat", page)
            self.assertIn("Shared Collections", page)
            self.assertNotIn("src=\"http", page)
            valid, messages = verify(root)
            self.assertTrue(valid, "\n".join(messages))
            saved_image.unlink()
            valid, messages = verify(root)
            self.assertFalse(valid)
            self.assertTrue(any("Missing screenshot link" in line for line in messages))

    def test_screenshot_folder_import_is_recursive_deduplicated_and_dated(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "archive"
            sources = base / "screenshots"
            nested = sources / "older"
            nested.mkdir(parents=True)
            first = sources / "WoWScrnShot_010224_030405.jpg"
            first.write_bytes(b"first-image")
            duplicate = nested / "same-content.jpg"
            duplicate.write_bytes(b"first-image")
            second = nested / "WoWScrnShot_123123_235959.png"
            second.write_bytes(b"second-image")

            archive = Archive(root)
            character = CharacterRef("us", 1, "realm", "Realm", 42, "Photographer")
            with archive.run(region="us", locale="en_US") as run_id:
                archive.import_capture(
                    run_id, character, {"character_profile": {"level": 80}}
                )
            character_id = archive.db.execute(
                "SELECT character_id FROM character WHERE character_name='Photographer'"
            ).fetchone()[0]
            result = archive.import_screenshot_folder(sources)

            self.assertEqual(result["scanned"], 3)
            self.assertEqual(result["imported"], 3)
            self.assertEqual(result["unchanged"], 0)
            rows = archive.db.execute(
                "SELECT captured_at,source_path FROM screenshot ORDER BY captured_at"
            ).fetchall()
            self.assertEqual(len(rows), 3)
            self.assertTrue(any(item[0].startswith("2023-12-31T23:59:59") for item in rows))
            self.assertTrue(any(item[0].startswith("2024-01-02T03:04:05") for item in rows))
            self.assertTrue(all(Path(item[1]).is_absolute() for item in rows))
            self.assertFalse((root / "media" / "screenshots").exists())
            rescanned = archive.rescan_screenshot_folders()
            self.assertEqual(rescanned["imported"], 0)
            self.assertEqual(rescanned["unchanged"], 3)
            duplicate.unlink()
            rescanned = archive.rescan_screenshot_folders()
            self.assertEqual(rescanned["missing"], 1)
            archive.close()

            page = generate_html(root).read_text(encoding="utf-8")
            self.assertIn("Load 60 more", page)
            self.assertIn('loading="lazy"', page)
            self.assertIn("2024", page)
            self.assertIn('"character": "World of Warcraft"', page)
            self.assertIn(first.resolve().as_uri(), page)
            self.assertNotIn("encodeURI(x.image)", page)
            self.assertIn("Open full image in the default viewer", page)
            self.assertIn("width:min(100%,360px)", page)

    def test_character_linked_screenshots_migrate_to_global_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "wow_archive.sqlite"
            db = sqlite3.connect(database)
            db.executescript("""
                CREATE TABLE character (
                    character_id INTEGER PRIMARY KEY, blizzard_character_id INTEGER,
                    region TEXT NOT NULL, realm_id INTEGER, realm_slug TEXT NOT NULL,
                    realm_name TEXT, character_name TEXT NOT NULL,
                    namespace TEXT NOT NULL DEFAULT 'profile', first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(region,realm_slug,character_name,namespace)
                );
                INSERT INTO character VALUES(
                    1,42,'us',1,'realm','Realm','Old Link','profile','x','x'
                );
                CREATE TABLE screenshot (
                    screenshot_id INTEGER PRIMARY KEY,
                    character_id INTEGER NOT NULL REFERENCES character,
                    relative_path TEXT NOT NULL UNIQUE, caption TEXT,
                    added_at TEXT NOT NULL, sha256 TEXT
                );
                INSERT INTO screenshot VALUES(
                    1,1,'media/screenshots/old.jpg','Old screenshot',
                    '2020-01-01T00:00:00Z','digest'
                );
            """)
            db.commit()
            db.close()

            archive = Archive(folder)
            self.assertNotIn(
                "character_id",
                {row[1] for row in archive.db.execute("PRAGMA table_info(screenshot)")},
            )
            archive.close()

    def test_existing_character_table_is_migrated_with_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "wow_archive.sqlite"
            db = sqlite3.connect(database)
            db.executescript("""
                CREATE TABLE character (
                    character_id INTEGER PRIMARY KEY, blizzard_character_id INTEGER,
                    region TEXT NOT NULL, realm_id INTEGER, realm_slug TEXT NOT NULL,
                    realm_name TEXT, character_name TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    UNIQUE(region, realm_slug, character_name)
                );
                INSERT INTO character VALUES(1,42,'us',1,'realm','Realm','Legacy','a','b');
                CREATE TABLE achievement (
                    achievement_id INTEGER PRIMARY KEY, name TEXT, description TEXT,
                    points INTEGER, category TEXT
                );
            """)
            db.close()
            archive = Archive(folder)
            row = archive.db.execute(
                "SELECT character_name,namespace FROM character WHERE character_id=1"
            ).fetchone()
            self.assertEqual(row, ("Legacy", "profile"))
            achievement_columns = {
                row[1] for row in archive.db.execute("PRAGMA table_info(achievement)")
            }
            self.assertIn("requirements", achievement_columns)
            self.assertIn("reference_json", achievement_columns)
            archive.close()

    def test_profession_tiers_achievement_details_and_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = Archive(root)
            character = CharacterRef("us", 1, "realm", "Realm", 42, "Smith")
            captured = {
                "character_profile": {
                    "level": 80, "last_login_timestamp": 1_700_000_000_000,
                },
                "achievements": {
                    "achievements": [{
                        "achievement": {"id": 6, "name": "Level 10"},
                        "completed_timestamp": 1_600_000_000_000,
                    }],
                    "_reference_details": {"6": {
                        "id": 6, "name": "Level 10", "description": "Reach level 10.",
                        "points": 10, "category": {"name": "Character"},
                        "criteria": {"description": "Reach level 10"},
                        "reward_description": "A fine tabard", "is_account_wide": False,
                    }},
                },
                "professions": {"primaries": [{
                    "profession": {"id": 164, "name": "Blacksmithing"},
                    "tiers": [{
                        "tier": {"id": 2822, "name": "Khaz Algar Blacksmithing"},
                        "skill_points": 75, "max_skill_points": 100,
                        "known_recipes": [
                            {"id": 1, "name": "Forged Practice Blade"},
                            {"id": 2, "name": "Tempered Test Shield"},
                        ],
                    }],
                }]},
                "_outcomes": {
                    "character_profile": {"status": "captured", "count": 1},
                    "achievements": {"status": "captured", "count": 1},
                    "achievement_details": {"status": "captured", "count": 1},
                    "professions": {"status": "captured", "count": 1},
                },
            }
            with archive.run(region="us", locale="en_US") as run_id:
                archive.save_raw(
                    run_id, "professions", "/professions", captured["professions"], 200,
                    "2026-10-02T00:00:00Z",
                )
                snapshot_id = archive.import_capture(
                    run_id, character, captured, "2026-10-02T00:00:00Z"
                )
            character_id = archive.db.execute(
                "SELECT character_id FROM character WHERE character_name='Smith'"
            ).fetchone()[0]
            archive.add_memory(character_id, "The old forge", "Made my first sword.")
            image = root / "forge.png"
            image.write_bytes(b"image")
            archive.add_screenshot(image, "At the forge")
            tier = archive.db.execute("""
                SELECT p.name,pt.name,cpt.skill_points,cpt.max_skill_points,cpt.known_recipes
                FROM character_profession_tier cpt
                JOIN profession_tier pt ON pt.profession_tier_id=cpt.profession_tier_id
                JOIN profession p ON p.profession_id=pt.profession_id
                WHERE cpt.character_snapshot_id=?
            """, (snapshot_id,)).fetchone()
            self.assertEqual(
                tier, ("Blacksmithing", "Khaz Algar Blacksmithing", 75, 100, 2)
            )
            achievement = archive.db.execute(
                "SELECT description,requirements,reward_description FROM achievement WHERE achievement_id=6"
            ).fetchone()
            self.assertEqual(
                achievement, ("Reach level 10.", "Reach level 10", "A fine tabard")
            )
            recipes = archive.db.execute(
                "SELECT name FROM recipe ORDER BY name"
            ).fetchall()
            self.assertEqual(
                recipes, [("Forged Practice Blade",), ("Tempered Test Shield",)]
            )
            archive.db.execute("DELETE FROM character_known_recipe")
            archive.db.execute("DELETE FROM recipe")
            archive.db.execute("DELETE FROM character_profession_tier")
            archive.db.commit()
            archive.close()

            archive = Archive(root)
            self.assertEqual(
                archive.db.execute(
                    "SELECT count(*) FROM character_profession_tier"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                archive.db.execute("SELECT count(*) FROM character_known_recipe").fetchone()[0],
                2,
            )
            archive.close()

            page = generate_html(root).read_text(encoding="utf-8")
            self.assertIn("Khaz Algar Blacksmithing", page)
            self.assertIn("Forged Practice Blade", page)
            self.assertIn("How to earn it", page)
            self.assertIn("A fine tabard", page)
            self.assertIn('"kind": "played"', page)
            self.assertIn('"kind": "achievement"', page)
            self.assertIn('"kind": "screenshot"', page)
            self.assertIn('"kind": "memory"', page)

    def test_legacy_character_collections_migrate_to_shared_collections(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(folder)
            character = CharacterRef("us", 1, "realm", "Realm", 42, "Legacy")
            with archive.run(region="us", locale="en_US") as run_id:
                snapshot_id = archive.import_capture(
                    run_id, character, {"character_profile": {"level": 70}},
                    "2025-01-01T00:00:00Z",
                )
            archive.db.executescript("""
                CREATE TABLE character_pet (
                    character_snapshot_id INTEGER, pet_id INTEGER, level INTEGER,
                    quality TEXT, breed TEXT, is_favorite INTEGER, observed_at TEXT,
                    PRIMARY KEY(character_snapshot_id,pet_id)
                );
                CREATE TABLE character_mount (
                    character_snapshot_id INTEGER, mount_id INTEGER,
                    is_collected INTEGER, observed_at TEXT,
                    PRIMARY KEY(character_snapshot_id,mount_id)
                );
                INSERT INTO pet(pet_id,pet_guid,name) VALUES(1,'legacy-pet','Legacy Pet');
                INSERT INTO mount(mount_id,name) VALUES(2,'Legacy Mount');
            """)
            archive.db.execute(
                "INSERT INTO character_pet VALUES(?,?,?,?,?,?,?)",
                (snapshot_id, 1, 25, "Rare", "", 1, "2025-01-01T00:00:00Z"),
            )
            archive.db.execute(
                "INSERT INTO character_mount VALUES(?,?,?,?)",
                (snapshot_id, 2, 1, "2025-01-01T00:00:00Z"),
            )
            archive.db.execute("DELETE FROM collection_snapshot")
            archive.db.commit()
            archive.close()

            migrated = Archive(folder)
            self.assertEqual(
                migrated.db.execute("SELECT count(*) FROM collection_pet").fetchone()[0], 1
            )
            self.assertEqual(
                migrated.db.execute("SELECT count(*) FROM collection_mount").fetchone()[0], 1
            )
            details = {
                row[0]: row[1] for row in migrated.db.execute(
                    "SELECT kind,detail FROM collection_snapshot"
                )
            }
            self.assertIn("older archive schema", details["pets"])
            self.assertIn("older archive schema", details["mounts"])
            migrated.close()


if __name__ == "__main__":
    unittest.main()
