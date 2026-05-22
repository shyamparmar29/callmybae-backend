"""
Character endpoints:
- GET /characters/                 list all (public)
- GET /characters/{id}             detail (public)
- GET /characters/{id}/relationship  my history with this character (auth)
- POST /characters/{id}/call       start a call as this character
                                   (auth: full memory; no auth: free trial once per phone)
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
from routers.calls import active_calls, audio_counter, BYPASS_NUMBERS

logger = logging.getLogger(__name__)
router = APIRouter()


class CharacterCallRequest(BaseModel):
    phone: str | None = None


@router.get("/")
async def get_all_characters(db: AsyncSession = Depends(get_db)):
    """Public list of characters."""
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
    user: User | None = Depends(get_optional_user),  # OPTIONAL — allows free trial
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a character call.
    - Logged in: full memory, life progression, uses credits
    - Not logged in: free 5-min trial, one-time per phone, no memory persists
    """
    char = await get_character(character_id, db)
    if not char:
        raise HTTPException(404, "Character not found")

    # Phone resolution
    phone = (body.phone or "").replace(" ", "").replace("-", "")
    if not phone and user and user.phone:
        phone = user.phone.replace(" ", "").replace("-", "")
    if not phone:
        raise HTTPException(400, "Phone number required")
    if not phone.startswith("+"):
        phone = "+91" + phone

    is_free_trial = False
    user_name = None
    char_life_state = dict(char.initial_life_state or {})
    char_memory = {}
    rel_call_count = 0

    if user:
        # ── LOGGED IN: use credits, load relationship for memory ──
        credits = await get_or_create_credits(user.id, db)
        if credits.balance < CREDITS_PER_MINUTE and phone not in BYPASS_NUMBERS:
            raise HTTPException(402, "Insufficient credits. Please top up to continue.")
        profile = await get_or_create_profile(user, db)
        user_name = profile.first_name or user.name
        rel = await get_or_create_relationship(user.id, character_id, db)
        char_life_state = rel.character_life_state or dict(char.initial_life_state or {})
        char_memory = rel.conversation_memory or {}
        rel_call_count = rel.call_count or 0
    else:
        # ── FREE TRIAL: one per phone, no memory persists ──
        prior = await db.execute(
            select(CallSession).where(
                CallSession.caller_phone == phone,
                CallSession.is_free_call == True
            )
        )
        if prior.scalars().first() and phone not in BYPASS_NUMBERS:
            raise HTTPException(
                403,
                "Free trial already used. Sign up to keep talking with full memory!"
            )
        is_free_trial = True

    # Create companion record (used by call infrastructure)
    companion = Companion(
        user_id=user.id if user else None,
        name=char.name,
        companion_type=char.gender,
        personalities=char.personalities or [],
        description=char.backstory,
        language=char.language,
        voice_id=char.voice_id,
    )
    db.add(companion)
    await db.flush()

    session = CallSession(
        companion_id=companion.id,
        character_id=char.id,
        caller_phone=phone,
        is_free_call=is_free_trial,
        status="initiated",
    )
    db.add(session)
    await db.flush()

    active_calls[session.id] = {
        "companion": {
            "name": char.name,
            "type": char.gender,
            "personalities": char.personalities or [],
            "description": char.backstory,
            "language": char.language,
            "voice_id": char.voice_id,
        },
        "user_id": user.id if user else None,
        "user_name": user_name,
        "memory_bank": {},
        "interaction_style": {},
        "history": [],
        "duration": 0,
        "is_free": is_free_trial,
        "call_uuid": None,
        "mute_until": 0.0,
        "latest_text": "",
        "latest_ts": 0.0,
        "respond_task": None,
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
        "character_life_state": char_life_state,
        "character_memory": char_memory,
        "relationship_call_count": rel_call_count,
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
        "is_free_trial": is_free_trial,
        "message": f"{char.name} is calling you now!",
    }
