# WoW Time Capsule user guide

WoW Time Capsule preserves character information made available through
Blizzard's Battle.net APIs. It also turns the latest saved record for each
character into a readable, offline album.

The application exports information only. It does not read a local World of
Warcraft installation or export game assets, models, maps, or textures.

## What can I do, and what do I need?

| What the app can do | What you need to do |
|---|---|
| View an existing character album | Select an archive folder. No Battle.net client or sign-in is needed. |
| Rebuild `index.html` from saved data | Select the archive and click **Rebuild HTML**. No API request is made. |
| Add your own screenshots and notes | Open the archive in **View**, select a character, then use **Add Screenshot** or **Add Note**. |
| Verify an archive | Run the verification command. No Battle.net client or sign-in is needed. |
| Discover your account's characters | Create a Battle.net developer client, then connect and sign in. |
| Export current character information | Connect, select one or more characters, and click **Export Selected Characters**. |

The app has two tabs:

```text
View (default)                         Export
|-- choose an existing archive        |-- connect to Battle.net
|-- browse characters/collections     |-- select one or more characters
|-- add screenshots and notes         |-- export available API records
`-- rebuild/open the HTML album        `-- review every section's result
```

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

The Redirect URL is not a website you need to create. `127.0.0.1` means "this
computer." During sign-in, WoW Time Capsule temporarily listens at that address
so Blizzard can return the authorization result to the application.

Client names must be globally unique. Blizzard's portal may return a misleading
`500` error when a name is already taken; try a more distinctive name if that
happens.

## Connect to Battle.net

1. Start WoW Time Capsule and open the **Export** tab.
2. Choose an **Export destination** folder.
3. Click **Connect Battle.net**.
4. Enter your region, locale, client ID, and client secret.
5. Complete authorization on Blizzard's website in your normal browser.

WoW Time Capsule never asks for or receives your Blizzard password. The access
token stays in memory and is not archived. On Windows, the client ID and secret
are saved as plain text in
`%LOCALAPPDATA%\WoWTimeCapsule\config.json`. Treat that file like a password.

## Export character information

1. Open the **Export** tab.
2. Select one or more rows in the character table. Use Ctrl-click or Shift-click
   to select several characters.
3. Click **Export Selected Characters**.
4. Review **Capture results**, then open the **View** tab.

The archive contains the original API JSON, SQLite records, run information,
an archive-specific README, and a local `index.html` album. Depending on what
Blizzard exposes, a snapshot can include profile, appearance, equipment,
achievements, hunter pets, account pets, account mounts, professions,
reputations, statistics, and completed quests.

Each successful export creates a new snapshot. Earlier snapshots and raw
responses are not replaced.

The result table deliberately distinguishes these cases:

| Result | Meaning |
|---|---|
| **Captured - 16 records** | The request succeeded and returned 16 records. |
| **Captured - 0 records** | The request succeeded, but its list was empty. |
| **Unavailable** | The section does not apply or is not exposed for this character/game version. |
| **Request failed - details** | The app tried the request, but Blizzard rejected it or a connection error occurred. |

An optional section failing does not discard the character data that was
successfully captured. Its exact outcome remains visible under **Archive
details** in the album.

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

## View an archive

The **View** tab is the default and does not connect to Battle.net.

1. Choose a folder containing `wow_archive.sqlite`.
2. Select a character above the embedded album, or select its card in the
   album.
3. Browse overview, equipment, completed achievements, professions,
   reputations, hunter companions, memories, and capture details.
4. Choose **Shared Collections** for account pets and mounts.

The album uses the latest successful saved snapshot for each character and
shows its capture date. It does not create comparisons, reminders, or daily
tracking.

Use **Add Screenshot** or **Add Note** after selecting a character. Screenshots
are copied into the archive, so moving the whole archive does not break them.

### Rebuild or open the HTML album

Click **Rebuild HTML** in View—or **Rebuild HTML from Existing Archive** in
Export—to recreate `index.html` from the existing SQLite data. This does not
contact Blizzard and is useful after presentation improvements. Pets and mounts
stored by an older archive schema are migrated into Shared Collections when the
archive is opened; another API export is not required for that migration.

**Open in Browser** opens the same album outside the desktop app. Its data,
styles, and scripts are embedded in `index.html`; screenshots use relative
paths under the archive. It works directly from disk and makes no web requests.

## Pets and mounts

There are two different kinds of pets:

| Data | Where it appears | Notes |
|---|---|---|
| **Hunter companions** | Inside the selected hunter's page | Character-specific hunter pet records. Non-hunters are marked **Unavailable**. Blizzard may not expose this endpoint for every game version. |
| **Battle pets** | **Shared Collections** | Account collection data. It is not assigned to each character. |
| **Mounts** | **Shared Collections** | Account collection data. It is not assigned to each character. |

Account collection requests use the account's Retail profile namespace even
when the selected character is Classic. Classic characters still use their own
Classic namespace for character-specific requests.

If pets or mounts are missing, look in `raw/api/` for files ending in
`_pets.json`, `_mounts.json`, or `_hunter_pets.json`:

- A populated file means the API request succeeded; if the album is empty,
  rebuild the HTML and then investigate the SQLite import.
- If a file is missing and the result says **Request failed**, Blizzard did not
  return usable data; the error details are shown in the capture result.
- No hunter-pet request for a known non-hunter is expected and is shown as
  **Unavailable**.
- A successful response with an empty list is shown as **Captured - 0
  records**, which is different from a failed request.

## Archive layout

A typical archive contains:

```text
WorldOfWarcraft/
    README.md
    index.html
    wow_archive.sqlite
    media/
        screenshots/
    raw/
        api/
            2026-10-01/
                run_1_account.json
                run_1_character_profile.json
                run_1_equipment.json
                ...
```

The SQLite database indexes character snapshots, collection snapshots, notes,
screenshots, and per-section outcomes. The `raw/api` directory preserves
Blizzard's original responses as UTF-8 JSON.

## Open or verify an archive

Neither operation requires Battle.net authorization. Use **Open in Browser** to
open the album. You can also double-click `index.html` in the archive folder.

To verify an archive, activate the virtual environment and run:

```powershell
python -m wow_timecapsule.verify D:\GameArchives\WorldOfWarcraft
```

Verification checks SQLite integrity, required raw files and screenshots, safe
relative paths, and SHA-256 checksums. A successful check ends with:

```text
Archive is self-contained.
```

## Troubleshooting

### No characters appear

- Check that the selected region matches your Battle.net account.
- Check the developer client ID, secret, and Redirect URL.
- Try adding the character manually.
- Check whether Blizzard's API exposes the character profile.

### A listed character returns "Blizzard has no profile" or 404

The account index and character profiles are separate Blizzard records. The
index can contain an old name, old realm, deleted character, or a character
whose detailed profile has not been published yet.

For a recent Hardcore character, use **Add Manual Character**, choose **Classic
Era / Hardcore / seasonal**, and enter its current realm slug and name. If that
also returns 404, log into the character, log out cleanly, and try again later.

### Pets or mounts are empty

Check the **Capture results** table first; it tells you whether the section was
unavailable, failed, or was captured with zero records. Then use the file checks
in [Pets and mounts](#pets-and-mounts). A previous successful shared collection
can still be displayed when the newest collection request fails; the album
labels this clearly.

### The archive fails verification

Read each `ERROR:` line. A missing-file error means an indexed JSON or screenshot
was moved or deleted. A checksum mismatch means its contents changed after it
was saved. Copy the damaged archive before attempting manual repairs.

## Security and privacy

- Never enter a Blizzard password into WoW Time Capsule.
- Keep the developer client secret and config file private.
- Review raw profile data and personal notes before publishing an archive.
- Do not commit generated archives to this repository.
- Back up the entire archive directory, including SQLite, HTML, media, and raw
  JSON.
