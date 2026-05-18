from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from database import get_db
from models import User
from schemas import RegisterRequest, LoginRequest, TokenResponse
from auth_utils import hash_password, verify_password, create_access_token

router = APIRouter()

@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not body.email and not body.phone:
        raise HTTPException(400, "Email or phone required")

    # Check duplicate
    filters = []
    if body.email:
        filters.append(User.email == body.email)
    if body.phone:
        filters.append(User.phone == body.phone)
    existing = await db.execute(select(User).where(or_(*filters)))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Account already exists with this email or phone")

    user = User(
        name=body.name,
        email=body.email,
        phone=body.phone,
        password_hash=hash_password(body.password),
        plan="free"
    )
    db.add(user)
    await db.flush()

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name, plan=user.plan)

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    if not body.email and not body.phone:
        raise HTTPException(400, "Email or phone required")

    filters = []
    if body.email:
        filters.append(User.email == body.email)
    if body.phone:
        filters.append(User.phone == body.phone)

    result = await db.execute(select(User).where(or_(*filters)))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name, plan=user.plan)

@router.get("/me")
async def me(db: AsyncSession = Depends(get_db)):
    # Protected route example - add auth dependency in production
    return {"message": "Add get_current_user dependency here"}
