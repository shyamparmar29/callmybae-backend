"""
Character endpoints:
- GET /characters/                 list all
- GET /characters/{id}             detail
- GET /characters/{id}/relationship  my history with this character
- POST /characters/{id}/call       start a call as this character
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime, timezone
import logging

from database import get_db
from models import User, CallSession, Companion, UserCharacterRelationship
from auth_utils import get_current_user, get_optional_user
from services.character_service import (
    list_characters, get_character, get_or_create_relationship,
    serialize_character, serialize_relationship,
)
from services.plivo_service import initiate_outbound_call
from routers.credits import get_or_create_credits, CREDITS_PER_MINUTE
from routers.profile import get_or_create_profile
from routers.calls import active_calls, audio_counter

logger = logging.getLogger(__name__)
router = APIRouter()


class CharacterCallRequest(BaseModel):
    phone: str | None = None  # optional, defaults to user's profile phone


@router.get("/")
async def get_all_characters(db: AsyncSession = Depends(get_db)):
    """Public list of characters — anyone can browse."""
    chars = await list_characters(db)
    return {"characters": [serialize_character(c) for c in chars]}


@router.get("/{character_id}")
async def get_character_detail(character_id: str, db: AsyncSession = Depends(get_db)):
    char = await get_character(character_id, db)
    if not char:
        raise HTTPException(404, "Character not found")
    return serialize_character(char)


@router.get("/{character_id}/relationship")
async def get_my_relationship(
    character_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """My state with this character — call count, depth, what they're up to."""
    char = await get_character(character_id, db)
    if not char:
        raise HTTPException(404, "Character not found")
    rel = await get_or_create_relationship(user.id, character_id, db)
    await db.flush()
    return serialize_relationship(rel)


@router.post("/{character_id}/call")
async def call_character(
    character_id: str,
    body: CharacterCallRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate a call as a specific character."""
    char = await get_character(character_id, db)
    if not char:
        raise HTTPException(404, "Character not found")

    # Phone: use body or fall back to user's profile phone
    profile = await get_or_create_profile(user, db)
    phone = (body.phone or user.phone or "").replace(" ", "").replace("-", "")
    if not phone:
        raise HTTPException(400, "No phone number — please update your profile")
    if not phone.startswith("+"):
        phone = "+91" + phone

    # Credit check
    credits = await get_or_create_credits(user.id, db)
    if credits.balance < CREDITS_PER_MINUTE:
        raise HTTPException(402, "Insufficient credits. Please top up to continue.")

    # Build the relationship state (lazy create)
    rel = await get_or_create_relationship(user.id, character_id, db)

    # Create a Companion record for this call (we reuse the existing Call infrastructure)
    companion = Companion(
        user_id=user.id,
        name=char.name,
        companion_type=char.gender,
        personalities=char.personalities or [],
        description=char.backstory,
        language=char.language,
        voice_id=char.voice_id,
    )
    db.add(companion)
    await db.flush()

    # Create the call session
    session = CallSession(
        companion_id=companion.id,
        character_id=char.id,
        caller_phone=phone,
        is_free_call=False,
        status="initiated",
    )
    db.add(session)
    await db.flush()

    # Store call state — flagged as character call so calls.py loads character context
    active_calls[session.id] = {
        "companion": {
            "name": char.name,
            "type": char.gender,
            "personalities": char.personalities or [],
            "description": char.backstory,
            "language": char.language,
            "voice_id": char.voice_id,
        },
        "user_id": user.id,
        "user_name": profile.first_name or user.name,
        "memory_bank": profile.memory_bank or {},
        "interaction_style": profile.interaction_style or {},
        "history": [],
        "duration": 0,
        "is_free": False,
        "call_uuid": None,
        "mute_until": 0.0,
        "latest_text": "",
        "latest_ts": 0.0,
        "respond_task": None,
        # Character-specific:
        "is_character_call": True,
        "character_id": char.id,
        "character_data": {
            "name": char.name,
            "age": char.age,
            "location": char.location,
            "occupation": char.occupation,
            "backstory": char.backstory,
            "personality": char.personality,
            "speaking_style": char.speaking_style,
            "gender": char.gender,
            "language": char.language,
        },
        "character_life_state": rel.character_life_state or {},
        "character_memory": rel.conversation_memory or {},
        "relationship_call_count": rel.call_count or 0,
    }
    audio_counter[session.id] = 0

    try:
        plivo_uuid = initiate_outbound_call(phone, session.id)
        session.plivo_call_uuid = plivo_uuid
        active_calls[session.id]["call_uuid"] = plivo_uuid
        session.status = "ringing"
    except Exception as e:
        logger.error(f"Plivo character call failed: {e}")
        raise HTTPException(500, f"Failed to start call: {str(e)}")

    await db.flush()
    return {
        "call_session_id": session.id,
        "character_id": char.id,
        "character_name": char.name,
        "status": session.status,
        "message": f"{char.name} is calling you now!",
    }
