import json
import sqlite3
import struct

from wow_timecapsule.archive import Archive
from wow_timecapsule.verify import verify
from wow_timecapsule.world import SpawnPoint


def test_map_export_generates_portable_scene(tmp_path):
    stage = tmp_path / "stage"; stage.mkdir()
    terrain = stage / "tile.obj"; terrain.write_text("# terrain\n", encoding="utf-8")
    building = stage / "inn.glb"; building.write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
    texture = stage / "tile.png"; texture.write_bytes(b"png")
    metadata = {"output_dir": str(stage), "entries": [
        {"path": "tile.obj", "kind": "terrain", "tile": {"x": 32, "y": 32}},
        {"path": "inn.glb", "kind": "wmo", "position": [1, 2, 3], "source_id": "42"},
    ]}
    root = tmp_path / "archive"; archive = Archive(root)
    with archive.run(region="us", locale="en_US", build="test") as run_id:
        scene_path = archive.preserve_map_export(run_id, 0, "Trade District", "test",
                                                 (terrain, building, texture), metadata,
                                                 SpawnPoint(1, 2, 3, 4))
    archive.close()
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    assert scene["terrain"][0]["path"] == "terrain/tile.obj"
    assert scene["objects"][0]["path"] == "objects/inn.glb"
    assert scene["objects"][0]["position"] == [1, 2, 3]
    assert scene["spawn"]["heading"] == 4
    assert "output_dir" not in (scene_path.parent / "source/bridge-response.json").read_text()
    valid, messages = verify(root)
    assert valid, "\n".join(messages)
    db = sqlite3.connect(root / "wow_archive.sqlite")
    assert db.execute("SELECT count(*) FROM map_export").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM map_asset").fetchone()[0] == 3
