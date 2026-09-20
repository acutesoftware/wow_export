import json
import struct
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from wow_timecapsule.adapters.wow_export_v2 import BridgeError, WowExportAdapter
from wow_timecapsule.api import CharacterRef
from wow_timecapsule.archive import Archive
from wow_timecapsule.model_spec import character_export_spec
from wow_timecapsule.verify import verify


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send({"interface": "wow-timecapsule-bridge/v1", "wow_export_version": "test", "formats": ["glb"]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0)); request = json.loads(self.rfile.read(length))
        if self.path == "/v1/installations/open": self._send({"status": "ready"}); return
        output = Path(request["output_dir"]); output.mkdir(parents=True, exist_ok=True)
        name = "pet.glb" if self.path.endswith("creature") else "character.glb"
        (output / name).write_bytes(struct.pack("<4sII", b"glTF", 2, 12))
        self._send({"status": "complete", "files": [name]})

    def _send(self, value):
        body = json.dumps(value).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *args): pass


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close()

    def adapter(self): return WowExportAdapter("missing.exe", f"http://127.0.0.1:{self.server.server_port}")

    def test_bridge_and_asset_ingestion(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as stage:
            root = Path(folder); archive = Archive(root); adapter = self.adapter()
            self.assertTrue(adapter.probe().automation_available)
            char = CharacterRef("us", 1, "realm", "Realm", 2, "Name")
            captured = {"character_profile": {"race": {"id": 1}, "character_class": {"id": 8}}, "equipment": {"equipped_items": []}}
            with archive.run(region="us", locale="en_US") as run_id:
                archive.save_raw(run_id, "character_profile", "/profile", captured["character_profile"], 200)
                sid = archive.import_capture(run_id, char, captured)
                spec = character_export_spec(char, captured); result = adapter.export_character(spec, Path(stage))
                archive.preserve_character_export(run_id, sid, char, "2026-09-21T00:00:00Z", spec, result.files, result.metadata)
            archive.close(); valid, messages = verify(root)
            self.assertTrue(valid, "\n".join(messages)); self.assertTrue(next(root.glob("characters/**/character.glb")))

    def test_non_loopback_bridge_is_rejected(self):
        with self.assertRaises(ValueError): WowExportAdapter("x", "http://localhost:17890")

