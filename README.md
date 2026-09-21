# WoW Time Capsule

A local-first World of Warcraft archival exporter. It provides API snapshots, character and pet GLB export, plus bounded ADT world-area exports with terrain, placed objects, textures, checksums, and stable `scene.json` manifests.

Requires Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m wow_timecapsule
```

Create a Battle.net developer OAuth client. Authentication occurs in Blizzard's site and the callback binds only to `127.0.0.1`; this application never handles a Blizzard password. OAuth client configuration is saved outside archives and access tokens remain in memory.

Verify an archive with:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```

3D options require a compatible loopback bridge implementing [the v1 bridge protocol](docs/BRIDGE_PROTOCOL.md). The application never automates the wow.export GUI. Use **Export World Area** for a deliberately small manual tile selection; the Go/Three.js viewer remains a later phase.

See the [user guide](docs/user_guide.md) for setup, exporting, verification, and an explanation of the mock bridge integration test.

