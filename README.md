# WoW Time Capsule

A local-first World of Warcraft archival exporter. Phase 1 provides API snapshots and Phase 2 adds versioned `wow.export` bridge automation, character GLB export, default companion-pet GLB export, and checksummed asset preservation.

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

The 3D option requires a compatible loopback bridge implementing [the v1 bridge protocol](docs/BRIDGE_PROTOCOL.md). The application never automates the wow.export GUI. World extraction and the Go/Three.js viewer remain later phases.

See the [user guide](docs/user_guide.md) for setup, exporting, verification, and an explanation of the mock bridge integration test.

