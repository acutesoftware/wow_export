from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

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
    protected_path: str = ""
    playable_race: str = ""
    playable_race_id: int | None = None
    faction: str = ""
    gender: str = ""
    protected_namespace: str = "profile"

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
                    protected_href = char.get("protected_character", {}).get("href", "")
                    protected_url = urlparse(protected_href) if protected_href else None
                    protected_path = protected_url.path if protected_url else ""
                    protected_qualified = (
                        parse_qs(protected_url.query).get("namespace", ["profile"])[0]
                        if protected_url else "profile"
                    )
                    protected_namespace = protected_qualified.removesuffix(
                        f"-{self.region}"
                    )
                    characters.append(CharacterRef(
                        self.region, realm.get("id"), realm.get("slug", ""), realm.get("name", ""),
                        char.get("id"), char.get("name", ""), char.get("level"),
                        char.get("playable_class", {}).get("name", ""), namespace,
                        char.get("playable_class", {}).get("id"),
                        protected_path,
                        char.get("playable_race", {}).get("name", ""),
                        char.get("playable_race", {}).get("id"),
                        char.get("faction", {}).get("name", ""),
                        char.get("gender", {}).get("name", ""),
                        protected_namespace,
                    ))
        raw: dict[str, Any] = {"namespaces": sources}
        if failures:
            raw["_failures"] = failures
        return characters, raw, status

    def capture_character(
        self, character: CharacterRef,
        save: Callable[[str, str, dict, int], None],
        known_achievement_ids: set[int] | None = None,
        progress: Callable[[str], None] | None = None,
        known_quest_ids: set[int] | None = None,
    ) -> dict[str, dict]:
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
            if progress:
                progress(name.replace("_", " ").title())
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
                if name == "character_profile":
                    if not character.protected_path:
                        outcomes[name] = {
                            "status": "request_failed", "count": None, "detail": str(exc),
                        }
                        break
                    public_error = str(exc)
                    if progress:
                        progress("Authenticated profile fallback")
                    try:
                        protected, status = self.get(
                            character.protected_path, character.protected_namespace
                        )
                        profile = self._normalise_protected_profile(protected, character)
                        save("character_profile", character.protected_path, protected, status)
                        captured[name] = profile
                        outcomes[name] = {
                            "status": "captured",
                            "count": 1,
                            "detail": (
                                "The public profile returned 404; captured through Blizzard's "
                                "authenticated protected-character record."
                            ),
                        }
                        failures["public_character_profile"] = public_error
                    except httpx.HTTPError as protected_exc:
                        protected_error = str(protected_exc)
                        captured[name] = self._basic_account_profile(character)
                        outcomes[name] = {
                            "status": "captured",
                            "count": 1,
                            "detail": (
                                "Basic identity captured from the authenticated account list; "
                                "Blizzard did not return the detailed character profile."
                            ),
                        }
                        outcomes["profile_details"] = {
                            "status": "request_failed",
                            "count": None,
                            "detail": (
                                "Public profile failed: " + public_error +
                                " Protected profile failed: " + protected_error +
                                " Check Game Data and Profile Privacy at "
                                "https://account.blizzard.com/privacy, then log into and out of "
                                "the character before reconnecting."
                            ),
                        }
                        failures["public_character_profile"] = public_error
                        failures["protected_character_profile"] = protected_error
                    continue
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
        if "achievements" in captured:
            reference_outcome = self._capture_achievement_references(
                captured["achievements"], character.namespace, save,
                known_achievement_ids or set(), progress,
            )
            outcomes["achievement_details"] = reference_outcome
        if "quests" in captured:
            outcomes["quest_details"] = self._capture_quest_references(
                captured["quests"], character.namespace, save,
                known_quest_ids or set(), progress,
            )
        if failures:
            captured["_failures"] = failures
        captured["_outcomes"] = outcomes
        return captured

    def _capture_quest_references(
        self, quests: dict[str, Any], profile_namespace: str,
        save: Callable[[str, str, dict, int], None], known_ids: set[int],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        quest_ids = {
            int(item["id"]) for item in quests.get("quests", [])
            if item.get("id") is not None
        }
        cache: dict[int, dict[str, Any]] = getattr(self, "_quest_cache", {})
        self._quest_cache = cache
        details: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        static_namespace = profile_namespace.replace("profile", "static", 1)
        pending_ids = sorted(quest_ids - known_ids)
        rate_limited = False
        for index, quest_id in enumerate(pending_ids, 1):
            if progress and (index == 1 or index % 25 == 0 or index == len(pending_ids)):
                progress(f"Quest reference details {index}/{len(pending_ids)}")
            if quest_id in cache:
                details[str(quest_id)] = cache[quest_id]
                continue
            endpoint = f"/data/wow/quest/{quest_id}"
            try:
                reference, _status = self.get(endpoint, static_namespace)
                cache[quest_id] = reference
                details[str(quest_id)] = reference
            except httpx.HTTPStatusError as exc:
                failed.append(f"{quest_id}: {exc}")
                if exc.response.status_code == 429:
                    rate_limited = True
                    break
            except httpx.HTTPError as exc:
                failed.append(f"{quest_id}: {exc}")
        if details:
            save(
                "quest_details", "/data/wow/quest/{id}",
                {"quests": details}, 200,
            )
            quests["_reference_details"] = details
        reused = len(quest_ids & known_ids)
        detail_parts = []
        if reused:
            detail_parts.append(f"Reused {reused} reference records already in the archive.")
        if failed:
            detail_parts.append(
                f"{len(failed)} reference request(s) failed: " + "; ".join(failed[:3])
            )
        if rate_limited:
            detail_parts.append(
                "Blizzard rate-limited the requests; export again later to resume the missing records."
            )
        captured_count = len(details) + reused
        status = "request_failed" if quest_ids and captured_count == 0 else "captured"
        return {
            "status": status,
            "count": captured_count,
            "detail": " ".join(detail_parts),
        }

    @staticmethod
    def _normalise_protected_profile(
        data: dict[str, Any], character: CharacterRef
    ) -> dict[str, Any]:
        """Make either protected-profile response shape importable as a profile."""
        nested = data.get("character")
        profile = dict(data)
        if isinstance(nested, dict) and nested.get("name"):
            profile.update(nested)
        fallback = BlizzardAPI._basic_account_profile(character)
        for key, value in fallback.items():
            if not profile.get(key):
                profile[key] = value
        return profile

    @staticmethod
    def _basic_account_profile(character: CharacterRef) -> dict[str, Any]:
        profile: dict[str, Any] = {
            "id": character.character_id,
            "name": character.name,
            "level": character.level,
            "realm": {
                "id": character.realm_id,
                "slug": character.realm_slug,
                "name": character.realm_name,
            },
            "character_class": {
                "id": character.playable_class_id,
                "name": character.playable_class,
            },
        }
        if character.playable_race or character.playable_race_id is not None:
            profile["race"] = {
                "id": character.playable_race_id, "name": character.playable_race,
            }
        if character.faction:
            profile["faction"] = {"name": character.faction}
        if character.gender:
            profile["gender"] = {"name": character.gender}
        return profile

    def _capture_achievement_references(
        self, achievements: dict[str, Any], profile_namespace: str,
        save: Callable[[str, str, dict, int], None], known_ids: set[int],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        completed_ids: set[int] = set()
        for item in achievements.get("achievements", []):
            detail = item.get("achievement", item)
            criteria = item.get("criteria", {})
            completed = bool(
                item.get("completed_timestamp") or item.get("is_completed") or
                (criteria.get("is_completed") if isinstance(criteria, dict) else False)
            )
            if completed and detail.get("id") is not None:
                completed_ids.add(int(detail["id"]))

        cache: dict[int, dict[str, Any]] = getattr(self, "_achievement_cache", {})
        self._achievement_cache = cache
        details: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        static_namespace = profile_namespace.replace("profile", "static", 1)
        pending_ids = sorted(completed_ids - known_ids)
        for index, achievement_id in enumerate(pending_ids, 1):
            if progress and (index == 1 or index % 10 == 0 or index == len(pending_ids)):
                progress(f"Achievement reference details {index}/{len(pending_ids)}")
            if achievement_id in cache:
                details[str(achievement_id)] = cache[achievement_id]
                continue
            endpoint = f"/data/wow/achievement/{achievement_id}"
            try:
                reference, _status = self.get(endpoint, static_namespace)
                cache[achievement_id] = reference
                details[str(achievement_id)] = reference
            except httpx.HTTPError as exc:
                failed.append(f"{achievement_id}: {exc}")
        if details:
            save(
                "achievement_details", "/data/wow/achievement/{id}",
                {"achievements": details}, 200,
            )
            achievements["_reference_details"] = details
        reused = len(completed_ids & known_ids)
        detail_parts = []
        if reused:
            detail_parts.append(f"Reused {reused} reference records already in the archive.")
        if failed:
            detail_parts.append(
                f"{len(failed)} reference request(s) failed: " + "; ".join(failed[:3])
            )
        status = "request_failed" if completed_ids and not details and not reused else "captured"
        return {
            "status": status,
            "count": len(completed_ids) - len(failed),
            "detail": " ".join(detail_parts),
        }

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
