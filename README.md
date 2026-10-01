# WoW Time Capsule

A local-first tool for preserving World of Warcraft character information from
Blizzard's supported APIs. It creates a readable, offline HTML album alongside
the original API responses and a queryable SQLite archive.

WoW Time Capsule exports information only. It does not extract game assets,
models, maps, textures, or other game-client files.

Requires Windows and Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m wow_timecapsule
```

Character export requires a Battle.net developer client and browser
authorization. See the [user guide](docs/user_guide.md) for the exact portal
settings, the View/Export workflow, collection behavior, and troubleshooting.

Opening an existing archive, adding personal screenshots or notes, and
rebuilding its `index.html` do not require a Battle.net connection.

Verify an archive with:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```
