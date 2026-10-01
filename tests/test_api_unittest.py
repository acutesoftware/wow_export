import unittest

import httpx

from wow_timecapsule.api import BlizzardAPI, CharacterRef


class BlizzardAPITests(unittest.TestCase):
    def test_discovers_retail_and_classic1x_separately(self):
        api = BlizzardAPI.__new__(BlizzardAPI)
        api.region = "us"
        api.locale = "en_US"
        requested = []

        def fake_get(path, namespace="profile"):
            requested.append(namespace)
            if namespace == "profile-classic":
                request = httpx.Request("GET", "https://us.api.blizzard.com/profile/user/wow")
                response = httpx.Response(404, request=request)
                raise httpx.HTTPStatusError("not found", request=request, response=response)
            suffix = "hardcore" if namespace == "profile-classic1x" else "retail"
            return {
                "wow_accounts": [{"characters": [{
                    "realm": {"id": 1, "slug": f"{suffix}-realm", "name": f"{suffix} realm"},
                    "id": 2,
                    "name": f"{suffix}char",
                    "level": 10,
                    "playable_class": {"name": "Warrior"},
                }]}]
            }, 200

        api.get = fake_get
        characters, raw, status = api.discover_characters()

        self.assertEqual(requested, ["profile", "profile-classic", "profile-classic1x"])
        self.assertEqual([char.namespace for char in characters], ["profile", "profile-classic1x"])
        self.assertEqual(characters[1].game_version, "Classic Era / Hardcore / seasonal")
        self.assertIn("profile-classic1x-us", raw["namespaces"])
        self.assertIn("profile-classic-us", raw["_failures"])
        self.assertEqual(status, 200)

    def test_capture_uses_character_namespace_and_explains_missing_profile(self):
        api = BlizzardAPI.__new__(BlizzardAPI)
        api.region = "us"
        api.locale = "en_US"
        requested = []

        def fake_get(path, namespace="profile"):
            requested.append(namespace)
            request = httpx.Request("GET", "https://us.api.blizzard.com" + path)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("404 Not Found", request=request, response=response)

        api.get = fake_get
        character = CharacterRef(
            "us", None, "doomhowl", "Doomhowl", None, "Example",
            namespace="profile-classic1x",
        )

        with self.assertRaisesRegex(RuntimeError, "profile-classic1x-us"):
            api.capture_character(character, lambda *_args: None)
        self.assertTrue(requested)
        self.assertEqual(set(requested), {"profile-classic1x", "profile"})

    def test_account_collections_use_retail_namespace_for_classic_character(self):
        api = BlizzardAPI.__new__(BlizzardAPI)
        api.region = "us"
        api.locale = "en_US"
        requested = []

        def fake_get(path, namespace="profile"):
            requested.append((path, namespace))
            if path.endswith("/hunter-pets"):
                return {"hunter_pets": []}, 200
            if path.endswith("/collections/pets"):
                return {"pets": []}, 200
            if path.endswith("/collections/mounts"):
                return {"mounts": []}, 200
            return {}, 200

        api.get = fake_get
        character = CharacterRef(
            "us", None, "doomhowl", "Doomhowl", None, "Example", 60,
            "Hunter", "profile-classic1x", 3,
        )
        captured = api.capture_character(character, lambda *_args: None)

        collection_namespaces = {
            namespace for path, namespace in requested if "/profile/user/wow/collections/" in path
        }
        character_namespaces = {
            namespace for path, namespace in requested if "/profile/wow/character/" in path
        }
        self.assertEqual(collection_namespaces, {"profile"})
        self.assertEqual(character_namespaces, {"profile-classic1x"})
        self.assertEqual(captured["_outcomes"]["pets"]["count"], 0)
        self.assertEqual(captured["_outcomes"]["hunter_pets"]["status"], "captured")

    def test_non_hunter_pet_capture_is_unavailable_not_failed(self):
        api = BlizzardAPI.__new__(BlizzardAPI)
        api.region = "us"
        api.locale = "en_US"
        requested = []

        def fake_get(path, namespace="profile"):
            requested.append(path)
            return {}, 200

        api.get = fake_get
        character = CharacterRef(
            "us", None, "realm", "Realm", None, "Mage", 80,
            "Mage", "profile", 8,
        )
        captured = api.capture_character(character, lambda *_args: None)

        self.assertNotIn("/profile/wow/character/realm/mage/hunter-pets", requested)
        self.assertEqual(captured["_outcomes"]["hunter_pets"]["status"], "unavailable")
        self.assertIsNone(captured["_outcomes"]["hunter_pets"]["count"])

    def test_completed_achievement_reference_details_are_downloaded(self):
        api = BlizzardAPI.__new__(BlizzardAPI)
        api.region = "us"
        api.locale = "en_US"
        requested = []
        saved = []

        def fake_get(path, namespace="profile"):
            requested.append((path, namespace))
            if path.endswith("/achievements"):
                return {"achievements": [
                    {"achievement": {"id": 6, "name": "Level 10"},
                     "completed_timestamp": 1_700_000_000_000},
                    {"achievement": {"id": 7, "name": "Not complete"},
                     "criteria": {"is_completed": False}},
                ]}, 200
            if path == "/data/wow/achievement/6":
                return {
                    "id": 6, "name": "Level 10", "description": "Reach level 10.",
                    "criteria": {"description": "Reach level 10"},
                }, 200
            return {}, 200

        api.get = fake_get
        character = CharacterRef("us", 1, "realm", "Realm", 42, "Example")
        captured = api.capture_character(
            character, lambda *args: saved.append(args), set()
        )

        self.assertIn(("/data/wow/achievement/6", "static"), requested)
        self.assertNotIn(("/data/wow/achievement/7", "static"), requested)
        self.assertEqual(
            captured["achievements"]["_reference_details"]["6"]["description"],
            "Reach level 10.",
        )
        self.assertEqual(captured["_outcomes"]["achievement_details"]["count"], 1)
        self.assertTrue(any(item[0] == "achievement_details" for item in saved))


if __name__ == "__main__":
    unittest.main()
