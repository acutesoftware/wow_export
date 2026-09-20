import tempfile
import unittest
from pathlib import Path

from wow_timecapsule.api import CharacterRef
from wow_timecapsule.archive import Archive
from wow_timecapsule.verify import verify


class ArchiveTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
