from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models import Companion, User
from schemas import CompanionCreate, CompanionResponse
from auth_utils import get_current_user
from config import settings

router = APIRouter()

def get_voice_id(companion_type: str) -> str:
    mapping = {
        "her": settings.VOICE_ID_HER,
        "him": settings.VOICE_ID_HIM,
        "them": settings.VOICE_ID_THEM,
    }
    return mapping.get(companion_type, settings.VOICE_ID_HER)

@router.post("/", response_model=CompanionResponse)
async def create_companion(
    body: CompanionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    companion = Companion(
        user_id=user.id,
        name=body.name,
        companion_type=body.companion_type,
        personalities=body.personalities,
        description=body.description,
        language=body.language,
        voice_id=get_voice_id(body.companion_type),
    )
    db.add(companion)
    await db.flush()
    return companion

@router.get("/", response_model=list[CompanionResponse])
async def list_companions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    result = await db.execute(select(Companion).where(Companion.user_id == user.id))
    return result.scalars().all()

@router.get("/{companion_id}", response_model=CompanionResponse)
async def get_companion(
    companion_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Companion).where(Companion.id == companion_id, Companion.user_id == user.id)
    )
    companion = result.scalar_one_or_none()
    if not companion:
        raise HTTPException(404, "Companion not found")
    return companion

@router.delete("/{companion_id}")
async def delete_companion(
    companion_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    result = await db.execute(
        select(Companion).where(Companion.id == companion_id, Companion.user_id == user.id)
    )
    companion = result.scalar_one_or_none()
    if not companion:
        raise HTTPException(404, "Companion not found")
    await db.delete(companion)
    return {"deleted": True}
