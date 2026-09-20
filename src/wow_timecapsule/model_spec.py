from __future__ import annotations

from typing import Any

from .api import CharacterRef


def character_export_spec(character: CharacterRef, captured: dict[str, dict]) -> dict[str, Any]:
    """Translate preserved API data into the stable bridge character description."""
    profile = captured["character_profile"]
    equipment = captured.get("equipment", {}).get("equipped_items", [])
    return {
        "schema": "wow-timecapsule-character/v1",
        "identity": {"region": character.region, "realm_id": character.realm_id,
                     "realm_slug": character.realm_slug, "character_id": character.character_id,
                     "name": character.name},
        "race_id": profile.get("race", {}).get("id"),
        "class_id": profile.get("character_class", {}).get("id"),
        "gender": profile.get("gender", {}).get("type"),
        "body_type": profile.get("body_type"),
        "appearance": captured.get("appearance", {}),
        "equipment": [{
            "slot": item.get("slot", {}).get("type"), "item_id": item.get("item", {}).get("id"),
            "item_level": item.get("level", {}).get("value"),
            "appearance_id": item.get("media", {}).get("id") or item.get("appearance", {}).get("id"),
            "raw": item,
        } for item in equipment],
    }


def default_pet(captured: dict[str, dict]) -> dict | None:
    pets = captured.get("pets", {}).get("pets", [])
    usable = [pet for pet in pets if pet_display_id(pet)]
    return next((pet for pet in usable if pet.get("is_favorite")), usable[0] if usable else None)


def pet_display_id(pet: dict) -> int | None:
    return pet.get("display", {}).get("id") or pet.get("creature_display", {}).get("id")
