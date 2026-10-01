# WoW Time Capsule user guide

WoW Time Capsule preserves character information made available through
Blizzard's Battle.net APIs. It stores the original JSON responses and builds a
SQLite history from repeated snapshots.

The application exports information only. It does not read a local World of
Warcraft installation or export game assets, models, maps, or textures.

## What can I do, and what do I need?

| What the app can do | Battle.net developer client | Browser sign-in | Archive folder |
|---|:---:|:---:|:---:|
| Open an existing archive folder | No | No | Existing |
| Verify an existing archive | No | No | Existing |
| Save available character information | Yes | Yes | Yes |

The Battle.net developer credentials are the **client ID and client secret**
for a client you create in Blizzard's developer portal. They are not your
Blizzard username and password.

## Install and start

Open PowerShell in the repository directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
python -m wow_timecapsule
```

## Create the Battle.net developer client

This setting is not in the normal Battle.net account pages. Open Blizzard's
separate Community Developer Portal:

<https://community.developer.battle.net/access/clients>

Choose **Create Client** and fill in the form as follows:

| Form field | What to enter |
|---|---|
| **Client Name** | A globally unique name, such as `YourBattleTag-WoW-Time-Capsule` |
| **Redirect URLs** | `http://127.0.0.1:17891/callback` |
| **Service URL** | Leave empty |
| **I do not have a service URL for this client** | Select this checkbox |
| **Intended Use** | `Local, personal World of Warcraft character archive tool. The application runs on my computer and calls the Battle.net API directly.` |

Enter the Redirect URL exactly as written. Do not substitute `https`,
`localhost`, another port, or add a trailing slash.

The Redirect URL is not a website you need to create. `127.0.0.1` means “this
computer.” During sign-in, WoW Time Capsule temporarily listens at that address
so Blizzard can return the authorization result to the application.

Client names must be globally unique. Blizzard's portal may return a misleading
`500` error when a name is already taken; try a more distinctive name if that
happens.

## Connect to Battle.net

1. Start WoW Time Capsule.
2. Choose an **Archive** folder.
3. Click **Connect Battle.net**.
4. Enter your region, locale, client ID, and client secret.
5. Complete authorization on Blizzard's website in your normal browser.

WoW Time Capsule never asks for or receives your Blizzard password. It saves
the client ID and secret in local application settings outside the archive. The
access token stays in memory and is not archived.

## Export a character snapshot

1. Select a character in the table.
2. Click **Export Selected Character**.

The archive contains the original API JSON, SQLite records, run information,
and an archive-specific README. Depending on what Blizzard exposes for the
character, the snapshot can include profile, appearance, equipment,
achievements, pets, mounts, professions, reputations, statistics, and completed
quests.

Each successful export creates a new snapshot. Earlier snapshots and raw
responses are not replaced.

### Sort the character table

Click any table heading to sort that column in ascending order. Click the same
heading again for descending order. The arrow beside the heading shows the
current direction.

### Retail, Classic, and Hardcore characters

The **Game** column identifies Retail, Classic progression, or Classic
Era/Hardcore/seasonal characters. The application requests those Blizzard API
namespaces separately.

Blizzard may return deleted, renamed, transferred, or stale characters in an
account index, and newly created characters may take time to appear. A character
appearing in the list does not guarantee its detailed profile is available.

### Add a character manually

If automatic discovery does not list a character:

1. Click **Add Manual Character**.
2. Select its region.
3. Select the game version. For Hardcore, choose **Classic Era / Hardcore /
   seasonal**.
4. Enter the realm slug, such as `defias-pillager`.
5. Enter the character name.
6. Export normally.

Use the lowercase URL form of the realm name rather than its display name.
Manual entry skips discovery but still requires Battle.net authorization.

## Archive layout

A typical archive contains:

```text
WorldOfWarcraft/
    README.md
    wow_archive.sqlite
    raw/
        api/
            2026-10-01/
                run_1_account.json
                run_1_character_profile.json
                run_1_equipment.json
                ...
```

The SQLite database indexes character snapshots and their related information.
The `raw/api` directory preserves Blizzard's original responses as UTF-8 JSON.

## Open or verify an archive

Neither operation requires Battle.net authorization.

Use **Open Archive** to open the selected folder in Windows Explorer.

To verify an archive, activate the virtual environment and run:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```

Verification checks SQLite integrity, required raw files, safe relative paths,
and SHA-256 checksums. A successful check ends with:

```text
Archive is self-contained.
```

## Troubleshooting

### No characters appear

- Check that the selected region matches your Battle.net account.
- Check the developer client ID, secret, and Redirect URL.
- Try adding the character manually.
- Check whether Blizzard's API exposes the character profile.

### A listed character returns “Blizzard has no profile” or 404

The account index and character profiles are separate Blizzard records. The
index can contain an old name, old realm, deleted character, or a character
whose detailed profile has not been published yet.

For a recent Hardcore character, use **Add Manual Character**, choose **Classic
Era / Hardcore / seasonal**, and enter its current realm slug and name. If that
also returns 404, log into the character, log out cleanly, and try again later.

### The archive fails verification

Read each `ERROR:` line. A missing-file error means an indexed JSON file was
moved or deleted. A checksum mismatch means its contents changed after export.
Copy the damaged archive before attempting manual repairs.

## Security and privacy

- Never enter a Blizzard password into WoW Time Capsule.
- Keep the developer client secret private.
- Review raw profile data before publishing an archive.
- Do not commit generated archives to this repository.
- Back up the entire archive directory, including SQLite and raw JSON.
