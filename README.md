# WoW Time Capsule

A local-first World of Warcraft archival exporter. Phase 1 includes a PySide6 GUI, browser OAuth, character discovery/manual entry, immutable snapshots, raw JSON preservation, SQLite indexing, archive README generation, a `wow.export` capability probe, and offline verification.

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

This implements Phase 1 of [the specification](docs/spec_wow_export_v01.md). Automated 3D export, world extraction, and the Go/Three.js viewer belong to later phases.

