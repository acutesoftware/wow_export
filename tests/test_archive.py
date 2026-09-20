import json
import sqlite3

from wow_timecapsule.api import CharacterRef
from wow_timecapsule.archive import Archive
from wow_timecapsule.verify import verify


def test_archive_snapshot_and_verify(tmp_path):
    archive = Archive(tmp_path)
    character = CharacterRef("us", 1, "test-realm", "Test Realm", 42, "Example", 80, "Mage")
    captured = {
        "character_profile": {"id": 42, "level": 80, "race": {"id": 1, "name": "Human"}, "character_class": {"id": 8, "name": "Mage"}, "faction": {"name": "Alliance"}, "achievement_points": 1234},
        "achievements": {"achievements": [{"achievement": {"id": 6, "name": "Level 10"}, "completed_timestamp": 1000}]},
        "equipment": {"equipped_items": [{"item": {"id": 100}, "name": "Test Hat", "slot": {"type": "HEAD"}}]},
        "pets": {"pets": [{"id": "BattlePet-1", "species": {"id": 39, "name": "Mechanical Squirrel"}, "level": 25, "is_favorite": True}]},
    }
    with archive.run(region="us", locale="en_US") as run_id:
        for name, payload in captured.items(): archive.save_raw(run_id, name, "/test/" + name, payload, 200, "2026-09-20T00:00:00Z")
        archive.import_capture(run_id, character, captured, "2026-09-20T00:00:00Z")
    archive.close()
    valid, lines = verify(tmp_path)
    assert valid, "\n".join(lines)
    db = sqlite3.connect(tmp_path / "wow_archive.sqlite")
    assert db.execute("select count(*) from character_snapshot").fetchone()[0] == 1
    assert db.execute("select completed_at from character_achievement").fetchone()[0] == "1000"
    assert json.loads((tmp_path / "raw/api/2026-09-20/run_1_character_profile.json").read_text())["id"] == 42
    assert "Example" in (tmp_path / "README.md").read_text()


def test_snapshots_do_not_overwrite(tmp_path):
    archive = Archive(tmp_path); char = CharacterRef("eu", None, "realm", "Realm", None, "Name")
    for level in (10, 11):
        with archive.run(region="eu", locale="en_GB") as run_id:
            payload = {"level": level}; archive.save_raw(run_id, "character_profile", "/profile", payload, 200); archive.import_capture(run_id, char, {"character_profile": payload})
    assert archive.db.execute("select count(*) from character_snapshot").fetchone()[0] == 2
    assert archive.db.execute("select count(*) from raw_api_file").fetchone()[0] == 2
    archive.close()
