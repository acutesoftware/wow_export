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
                    ))
        raw: dict[str, Any] = {"namespaces": sources}
        if failures:
            raw["_failures"] = failures
        return characters, raw, status

    def capture_character(self, character: CharacterRef, save: Callable[[str, str, dict, int], None]) -> dict[str, dict]:
        base = f"/profile/wow/character/{character.realm_slug.lower()}/{character.name.lower()}"
        endpoints = {
            "character_profile": base,
            "achievements": base + "/achievements",
            "equipment": base + "/equipment",
            "appearance": base + "/appearance",
            "pets": "/profile/user/wow/collections/pets",
            "mounts": "/profile/user/wow/collections/mounts",
            "professions": base + "/professions",
            "reputations": base + "/reputations",
            "statistics": base + "/statistics",
            "quests": base + "/quests/completed",
        }
        captured: dict[str, dict] = {}
        failures: dict[str, str] = {}
        for name, endpoint in endpoints.items():
            try:
                data, status = self.get(endpoint, character.namespace)
                save(name, endpoint, data, status)
                captured[name] = data
            except httpx.HTTPError as exc:
                failures[name] = str(exc)
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
        return captured
