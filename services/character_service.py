"""
Character service — manage characters and per-user relationships.
Handles loading, life advancement, and memory updates.
"""
import logging
import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from models import Character, UserCharacterRelationship
from services.character_seed import SEED_CHARACTERS

logger = logging.getLogger(__name__)


async def seed_characters_if_needed(db: AsyncSession):
    """Insert characters from seed data if they don't exist yet. Idempotent."""
    try:
        result = await db.execute(select(Character.id))
        existing_ids = {row[0] for row in result.all()}

        for char_data in SEED_CHARACTERS:
            if char_data["id"] in existing_ids:
                continue
            char = Character(**char_data)
            db.add(char)
        await db.flush()
        logger.info(f"Character seed complete. Total characters: {len(SEED_CHARACTERS)}")
    except Exception as e:
        logger.error(f"Character seeding error: {e}")


async def list_characters(db: AsyncSession) -> list[Character]:
    """All active characters, sorted by sort_order."""
    result = await db.execute(
        select(Character)
        .where(Character.is_active == True)
        .order_by(Character.sort_order)
    )
    return list(result.scalars().all())


async def get_character(character_id: str, db: AsyncSession) -> Character | None:
    result = await db.execute(select(Character).where(Character.id == character_id))
    return result.scalar_one_or_none()


async def get_or_create_relationship(
    user_id: str, character_id: str, db: AsyncSession
) -> UserCharacterRelationship:
    """Get user-character relationship, creating if first call."""
    result = await db.execute(
        select(UserCharacterRelationship).where(
            UserCharacterRelationship.user_id == user_id,
            UserCharacterRelationship.character_id == character_id,
        )
    )
    rel = result.scalar_one_or_none()
    if rel:
        return rel

    # First time talking to this character — initialize from character's initial_life_state
    character = await get_character(character_id, db)
    if not character:
        raise ValueError(f"Character {character_id} not found")

    rel = UserCharacterRelationship(
        user_id=user_id,
        character_id=character_id,
        conversation_memory={},
        character_life_state=dict(character.initial_life_state or {}),
        call_count=0,
        total_call_minutes=0,
        relationship_depth=0,
    )
    db.add(rel)
    await db.flush()
    return rel


def serialize_character(char: Character) -> dict:
    """For API responses."""
    return {
        "id": char.id,
        "name": char.name,
        "tagline": char.tagline,
        "avatar_emoji": char.avatar_emoji,
        "age": char.age,
        "location": char.location,
        "occupation": char.occupation,
        "gender": char.gender,
        "language": char.language,
        "personalities": char.personalities or [],
    }


def serialize_relationship(rel: UserCharacterRelationship) -> dict:
    return {
        "character_id": rel.character_id,
        "call_count": rel.call_count,
        "total_call_minutes": rel.total_call_minutes,
        "relationship_depth": rel.relationship_depth,
        "last_call_at": rel.last_call_at.isoformat() if rel.last_call_at else None,
        "current_life_state": rel.character_life_state or {},
    }
