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
        self.assertEqual(set(requested), {"profile-classic1x"})


if __name__ == "__main__":
    unittest.main()
