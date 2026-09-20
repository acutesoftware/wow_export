
# WoW Time Capsule

## Purpose

Create a local-first archival tool for World of Warcraft characters and selected parts of the WoW world.

The tool should preserve:

* character identity and current state
* character appearance and equipped gear
* achievements
* pets
* mounts
* professions
* reputations
* currencies
* statistics available through supported APIs
* quest/completion information where available
* raw API responses
* selected game models and textures
* selected WoW world locations
* enough metadata to understand the archive without the application
* repeated snapshots so changes can be tracked over time

The long-term goal is to be able to open the archive many years from now and:

1. inspect the character and historical data
2. view the character model
3. view pets
4. walk around selected exported WoW locations
5. optionally have a selected pet follow the character
6. interact with the pet, including a simple "pat pet" action

This is an archival viewer, not a WoW emulator or private server.

---

# Architecture

Use three separate components.

```text
wow-timecapsule/
    exporter/
        Python GUI and archival logic

    viewer/
        Go local web server
        browser-based 3D viewer

    addon/
        optional WoW addon for data unavailable from external APIs

    archive/
        generated user data - never committed to public Git
```

The exporter and viewer must communicate only through documented archive files and SQLite.

Do not tightly couple the viewer to the Python application.

---

# Technology

## Exporter

Use:

* Python 3.12
* PySide6 GUI
* sqlite3
* requests/httpx for HTTP
* standard Python libraries where practical

Avoid unnecessary frameworks.

Code should be straightforward and readable.

Prefer functions and small modules over elaborate class hierarchies.

## Viewer

Use:

* Go
* standard net/http server or similarly lightweight router
* SQLite read-only access
* static HTML/JavaScript frontend
* Three.js for 3D rendering
* vendored/local JavaScript dependencies

Do not require Node.js at runtime.

The viewer must work with no internet connection once an archive has been created.

---

# Important Security Rule

NEVER request, capture, store or transmit the user's Blizzard email or password.

Battle.net authentication must use OAuth in the user's normal web browser.

The flow should be conceptually:

```text
WoW Time Capsule
      |
      +--> Open Battle.net authorization page in browser
      |
User logs into Blizzard directly
      |
      +--> Blizzard redirects to localhost callback
      |
WoW Time Capsule receives temporary authorization result
```

Store refresh/access tokens only if required.

If tokens are stored, store them separately from the archival data and make it obvious that they are temporary operational credentials, not preservation data.

The archive itself must remain usable after all OAuth credentials expire.

---

# User Workflow

Main window should initially be extremely simple.

```text
WoW Time Capsule

WoW Installation:
[C:\Program Files (x86)\World of Warcraft] [Browse]

wow.export:
[C:\tools\wow.export\wow.export.exe]       [Browse]

Archive:
[D:\GameArchives\WorldOfWarcraft]          [Browse]


Battle.net
[ Connect Battle.net ]

Status: Connected / Not Connected


Characters

Realm        Character       Level    Class
------------------------------------------------
Aman'Thul    ExampleName     80       Mage
...

[ Export Selected Character ]

[ World Locations ]

[ Open Archive ]

[ Launch Viewer ]
```

Remember folder settings locally.

Do not store machine-specific paths inside archival records except in a technical run log.

---

# WoW Installation

The user selects the root WoW installation folder.

Detect available products where possible, for example:

```text
_retail_
_classic_
_classic_era_
```

Record:

* detected product
* client version/build
* locale
* archive/export date
* source installation path in run log only

Do not copy the entire WoW installation by default.

Allow a future optional "Preserve Client" feature but keep this outside Phase 1.

---

# wow.export Integration

Treat wow.export as an external dependency behind an adapter.

Create:

```text
exporter/adapters/wow_export.py
```

Expose a small internal interface such as:

```python
probe()
get_version()
open_installation(path)
export_character(character_spec, output_dir)
export_creature(display_id, output_dir)
export_map(map_id, tiles, output_dir)
```

The rest of the application must not know how wow.export is automated.

## Important

Do NOT automate the wow.export GUI using mouse clicks, screen coordinates or keyboard macros.

Upstream wow.export does not currently expose a documented stable command-line automation interface.

Therefore implement wow.export integration in stages.

### Stage A — capability probe

Detect:

* wow.export executable exists
* version
* whether an automation/RPC endpoint is available
* whether expected export formats are supported

Write results to the diagnostic log.

### Stage B — bridge mode

Implement a localhost-only wow.export bridge if required.

Preferred options in order:

1. supported upstream API if one becomes available
2. very small version-pinned bridge/patch around upstream wow.export
3. compatible RPC-enabled wow.export fork through the adapter

Never spread fork-specific calls throughout the application.

The bridge must listen only on:

```text
127.0.0.1
```

and must not expose an external network service.

Version-pin the bridge interface.

---

# wow.export Output Formats

For preservation, prefer:

## Character

Primary:

```text
character.glb
```

GLB is preferred because the geometry, skeleton and textures can be packaged into one file.

Also preserve:

```text
character.json
character.png
```

if available.

## Individual models

Prefer:

```text
.glb
.gltf
.png
```

Use OBJ only when GLB/glTF is unavailable.

## World terrain

Preserve wow.export's map export including:

```text
OBJ
PNG textures
placement CSV/JSON
heightmap where useful
wow.export metadata JSON
```

Do not discard the metadata generated by wow.export.

## Raw data

Where wow.export produces CSV, SQL, JSON or metadata files, retain the original output.

Conversion should add files, not replace originals.

---

# Battle.net Character Discovery

After Battle.net OAuth succeeds, retrieve characters available through supported account/profile APIs.

Show them in the GUI.

Store identifiers rather than relying only on names.

Where possible record:

```text
region
realm_id
realm_slug
realm_name
character_id
character_name
race
class
level
faction
gender/body type where provided
```

Also allow manual character entry:

```text
Region
Realm
Character Name
```

This provides a fallback for public profiles or API changes.

---

# Snapshot Philosophy

Do not attempt to pretend that the API gives us a complete historical record.

The exporter records:

```text
WHAT WE CAN KNOW NOW
+
ANY HISTORICAL DATES ALREADY PRESENT
+
FUTURE SNAPSHOTS
```

Every export creates a snapshot.

Example:

```text
2026-09-20
2027-01-04
2028-07-17
```

This means WoW Time Capsule gradually builds its own history.

Never overwrite previous snapshots.

---

# Historical Information

Retain any historical dates supplied by Blizzard, especially:

* achievement completion timestamps
* progression dates
* other dated milestones returned by APIs

Do not manufacture dates when only current state is known.

Use:

```text
observed_at
```

to distinguish:

```text
earned_at      = date supplied by source
observed_at    = when our exporter saw it
```

---

# Raw API Preservation

For every API request, save the unmodified JSON response as well as importing useful fields into SQLite.

Example:

```text
archive/
    raw/
        api/
            2026-09-20/
                account.json
                character_profile.json
                achievements.json
                equipment.json
                pets.json
                mounts.json
                reputations.json
                professions.json
                currencies.json
```

This is important.

Future versions may understand fields that the current exporter ignores.

SQLite is an index and analysis layer.

The raw JSON is the preservation source.

---

# SQLite Database

Create:

```text
archive/wow_archive.sqlite
```

Use normal SQLite with foreign keys enabled.

Do not use proprietary database extensions.

Initial tables:

```text
archive_run

account

character
character_snapshot

equipment
character_equipment

achievement
character_achievement

pet
character_pet

mount
character_mount

profession
character_profession

reputation
character_reputation

currency
character_currency

character_stat

quest
character_quest

asset

character_asset

map
map_export
map_asset

source_file

raw_api_file
```

---

# archive_run

One record per archival run.

Fields:

```text
archive_run_id
started_at
completed_at
app_version
wow_export_version
wow_client_build
wow_product
region
locale
status
notes
```

---

# character

Stable character identity.

Fields:

```text
character_id
blizzard_character_id
region
realm_id
realm_slug
realm_name
character_name
first_seen_at
last_seen_at
```

---

# character_snapshot

Fields:

```text
character_snapshot_id
character_id
archive_run_id
observed_at

level
race_id
race_name
class_id
class_name
specialization
faction

guild_name

achievement_points
money

last_login_if_available

raw_json_path
```

Do not make fields mandatory merely because they normally exist.

APIs change.

---

# Achievements

Preserve:

```text
achievement_id
name
description
points
category
is_completed
completed_at
criteria
observed_at
```

Achievement completion dates are especially valuable for reconstructing old character history.

---

# Pets

Pets are an important preservation feature.

Preserve as much identity as available:

```text
pet_guid
species_id
display_id
creature_id
name
custom_name
level
quality
breed
is_favorite
observed_at
```

The distinction between:

```text
species_id
display_id
```

is important.

The display/model identity is required to reproduce the particular visual version of the pet.

Where possible export the matching model and textures.

Store:

```text
assets/pets/<pet-id>/
```

Example:

```text
assets/
    pets/
        12345/
            pet.json
            pet.glb
            preview.png
            source.json
```

---

# Special Pet Preservation Requirement

The application must support marking a pet as:

```text
preserve_for_viewer = true
```

The first such pet should become the viewer's default companion.

The viewer must ultimately support:

```text
Follow
Stay
Pat
```

This is a real acceptance requirement, not an Easter egg.

---

# Character Asset Export

Once a character is selected:

1. Retrieve character appearance/equipment information.
2. Convert that information to the character description required by wow.export.
3. Ask the wow.export adapter to generate a character export.
4. Prefer GLB.
5. Copy result into the archive.
6. Record checksums.
7. Record all source identifiers used to generate the model.

Output:

```text
archive/
    characters/
        <region>_<realm>_<character>/
            character.json

            snapshots/
                2026-09-20T232000/
                    profile.json
                    equipment.json
                    character.glb
                    preview.png
```

Do not overwrite old models.

Character appearance changes over time.

---

# Asset Table

Every preserved binary asset should have a database record.

Fields:

```text
asset_id
asset_type
relative_path
format
source
source_id
sha256
file_size
created_at
archive_run_id
```

All stored paths must be relative to the archive root.

No permanent absolute Windows paths.

---

# Optional WoW Addon

Some interesting information is not reliably available through external APIs.

Create a later optional addon:

```text
WoWTimeCapsule
```

The addon should collect only data exposed through Blizzard's normal addon API.

Potential fields:

```text
played time
current location
map id
coordinates
current companion pet
bags/inventory where permitted
known toys
professions
currencies
character settings
selected personal milestones
```

Data should be written to normal WoW SavedVariables.

The Python exporter should be able to:

1. locate the SavedVariables file
2. preserve it unchanged
3. parse supported fields
4. import the useful information into SQLite

Do not require the addon for basic operation.

---

# Local WTF Preservation

Offer:

```text
[ Preserve Character Local Files ]
```

If enabled, copy relevant files from:

```text
WTF/
```

into:

```text
archive/raw/wtf/
```

Do not modify them.

These files may contain useful addon history that later tools can understand.

---

# World Location Export

Add a separate screen:

```text
World Locations

Map / Zone:
[ Stormwind ]

Tile/Area:
[ selection ]

Name:
[ Stormwind - Trade District ]

[ Export Area ]
```

Initially the user may choose areas manually.

Do NOT attempt to export all of Azeroth.

A small collection of personally meaningful locations is the goal.

Examples:

```text
Stormwind
Ironforge
old home city
favourite inn
guild location
important raid entrance
```

---

# World Export Structure

Example:

```text
world/
    stormwind_trade_district/
        scene.json
        terrain/
        objects/
        textures/
        source/
        preview.png
```

`scene.json` is our own stable description.

Example concept:

```json
{
  "format": "wow-timecapsule-scene",
  "version": 1,
  "name": "Stormwind - Trade District",
  "map_id": 0,
  "source_build": "....",
  "terrain": [],
  "objects": [],
  "spawn": {
    "x": 0,
    "y": 0,
    "z": 0,
    "heading": 0
  }
}
```

Our viewer should depend on `scene.json`, not directly on wow.export.

This gives us control over future migrations.

---

# Viewer

Create a separate Go executable:

```text
wow-viewer.exe
```

Running it should:

1. locate the archive
2. open SQLite read-only
3. start a localhost HTTP server
4. open the default browser

Example:

```text
http://127.0.0.1:9876
```

---

# Viewer Home Page

Show:

```text
WoW Time Capsule

Characters
----------

ExampleMage
Level 80 Mage
Aman'Thul

[ View Character ]
[ Timeline ]


Places
------

Stormwind - Trade District
Ironforge

[ Visit ]
```

---

# 3D Browser Viewer

Use Three.js.

Support:

```text
GLB/glTF character models
OBJ world geometry initially
PNG textures
```

First iteration requires:

```text
WASD movement
mouse look
pointer lock
walk
run
gravity
basic collision
spawn position
character loading
pet loading
```

No combat.

No quests.

No WoW UI recreation.

This is a memory/archive viewer.

---

# Character Modes

Provide:

```text
First person
Third person
Free camera
```

Third-person can be basic initially.

---

# Pet Behaviour

When a preserved pet exists:

```text
spawn near player
follow player
idle when player stops
teleport near player if excessively far away
```

Interaction:

```text
[E] Pat <pet name>
```

On activation:

```text
player stops
pet stops
pet turns toward player
play suitable existing pet animation if available
play suitable player interaction animation if available
return to idle
resume follow mode
```

Do not require an authentic Blizzard "petting" animation.

Approximation using preserved animations is acceptable.

This feature must work even if the animation is only:

```text
pet turns
pet sits
short pause
```

Functional requirement:

> The user can walk up to their preserved pet and pat it.

---

# Archive Independence

Once export is complete, the archive viewer must NOT require:

```text
Battle.net
Blizzard servers
Battle.net OAuth
wow.export
the WoW client
Python
```

Only the archive plus the Go viewer should be needed.

This is one of the most important design goals.

---

# Offline Test

Add:

```text
python -m wow_timecapsule.verify <archive>
```

Verification should:

* open SQLite
* check expected files
* verify SHA-256 hashes
* verify GLB files can be parsed
* verify scene references resolve
* report missing files
* report absolute paths accidentally stored
* report external URLs required for rendering

Expected final result:

```text
Archive verification

Database ........ OK
Characters ...... 3
Pets ............ 47
Character models  3
World scenes ..... 5
Assets .......... 8,412
Checksums ........ OK
External deps .... NONE

Archive is self-contained.
```

---

# Diagnostics

Maintain:

```text
archive/logs/
```

Each run should have a readable log.

Do not put OAuth tokens, passwords or secrets in logs.

---

# README Generation

Every archive should automatically get:

```text
README.md
```

Explain:

* what the archive contains
* character names/realms
* WoW client build
* export date
* wow.export version
* viewer version
* formats used
* how to open the archive
* limitations

This README must remain useful even if all custom software is lost.

---

# Legal / Repository Separation

The public source repository must contain:

```text
Python source
Go source
viewer code
addon source
schema
documentation
sample dummy assets
```

It must NOT contain Blizzard game assets.

Generated archive directories should be gitignored.

The user owns and manages their local archive separately.

---

# Phase 1

Build only:

```text
Python GUI
configuration
WoW folder detection
Battle.net OAuth
character discovery
character selection
profile API capture
raw JSON preservation
SQLite import
archive runs
README
verification command
wow.export capability probe
```

Do not build the 3D viewer yet.

At the end of Phase 1 we must be able to select a WoW character and create a useful archival dataset even if 3D asset automation is incomplete.

---

# Phase 2

Implement:

```text
wow.export adapter
automated character GLB export
equipment/appearance model capture
pet model export
asset checksums
```

Use a version-pinned bridge if upstream wow.export cannot be controlled programmatically.

Do not use GUI automation.

---

# Phase 3

Implement selected world exports:

```text
map selection
ADT/map export
terrain
WMO/M2 placed objects
textures
scene.json generation
spawn points
```

Start with ONE deliberately small test area.

Do not optimize for whole continents yet.

---

# Phase 4

Implement Go/browser viewer:

```text
Go server
archive browser
Three.js
scene loading
first-person movement
third-person character
pet following
pat pet
```

---

# First Technical Spike

Before implementing the full GUI, build a small proof-of-concept.

Test against one installed WoW client and one character.

The spike should answer:

```text
1. Can we authenticate using Battle.net OAuth?
2. Can we retrieve the account's character list?
3. Can we retrieve useful profile/achievement/pet data?
4. Can we produce raw JSON + SQLite?
5. Can the selected character appearance/equipment be represented
   in a form wow.export can consume?
6. Can wow.export be driven programmatically without GUI automation?
7. Can we export the selected character to GLB?
8. Can Three.js load that GLB unchanged?
```

Write the answers to:

```text
docs/FEASIBILITY.md
```

If item 6 fails against upstream wow.export, do not abandon the project.

Implement the versioned local bridge described above.

---

# First Acceptance Test

A successful initial end-to-end test is:

```text
Select WoW installation

Connect Battle.net

Characters appear

Select one character

Click Export

archive/wow_archive.sqlite created

character profile stored

achievements stored

pets stored

equipment stored

raw API JSON stored

character GLB generated

one selected pet GLB generated

README generated

archive verifies successfully
```

Then manually open the GLB in a generic glTF viewer.

If a generic glTF viewer can display the archived character without WoW or wow.export running, the core preservation goal has been achieved.

---

# Non-Goals

Do not implement:

```text
private WoW server
combat
NPC AI
quests
auction house
multiplayer
server emulation
full Azeroth export
Blizzard credential storage
screen scraping
GUI mouse automation
```

Keep this a preservation tool.

---

# Design Principle

The archive is the product.

The Python exporter, wow.export and the Go viewer are replaceable tools.

The preserved data should remain understandable and usable without them.

A couple of bits in that spec are deliberately conservative. Most importantly, **“history” cannot mean “recover everything your character did for the last 17 years.”** Blizzard's APIs expose useful current/profile data and some genuinely historical information such as achievement completion dates, but not a complete event log. From the first run onward, though, every snapshot becomes history, and an addon can capture extra personal state that the remote API never exposes. ([Blizzard Forums][3])

Also, the `wow.export` side is the only piece I'd call a genuine engineering spike rather than routine application work. Its configuration already contains explicit character export settings, GLTF/GLB support, OBJ map export, metadata export and local-install support, so all the machinery exists; what is missing is a nice stable external automation surface. ([GitHub][4]) A third-party project has already added an RPC server to a fork and drives it programmatically, which is pretty strong evidence that adding our own narrow adapter/bridge is realistic. ([GitHub][5])

architectural result:

```text
Blizzard today          Your archive                 2046

Battle.net ─┐
WoW client ─┼─ exporter → JSON + SQLite + GLB ──────→ still readable
wow.export ─┘                 +
                          world scenes
                               │
                               ↓
                        wow-viewer.exe
                               │
                          walk around
                               │
                               ↓
                           pat cat
```

**we aren't trying to preserve the service; we're extracting the parts of the experience that were yours while the service still exists.**

[1]: https://github.com/Kruithne/wow.export?utm_source=chatgpt.com "GitHub - Kruithne/wow.export: 📦 wow.export is the number one export toolkit for World of Warcraft. · GitHub"
[2]: https://github.com/api-evangelist/battle-net/blob/main/apis.yml?utm_source=chatgpt.com "battle-net/apis.yml at main · api-evangelist/battle-net · GitHub"
[3]: https://us.forums.blizzard.com/en/blizzard/t/world-of-warcraft-api-update-visions-of-nzoth/3461?utm_source=chatgpt.com "World of Warcraft API Update - Visions of N'zoth - API Discussion - Blizzard Forums"
[4]: https://github.com/Kruithne/wow.export/blob/main/src/default_config.jsonc?utm_source=chatgpt.com "wow.export/src/default_config.jsonc at main · Kruithne/wow.export · GitHub"
[5]: https://github.com/pqhuy98/wow-converter?utm_source=chatgpt.com "GitHub - pqhuy98/wow-converter · GitHub"
