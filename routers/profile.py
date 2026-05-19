from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from database import get_db
from models import User, UserProfile, Companion, CallSession
from auth_utils import get_current_user

router = APIRouter()


async def get_or_create_profile(user: User, db: AsyncSession) -> UserProfile:
    result = await db.execute(select(UserProfile).where(UserProfile.user_id == user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(
            user_id=user.id,
            first_name=user.name.split()[0] if user.name else None,
            companion_name="Luna",
            companion_type="her",
            companion_language="hi",
            companion_personalities=["warm"],
            companion_description=None,
            memory_bank={},
            interaction_style={"call_count": 0},
            scheduled_calls=[]
        )
        db.add(profile)
        await db.flush()
    return profile


@router.get("/")
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(user, db)

    calls_result = await db.execute(
        select(CallSession)
        .join(Companion, CallSession.companion_id == Companion.id)
        .where(Companion.user_id == user.id)
        .order_by(CallSession.created_at.desc())
        .limit(20)
    )
    recent_calls = calls_result.scalars().all()

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone": user.phone,
            "avatar_url": user.avatar_url,
            "plan": user.plan,
        },
        "profile": {
            "first_name": profile.first_name,
            "age": profile.age,
            "city": profile.city,
            "occupation": profile.occupation,
            "about": profile.about,
            "interests": profile.interests or [],
            "companion_name": profile.companion_name,
            "companion_type": profile.companion_type,
            "companion_language": profile.companion_language,
            "companion_personalities": profile.companion_personalities or [],
            "companion_description": profile.companion_description,
            "scheduled_calls": profile.scheduled_calls or [],
            "total_call_minutes": round(profile.total_call_minutes or 0, 1),
            "last_call_at": profile.last_call_at.isoformat() if profile.last_call_at else None,
        },
        "memory_preview": _summarize_memory(profile.memory_bank or {}),
        "call_count": len(recent_calls),
        "recent_calls": [
            {
                "duration": f"{c.duration_secs // 60}m {c.duration_secs % 60}s",
                "status": c.status,
                "date": c.created_at.isoformat() if c.created_at else "",
                "recording_url": c.recording_url,
            }
            for c in recent_calls
        ]
    }


@router.put("/update")
async def update_profile(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    profile = await get_or_create_profile(user, db)

    # ── Personal info ──
    if "first_name" in body and body["first_name"]:
        profile.first_name = body["first_name"]
        user.name = body["first_name"]
    if "age" in body:
        profile.age = body.get("age")
    if "city" in body:
        profile.city = body.get("city")
    if "occupation" in body:
        profile.occupation = body.get("occupation")
    if "about" in body:
        profile.about = body.get("about")
    if "interests" in body:
        profile.interests = body.get("interests", [])

    # ── Phone — stored on User model ──
    if "phone" in body and body["phone"]:
        phone = str(body["phone"]).strip().replace(" ", "").replace("-", "")
        if not phone.startswith("+"):
            phone = "+91" + phone
        user.phone = phone

    # ── Companion config ──
    if "companion_name" in body and body["companion_name"]:
        profile.companion_name = body["companion_name"]
    if "companion_type" in body:
        profile.companion_type = body["companion_type"]
    if "companion_language" in body:
        profile.companion_language = body["companion_language"]
    if "companion_personalities" in body:
        profile.companion_personalities = body["companion_personalities"]
    if "companion_description" in body:
        profile.companion_description = body.get("companion_description") or None

    await db.flush()
    return {"success": True}


@router.get("/memory")
async def get_memory(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(user, db)
    memory = profile.memory_bank or {}
    return {
        "memory_bank": memory,
        "summary": _summarize_memory(memory),
        "total_facts": _count_facts(memory),
    }


@router.delete("/memory")
async def clear_memory(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(user, db)
    profile.memory_bank = {}
    profile.interaction_style = {"call_count": 0}
    await db.flush()
    return {"success": True}


@router.get("/scheduled-calls")
async def get_scheduled_calls(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = await get_or_create_profile(user, db)
    return {"scheduled_calls": profile.scheduled_calls or []}


@router.post("/scheduled-calls")
async def add_scheduled_call(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    profile = await get_or_create_profile(user, db)
    scheduled = list(profile.scheduled_calls or [])
    phone = user.phone or body.get("phone", "")
    if not phone:
        raise HTTPException(400, "Add your phone number in Profile before scheduling calls")

    new_call = {
        "id": f"sc_{len(scheduled)+1}_{int(datetime.now().timestamp())}",
        "time": body.get("time", "09:00"),
        "days": body.get("days", ["mon","tue","wed","thu","fri"]),
        "topic": body.get("topic", "general check-in"),
        "enabled": True,
        "phone": phone,
    }
    scheduled.append(new_call)
    profile.scheduled_calls = scheduled
    await db.flush()
    return {"success": True, "scheduled_call": new_call}


@router.delete("/scheduled-calls/{call_id}")
async def delete_scheduled_call(
    call_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    profile = await get_or_create_profile(user, db)
    profile.scheduled_calls = [c for c in (profile.scheduled_calls or []) if c.get("id") != call_id]
    await db.flush()
    return {"success": True}


def _summarize_memory(memory: dict) -> list[str]:
    lines = []
    personal = memory.get("personal", {})
    if personal.get("city"):
        lines.append(f"Lives in {personal['city']}")
    if personal.get("occupation"):
        lines.append(f"Works as {personal['occupation']}")
    if personal.get("age"):
        lines.append(f"Age {personal['age']}")
    for cat in ["family", "interests", "struggles", "goals", "events", "important_people"]:
        for item in (memory.get(cat) or [])[:2]:
            lines.append(item)
    return lines[:12]


def _count_facts(memory: dict) -> int:
    count = 0
    for v in memory.values():
        if isinstance(v, list):
            count += len(v)
        elif isinstance(v, dict):
            count += sum(1 for val in v.values() if val)
        elif v:
            count += 1
    return count
