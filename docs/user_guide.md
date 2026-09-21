# WoW Time Capsule User Guide

## What the integration test actually proves

The automated Phase 2 test does **not** run the real `wow.export.exe` or export a real World of Warcraft character.

Instead, the test starts a small temporary web server on `127.0.0.1`. This server pretends to be the proposed wow.export bridge and follows the documented bridge protocol. When WoW Time Capsule requests a character export, the test server writes a minimal test GLB file into the requested temporary folder and reports that file back to the exporter.

WoW Time Capsule then performs the same archive operations it would perform for a real export:

1. It checks that the bridge returned a file inside the approved temporary directory.
2. It copies the GLB into the character's archive directory.
3. It calculates and records the file's SHA-256 checksum and size.
4. It links the model to the corresponding character snapshot in SQLite.
5. It runs archive verification and confirms that the file exists, its checksum matches, and its GLB header is valid.

This proves that the communication, staging, archival, database, checksum, and verification code work together. It does **not** prove that stock wow.export can currently receive the request or generate the correct character model. A compatible bridge-enabled build is still required for real 3D exports.

## Current capabilities

WoW Time Capsule can currently:

- authenticate through Blizzard's website without asking for your Blizzard password;
- discover characters associated with a Battle.net account;
- accept a manually entered public character;
- download available profile, appearance, equipment, achievement, pet, mount, profession, reputation, statistic, and completed-quest data;
- preserve the original API JSON;
- create repeatable, non-destructive SQLite snapshots;
- request character and pet GLB exports from a compatible wow.export bridge;
- export a small manually selected set of ADT map tiles, including terrain, placed WMO/M2 objects, textures, and source metadata;
- generate a versioned, portable `scene.json` with a chosen spawn point;
- preserve and checksum files returned by that bridge;
- generate an archive README;
- verify that an archive remains internally consistent.

The application does not yet include the Phase 4 offline 3D viewer.

## Requirements

- Windows with Python 3.12
- A Battle.net developer OAuth client
- A local World of Warcraft installation for local 3D extraction
- For 3D exports, a compatible wow.export build implementing `wow-timecapsule-bridge/v1`

Stock wow.export does not currently implement the required bridge protocol. You can still create complete API-data snapshots without it.

## Install the application

Open PowerShell in the repository directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

Start the application:

```powershell
python -m wow_timecapsule
```

## Configure Battle.net access

Create an application in the Battle.net developer portal and obtain its OAuth client ID and client secret.

When you click **Connect Battle.net**, WoW Time Capsule asks for:

- **Region:** `us`, `eu`, `kr`, or `tw`
- **Locale:** for example, `en_US` or `en_GB`
- **OAuth client ID**
- **OAuth client secret**

Authentication happens in your normal browser on Blizzard's website. Blizzard redirects the result to a temporary callback server bound to `127.0.0.1` on your computer.

WoW Time Capsule never requests or receives your Blizzard email address or password. The client ID and secret are saved in the local application configuration, outside the archive. The access token remains in memory and is not preserved as archival data.

## Choose paths

Set the three paths at the top of the main window:

### WoW Installation

Select the World of Warcraft root directory, normally similar to:

```text
C:\Program Files (x86)\World of Warcraft
```

The application looks for products such as `_retail_`, `_classic_`, and `_classic_era_` beneath this directory.

### wow.export

Select `wow.export.exe`. This path is used for version diagnostics. Real automated model export also requires a compatible bridge-enabled build to be running.

### Archive

Choose a separate directory for preserved data, for example:

```text
D:\GameArchives\WorldOfWarcraft
```

Do not select the source-code repository as the archive directory. Generated archives are personal data and may contain character information and extracted game assets.

## Create an API-only archive

API-only mode does not require wow.export or a bridge.

1. Clear the **Export character GLB and default companion pet** checkbox.
2. Click **Connect Battle.net**.
3. Complete authorization in your browser.
4. Select a character in the table.
5. Click **Export Selected Character**.

The resulting archive contains the raw API responses, SQLite records, run information, and an archive-specific README.

Every successful export creates another snapshot. Existing snapshots and raw responses are not replaced.

## Add a character manually

If account character discovery is unavailable:

1. Click **Add Manual Character**.
2. Select the character's region.
3. Enter the realm slug, such as `aman-thul`.
4. Enter the character name.
5. Connect Battle.net for the same region and export normally.

The profile must be accessible through the supported Blizzard API. A display realm name is not the same as a realm slug; use the lowercase URL form without spaces.

## Create a 3D character and pet archive

Real 3D export requires a bridge-enabled wow.export build.

1. Start the compatible wow.export build.
2. Start or enable its `wow-timecapsule-bridge/v1` service.
3. Confirm that it listens only on:

   ```text
   http://127.0.0.1:17890
   ```

4. In WoW Time Capsule, select the WoW installation and `wow.export.exe` paths.
5. Leave **Export character GLB and default companion pet** selected.
6. Connect Battle.net and select a character.
7. Click **Export Selected Character**.

The exporter asks the bridge to open the detected WoW product and generate a GLB from the preserved appearance and equipment description. It then asks for one companion pet model, preferring a favorite pet with a usable display ID and otherwise using the first compatible pet.

If no compatible pet display ID is available, the character can still be exported without a pet. If the bridge is missing or incompatible, the archival run is marked failed and the UI displays an error. Disable the 3D checkbox to create an API-only snapshot instead.

The exact bridge request and response format is documented in [BRIDGE_PROTOCOL.md](BRIDGE_PROTOCOL.md).

## Export a small world area

1. Start the compatible bridge and choose the WoW installation, wow.export, and archive paths.
2. Click **Export World Area**.
3. Enter the numeric map ID and one or more ADT coordinates as `x,y`, separated by semicolons.
4. Give the place a meaningful name and enter `x,y,z,heading` for its viewer spawn point.
5. Confirm the export.

The UI limits one request to 16 tiles. Begin with one tile and expand only when needed. The archive stores original bridge output beneath `world/<name>/`, classifies geometry as terrain or placed objects using bridge metadata, retains textures and metadata, and creates the stable `scene.json` used by future viewers.

## Archive layout

A typical archive looks like:

```text
WorldOfWarcraft/
    README.md
    wow_archive.sqlite
    logs/
        wow_export_probe_....json
    raw/
        api/
            2026-09-21/
                run_1_account.json
                run_1_character_profile.json
                run_1_appearance.json
                run_1_equipment.json
                run_1_achievements.json
                run_1_pets.json
    characters/
        us_aman-thul_ExampleName/
            character.json
            snapshots/
                20260921T120000Z/
                    character.glb
                    source.json
    assets/
        pets/
            BattlePet-.../
                pet.json
                pet.glb
                source.json
    world/
        stormwind_trade_district/
            scene.json
            terrain/
            objects/
            textures/
            source/
```

All paths stored in SQLite are relative to the archive root. Local installation paths may appear in diagnostic run information but are not used as permanent asset paths.

## Verify an archive

Activate the virtual environment and run:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```

Verification checks:

- SQLite integrity;
- expected raw, source, and asset files;
- SHA-256 checksums;
- basic GLB version and length information;
- scene references, when Phase 3 scenes are present;
- unsafe or absolute stored paths;
- external rendering URLs.

A successful result ends with:

```text
Archive is self-contained.
```

Verification confirms archive consistency. It does not determine whether a model visually matches the character. Until the bundled viewer exists, open `character.glb` and `pet.glb` in an independent glTF 2.0 viewer for visual inspection.

## Troubleshooting

### No characters appear

- Confirm that the selected region matches the Battle.net account.
- Confirm that the OAuth application and redirect configuration are valid.
- Try manual character entry.
- Check whether the character profile is available through Blizzard's API.

### The API export works but 3D export fails

This normally means the bridge is not running or does not implement `wow-timecapsule-bridge/v1`. Stock wow.export is not sufficient by itself. Disable the 3D checkbox to continue preserving API data.

### “No supported WoW installation product was detected”

Select the parent World of Warcraft directory containing `_retail_`, `_classic_`, or `_classic_era_`, rather than selecting one of those product directories directly.

### The archive fails verification

Read each `ERROR:` line in the verifier output. A missing-file error means an indexed file was moved or deleted. A checksum mismatch means its contents changed after archival. Preserve the damaged archive before attempting manual repairs.

## Security and privacy

- Never enter a Blizzard password into WoW Time Capsule.
- Do not run a bridge that listens on a public or LAN network interface.
- Do not publish an archive without reviewing its raw profile data.
- Do not commit generated archives or Blizzard game assets to the public source repository.
- Back up the entire archive directory, including SQLite, raw JSON, models, metadata, and its README.
