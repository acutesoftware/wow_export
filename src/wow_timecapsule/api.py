from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx


REGION_HOSTS = {"us": "us.api.blizzard.com", "eu": "eu.api.blizzard.com", "kr": "kr.api.blizzard.com", "tw": "tw.api.blizzard.com"}
PROFILE_NAMESPACES = ("profile", "profile-classic", "profile-classic1x")
PROFILE_LABELS = {
    "profile": "Retail",
    "profile-classic": "Classic progression",
    "profile-classic1x": "Classic Era / Hardcore / seasonal",
}


@dataclass(frozen=True, slots=True)
class CharacterRef:
    region: str
    realm_id: int | None
    realm_slug: str
    realm_name: str
    character_id: int | None
    name: str
    level: int | None = None
    playable_class: str = ""
    namespace: str = "profile"
    playable_class_id: int | None = None

    @property
    def game_version(self) -> str:
        return PROFILE_LABELS.get(self.namespace, self.namespace)


class BlizzardAPI:
    def __init__(self, region: str, locale: str, access_token: str):
        if region not in REGION_HOSTS:
            raise ValueError(f"Unsupported region: {region}")
        self.region, self.locale = region, locale
        self.client = httpx.Client(
            base_url=f"https://{REGION_HOSTS[region]}",
            headers={"Authorization": f"Bearer {access_token}", "User-Agent": "WoW-Time-Capsule/0.1"},
            timeout=45,
        )

    def close(self) -> None:
        self.client.close()

    def get(self, path: str, namespace: str = "profile") -> tuple[dict[str, Any], int]:
        response = self.client.get(path, params={"namespace": f"{namespace}-{self.region}", "locale": self.locale})
        response.raise_for_status()
        return response.json(), response.status_code

    def discover_characters(self) -> tuple[list[CharacterRef], dict[str, Any], int]:
        characters: list[CharacterRef] = []
        sources: dict[str, dict[str, Any]] = {}
        failures: dict[str, str] = {}
        status = 200
        for namespace in PROFILE_NAMESPACES:
            qualified = f"{namespace}-{self.region}"
            try:
                data, status = self.get("/profile/user/wow", namespace)
            except httpx.HTTPError as exc:
                if namespace == "profile":
                    raise
                failures[qualified] = str(exc)
                continue
            sources[qualified] = data
            for account in data.get("wow_accounts", []):
                for char in account.get("characters", []):
                    realm = char.get("realm", {})
                    characters.append(CharacterRef(
                        self.region, realm.get("id"), realm.get("slug", ""), realm.get("name", ""),
                        char.get("id"), char.get("name", ""), char.get("level"),
                        char.get("playable_class", {}).get("name", ""), namespace,
                        char.get("playable_class", {}).get("id"),
                    ))
        raw: dict[str, Any] = {"namespaces": sources}
        if failures:
            raw["_failures"] = failures
        return characters, raw, status

    def capture_character(self, character: CharacterRef, save: Callable[[str, str, dict, int], None]) -> dict[str, dict]:
        base = f"/profile/wow/character/{character.realm_slug.lower()}/{character.name.lower()}"
        endpoints = {
            "character_profile": (base, character.namespace),
            "achievements": (base + "/achievements", character.namespace),
            "equipment": (base + "/equipment", character.namespace),
            "appearance": (base + "/appearance", character.namespace),
            "hunter_pets": (base + "/hunter-pets", character.namespace),
            # These are account collections. They use the account/Retail profile
            # namespace even when the selected character is Classic.
            "pets": ("/profile/user/wow/collections/pets", "profile"),
            "mounts": ("/profile/user/wow/collections/mounts", "profile"),
            "professions": (base + "/professions", character.namespace),
            "reputations": (base + "/reputations", character.namespace),
            "statistics": (base + "/statistics", character.namespace),
            "quests": (base + "/quests/completed", character.namespace),
        }
        captured: dict[str, dict] = {}
        failures: dict[str, str] = {}
        outcomes: dict[str, dict[str, Any]] = {}
        for name, (endpoint, namespace) in endpoints.items():
            if name == "hunter_pets" and character.playable_class_id not in (None, 3):
                outcomes[name] = {
                    "status": "unavailable",
                    "count": None,
                    "detail": "Not applicable: this character is not a Hunter.",
                }
                continue
            try:
                data, status = self.get(endpoint, namespace)
                save(name, endpoint, data, status)
                captured[name] = data
                outcomes[name] = {
                    "status": "captured",
                    "count": self._record_count(name, data),
                    "detail": "",
                }
            except httpx.HTTPError as exc:
                failures[name] = str(exc)
                outcomes[name] = {
                    "status": "request_failed",
                    "count": None,
                    "detail": str(exc),
                }
        if "character_profile" not in captured:
            namespace = f"{character.namespace}-{self.region}"
            raise RuntimeError(
                f"Blizzard has no profile for {character.name} — {character.realm_name or character.realm_slug} "
                f"in {character.game_version} ({namespace}). The account list can contain deleted, "
                "renamed, transferred, or not-yet-published characters. If the game version is wrong, "
                "add the character manually with the correct version. Original error: "
                f"{failures.get('character_profile', 'unknown error')}"
            )
        if failures:
            captured["_failures"] = failures
        captured["_outcomes"] = outcomes
        return captured

    @staticmethod
    def _record_count(name: str, data: dict[str, Any]) -> int | None:
        keys = {
            "achievements": "achievements",
            "equipment": "equipped_items",
            "hunter_pets": "hunter_pets",
            "pets": "pets",
            "mounts": "mounts",
            "reputations": "reputations",
            "quests": "quests",
        }
        if name == "professions":
            return len(data.get("primaries", [])) + len(data.get("secondaries", []))
        key = keys.get(name)
        if key:
            value = data.get(key, [])
            return len(value) if isinstance(value, list) else 0
        return 1
