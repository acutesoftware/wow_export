# WoW Time Capsule user guide

WoW Time Capsule preserves World of Warcraft character data and, when extra
tools are available, selected 3D assets. You do not need to configure every
integration to use the application.

## What can I do, and what do I need?

Start with the row that matches what you want to preserve.

| What the app can do | Battle.net developer client ID and secret | Battle.net browser sign-in | Local WoW installation | Bridge-enabled `wow.export` | Archive folder |
|---|:---:|:---:|:---:|:---:|:---:|
| Open an existing archive folder | No | No | No | No | Existing |
| Verify an existing archive | No | No | No | No | Existing |
| Save a character's available API data | Yes | Yes | No | No | Yes |
| Save a character and companion pet as GLB models | Yes | Yes | Yes | Yes | Yes |
| Export a small world area (up to 16 ADT tiles) | No | No | Yes | Yes | Yes |

In short:

```text
Existing archive only
    -> no Blizzard credentials and no wow.export

Character data snapshot
    -> Battle.net developer client + browser sign-in

Character data + 3D character/pet
    -> Battle.net developer client + browser sign-in
       + local WoW files + bridge-enabled wow.export

Small world-area export
    -> local WoW files + bridge-enabled wow.export
       (no Battle.net sign-in)
```

The Battle.net developer credentials are sometimes called an API key, client
key, or OAuth client. In this application they mean the **client ID and client
secret** for an application you create in the Battle.net developer portal.
They are not your Blizzard username and password.

Adding a character manually only skips automatic character discovery. The app
still needs a Battle.net developer client and browser sign-in to download that
character's API data.

## Important 3D-export limitation

Character, pet, and world 3D export are **not available with the normal public
release of `wow.export` alone**. This repository also does not include a
bridge-enabled build or instructions for obtaining one. Until a compatible
build exists and is running, use API-only character exports and archive
verification.

### What is `wow.export.exe`?

[`wow.export`](https://github.com/Kruithne/wow.export) is a separate third-party
Windows application. It reads assets from a local World of Warcraft installation
and can export models and maps to formats such as GLB or OBJ. WoW Time Capsule
does not contain `wow.export`, and the `wow.export.exe` path in the window does
not refer to WoW Time Capsule itself.

The public `wow.export` application is normally controlled through its own user
interface. WoW Time Capsule does not click or type in that interface. It expects
to send export requests to a small local HTTP service instead.

### What does “bridge-enabled build” mean?

A bridge-enabled build is a **modified build or fork of `wow.export`** containing
that local HTTP service. The service is the “bridge” between the two programs:

```text
WoW Time Capsule  ->  local bridge on 127.0.0.1:17890
                  ->  modified wow.export
                  ->  local WoW game files
                  ->  exported GLB/OBJ files
```

The bridge must implement the interface named
`wow-timecapsule-bridge/v1`. The normal upstream `wow.export.exe` does not
currently implement it. Merely browsing to a stock `wow.export.exe` therefore
does not enable automated 3D export.

The executable path currently serves two purposes:

- recording/probing which `wow.export` build is being used;
- identifying the companion program expected to provide the bridge.

The bridge itself must already be running at `http://127.0.0.1:17890`. WoW Time
Capsule does not start it automatically. `127.0.0.1` means it is reachable only
from your computer; do not expose the bridge to a LAN or the internet.

The technical request and response format is documented in
[BRIDGE_PROTOCOL.md](BRIDGE_PROTOCOL.md). That document is for someone building
or maintaining the modified `wow.export`, not a normal setup step for users.

## Install and start WoW Time Capsule

Requirements for the basic application are Windows and Python 3.12.

Open PowerShell in the repository directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m wow_timecapsule
```

## Choose paths

The top of the main window has three paths. Only fill in the paths needed for
the operation you chose in the table above.

### WoW Installation

Needed only for 3D character, pet, or world exports. Select the parent World of
Warcraft directory, normally:

```text
C:\Program Files (x86)\World of Warcraft
```

The application looks beneath it for products such as `_retail_`, `_classic_`,
and `_classic_era_`. Do not select one of those product folders directly.

### wow.export

Needed only for 3D exports. Select the `wow.export.exe` belonging to the
compatible bridge-enabled build described above. A stock build is not enough.

### Archive

Needed whenever creating an export. Choose a separate directory, for example:

```text
D:\GameArchives\WorldOfWarcraft
```

Do not use the source-code repository as the archive directory. Archives can
contain personal character information and extracted game assets.

## Save character data without 3D models

This is the useful path that does **not** require a WoW installation or
`wow.export`. It does require Battle.net developer credentials because the data
comes from Blizzard's APIs.

### One-time Battle.net setup

This setting is not in the normal Battle.net account-management pages. Open
Blizzard's separate **Community Developer Portal** directly:

<https://community.developer.battle.net/access/clients>

Then:

1. Sign in again if the developer portal asks you to.
2. Choose **Create Client**.
3. Fill in the form as shown below.
4. Save the client and copy its client ID and client secret.
5. In WoW Time Capsule, click **Connect Battle.net**.
6. Enter the region, locale, client ID, and client secret.
7. Complete authorization on Blizzard's website in your normal browser.

Use these values in Blizzard's **Create Client** form:

| Form field | What to enter |
|---|---|
| **Client Name** | A globally unique name, such as `YourBattleTag-WoW-Time-Capsule` |
| **Redirect URLs** | `http://127.0.0.1:17891/callback` |
| **Service URL** | Leave this empty |
| **I do not have a service URL for this client** | Select this checkbox |
| **Intended Use** | `Local, personal World of Warcraft character archive tool. The application runs on my computer and calls the Battle.net API directly.` |

Enter the Redirect URL exactly as written, with `http`, the numeric
`127.0.0.1` address, port `17891`, and `/callback`. Do not substitute `https`,
`localhost`, another port, or add a trailing slash.

The Redirect URL is not a website you need to create. `127.0.0.1` means “this
computer.” While you sign in, WoW Time Capsule temporarily listens at that
address so Blizzard can return the authorization result to the app. It accepts
connections only from your own computer and stops listening after sign-in.

Blizzard's developer portal has recently returned misleading `500` errors when
creating clients. One reported cause is choosing a client name that is already
in use: client names must be unique across all developer accounts, but the form
may not explain the collision. If **Create Client** is visible but saving fails,
try a substantially more distinctive name. Portal login and server failures
are controlled by Blizzard and cannot be fixed by WoW Time Capsule.

The temporary sign-in callback listens only on `127.0.0.1`. WoW Time Capsule
never asks for or receives your Blizzard password. It saves the client ID and
secret in local application settings, outside the archive. The access token is
kept in memory and is not archived.

### Export the snapshot

1. Choose an archive folder.
2. Leave **Also export character/pet GLB** clear. API-only export is the safe
   default.
3. Connect Battle.net if you have not already connected.
4. Select a character.
5. Click **Export Selected Character**.

The archive contains the original API JSON, SQLite records, run information,
and an archive-specific README. Depending on what Blizzard exposes for the
character, this can include profile, appearance, equipment, achievements,
pets, mounts, professions, reputations, statistics, and completed quests.

Each successful export creates a new snapshot. It does not replace earlier
snapshots or raw responses.

The character table has a **Game** column. WoW Time Capsule requests Blizzard's
Retail, Classic progression, and Classic Era/Hardcore/seasonal account indexes
separately. Blizzard may still return deleted, renamed, transferred, or stale
characters in these indexes, and newly created characters may take time to
appear. A character appearing in the list does not guarantee that Blizzard has
published its detailed profile yet.

Click any character-table heading to sort that column in ascending order. Click
the same heading again for descending order. The arrow beside the heading shows
the current direction.

### Add a character manually

If automatic character discovery does not list the character:

1. Click **Add Manual Character**.
2. Select its region.
3. Select the game version. For a Hardcore realm, choose **Classic Era /
   Hardcore / seasonal**.
4. Enter the realm slug, such as `defias-pillager`.
5. Enter the character name.
6. Connect Battle.net for the same region and export normally.

The profile must be accessible through Blizzard's API. Use the lowercase URL
form of the realm name without spaces, not its display name.

## Save a 3D character and companion pet

This path is only usable when you have a compatible bridge-enabled build.

1. Start that build and enable its `wow-timecapsule-bridge/v1` service.
2. Confirm that it listens on `http://127.0.0.1:17890` only.
3. Choose the WoW installation, bridge-enabled `wow.export.exe`, and archive
   paths.
4. Select **Also export character/pet GLB (requires bridge-enabled
   wow.export)**.
5. Connect Battle.net and select a character.
6. Click **Export Selected Character**.

The app downloads the character data, asks the bridge to generate a GLB from
the appearance and equipment description, and tries to export one companion
pet. It prefers a favourite pet with a usable display ID, then the first
compatible pet. The character can still be exported if no compatible pet is
available.

If the bridge is absent or incompatible, the run fails. Clear the 3D checkbox
and repeat the export to preserve the API data without models.

## Export a small world area

This operation does not use Battle.net and does not require a developer client.
It does require a local WoW installation and a bridge-enabled `wow.export`.

1. Start the compatible bridge.
2. Choose the WoW installation, bridge-enabled `wow.export.exe`, and archive
   paths.
3. Click **Export World Area**.
4. Enter a numeric map ID.
5. Enter one or more ADT coordinates as `x,y`, separated by semicolons.
6. Enter a meaningful place name.
7. Enter a viewer spawn point as `x,y,z,heading` and confirm.

One request is limited to 16 tiles. Start with one tile and expand only when
needed. The archive keeps terrain, placed WMO/M2 objects, textures, source
metadata, and a portable `scene.json` for a future viewer.

## Archive layout

A typical archive looks like this:

```text
WorldOfWarcraft/
    README.md
    wow_archive.sqlite
    logs/
    raw/api/
    characters/
        us_aman-thul_ExampleName/
            character.json
            snapshots/
                20260921T120000Z/
                    character.glb       # only when 3D export was used
                    source.json
    assets/pets/                        # only when a pet was exported
    world/                              # only for world-area exports
        stormwind_trade_district/
            scene.json
            terrain/
            objects/
            textures/
            source/
```

SQLite stores paths relative to the archive root. Diagnostic run information
may mention local installation paths, but the archive does not use those as
permanent asset paths.

## Open or verify an existing archive

Neither operation requires Battle.net credentials, a WoW installation, or
`wow.export`.

Use **Open Archive** to open the selected archive folder in Windows Explorer.

To check an archive, activate the virtual environment and run:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```

Verification checks SQLite integrity, expected files, SHA-256 checksums, basic
GLB headers, scene references, unsafe stored paths, and external rendering URLs.
A successful check ends with:

```text
Archive is self-contained.
```

This confirms internal consistency, not whether a model visually matches the
character. There is no bundled offline 3D viewer yet. Use an independent glTF
2.0 viewer to inspect any `character.glb` and `pet.glb` files.

## Troubleshooting

### No characters appear

- Check that the selected region matches the Battle.net account.
- Check the OAuth client configuration.
- Try adding the character manually.
- Check whether Blizzard's API exposes that character profile.

### A listed character returns “Blizzard has no profile” or 404

The account index and character profiles are separate Blizzard API records. The
index can contain an old name, an old realm, a deleted character, or a character
whose detailed profile has not been published yet. The error now shows the game
version and API namespace used for the request.

For a recent Hardcore character, use **Add Manual Character**, choose **Classic
Era / Hardcore / seasonal**, and enter its current realm slug and character
name. If that also returns 404, log into the character, log out cleanly, and try
again later; publishing the profile is controlled by Blizzard.

### API export works but 3D export fails

The likely cause is that no compatible `wow-timecapsule-bridge/v1` service is
running. Stock `wow.export` is not sufficient. Clear **Also export
character/pet GLB** and export again to preserve API data only.

### “No supported WoW installation product was detected”

Select the parent World of Warcraft directory containing `_retail_`,
`_classic_`, or `_classic_era_`, not one of those product folders itself.

### Archive verification fails

Read each `ERROR:` line. A missing-file error means an indexed file was moved
or deleted. A checksum mismatch means its contents changed after archival.
Copy the damaged archive before attempting manual repairs.

## Security and privacy

- Never enter a Blizzard password into WoW Time Capsule.
- Never expose a bridge on a public or LAN network interface.
- Review raw profile data before publishing an archive.
- Do not commit generated archives or Blizzard game assets to this repository.
- Back up the whole archive directory, including SQLite, raw JSON, models,
  metadata, and its README.

## What the automated test proves

The integration test uses a small temporary web server that pretends to be the
bridge. It writes a minimal test GLB so the test can exercise communication,
staging, archival, database indexing, checksums, and verification.

The test does **not** run the real `wow.export.exe`, export a real character, or
prove that stock `wow.export` can receive these requests. Real 3D export still
requires the modified bridge-enabled build described above.
