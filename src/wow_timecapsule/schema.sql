PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS archive_run (
 archive_run_id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
 app_version TEXT NOT NULL, region TEXT, locale TEXT, status TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS account (
 account_id INTEGER PRIMARY KEY, blizzard_account_id TEXT UNIQUE, battletag TEXT,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS character (
 character_id INTEGER PRIMARY KEY, blizzard_character_id INTEGER, region TEXT NOT NULL,
 realm_id INTEGER, realm_slug TEXT NOT NULL, realm_name TEXT, character_name TEXT NOT NULL,
 namespace TEXT NOT NULL DEFAULT 'profile', first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(region, realm_slug, character_name, namespace)
);
CREATE TABLE IF NOT EXISTS character_snapshot (
 character_snapshot_id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL REFERENCES character,
 archive_run_id INTEGER NOT NULL REFERENCES archive_run, observed_at TEXT NOT NULL,
 level INTEGER, race_id INTEGER, race_name TEXT, class_id INTEGER, class_name TEXT,
 specialization TEXT, faction TEXT, guild_name TEXT, achievement_points INTEGER, money INTEGER,
 last_login_if_available TEXT, raw_json_path TEXT
);
CREATE TABLE IF NOT EXISTS equipment (equipment_id INTEGER PRIMARY KEY, blizzard_item_id INTEGER, name TEXT, slot_type TEXT, UNIQUE(blizzard_item_id, slot_type));
CREATE TABLE IF NOT EXISTS character_equipment (character_snapshot_id INTEGER REFERENCES character_snapshot, equipment_id INTEGER REFERENCES equipment, observed_at TEXT NOT NULL, raw_json TEXT, PRIMARY KEY(character_snapshot_id, equipment_id));
CREATE TABLE IF NOT EXISTS achievement (achievement_id INTEGER PRIMARY KEY, name TEXT, description TEXT, points INTEGER, category TEXT, requirements TEXT, reward_description TEXT, is_account_wide INTEGER, display_order INTEGER, reference_json TEXT);
CREATE TABLE IF NOT EXISTS character_achievement (character_snapshot_id INTEGER REFERENCES character_snapshot, achievement_id INTEGER REFERENCES achievement, is_completed INTEGER, completed_at TEXT, criteria TEXT, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, achievement_id));
CREATE TABLE IF NOT EXISTS pet (pet_id INTEGER PRIMARY KEY, pet_guid TEXT, species_id INTEGER, display_id INTEGER, creature_id INTEGER, name TEXT, custom_name TEXT, UNIQUE(pet_guid));
CREATE TABLE IF NOT EXISTS mount (mount_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS collection_snapshot (collection_snapshot_id INTEGER PRIMARY KEY, archive_run_id INTEGER NOT NULL REFERENCES archive_run, kind TEXT NOT NULL, observed_at TEXT NOT NULL, status TEXT NOT NULL, record_count INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS collection_pet (collection_snapshot_id INTEGER REFERENCES collection_snapshot, pet_id INTEGER REFERENCES pet, level INTEGER, quality TEXT, breed TEXT, is_favorite INTEGER, raw_json TEXT, PRIMARY KEY(collection_snapshot_id, pet_id));
CREATE TABLE IF NOT EXISTS collection_mount (collection_snapshot_id INTEGER REFERENCES collection_snapshot, mount_id INTEGER REFERENCES mount, is_collected INTEGER, raw_json TEXT, PRIMARY KEY(collection_snapshot_id, mount_id));
CREATE TABLE IF NOT EXISTS character_hunter_pet (character_snapshot_id INTEGER REFERENCES character_snapshot, pet_key TEXT, name TEXT, species_id INTEGER, creature_id INTEGER, display_id INTEGER, level INTEGER, slot INTEGER, is_active INTEGER, raw_json TEXT, PRIMARY KEY(character_snapshot_id, pet_key));
CREATE TABLE IF NOT EXISTS profession (profession_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS character_profession (character_snapshot_id INTEGER REFERENCES character_snapshot, profession_id INTEGER REFERENCES profession, skill_points INTEGER, max_skill_points INTEGER, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, profession_id));
CREATE TABLE IF NOT EXISTS profession_tier (profession_tier_id INTEGER PRIMARY KEY, profession_id INTEGER REFERENCES profession, name TEXT);
CREATE TABLE IF NOT EXISTS character_profession_tier (character_snapshot_id INTEGER REFERENCES character_snapshot, profession_tier_id INTEGER REFERENCES profession_tier, skill_points INTEGER, max_skill_points INTEGER, known_recipes INTEGER, observed_at TEXT NOT NULL, raw_json TEXT, PRIMARY KEY(character_snapshot_id, profession_tier_id));
CREATE TABLE IF NOT EXISTS reputation (reputation_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS character_reputation (character_snapshot_id INTEGER REFERENCES character_snapshot, reputation_id INTEGER REFERENCES reputation, standing TEXT, value INTEGER, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, reputation_id));
CREATE TABLE IF NOT EXISTS currency (currency_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS character_currency (character_snapshot_id INTEGER REFERENCES character_snapshot, currency_id INTEGER REFERENCES currency, quantity INTEGER, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, currency_id));
CREATE TABLE IF NOT EXISTS character_stat (character_snapshot_id INTEGER REFERENCES character_snapshot, name TEXT, value REAL, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, name));
CREATE TABLE IF NOT EXISTS quest (quest_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS character_quest (character_snapshot_id INTEGER REFERENCES character_snapshot, quest_id INTEGER REFERENCES quest, status TEXT, completed_at TEXT, observed_at TEXT NOT NULL, PRIMARY KEY(character_snapshot_id, quest_id));
CREATE TABLE IF NOT EXISTS capture_section (character_snapshot_id INTEGER REFERENCES character_snapshot, section_name TEXT, status TEXT NOT NULL, record_count INTEGER, detail TEXT, raw_json_path TEXT, PRIMARY KEY(character_snapshot_id, section_name));
CREATE TABLE IF NOT EXISTS character_memory (memory_id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL REFERENCES character, title TEXT, body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS screenshot (screenshot_id INTEGER PRIMARY KEY, character_id INTEGER NOT NULL REFERENCES character, relative_path TEXT NOT NULL UNIQUE, caption TEXT, added_at TEXT NOT NULL, sha256 TEXT);
CREATE TABLE IF NOT EXISTS raw_api_file (raw_api_file_id INTEGER PRIMARY KEY, archive_run_id INTEGER REFERENCES archive_run, endpoint TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, http_status INTEGER, observed_at TEXT NOT NULL);
