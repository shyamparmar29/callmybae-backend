from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
import httpx

from database import get_db
from models import User
from schemas import RegisterRequest, LoginRequest, TokenResponse
from auth_utils import hash_password, verify_password, create_access_token, get_current_user
from config import settings

router = APIRouter()

# ── REGISTER ──
@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    if not body.email and not body.phone:
        raise HTTPException(400, "Email or phone required")
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
    return TokenResponse(access_token=token, user_id=user.id, name=user.name, plan="free")

# ── LOGIN ──
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
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name, plan="free")

# ── ME ──
@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "plan": "free",
        "avatar_url": user.avatar_url,
    }

# ── GOOGLE OAUTH ──
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

@router.get("/google")
async def google_login():
    """Return Google OAuth URL for frontend to redirect to."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google OAuth not configured")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return {"url": f"{GOOGLE_AUTH_URL}?{query}"}

@router.post("/google/callback")
async def google_callback(body: dict, db: AsyncSession = Depends(get_db)):
    """Exchange Google auth code for JWT. Called by frontend."""
    code = body.get("code")
    if not code:
        raise HTTPException(400, "Missing code")

    # Exchange code for Google tokens
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(400, f"Google token error: {token_resp.text}")
        tokens = token_resp.json()

        # Get user info
        user_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        google_user = user_resp.json()

    google_id = google_user.get("sub")
    email = google_user.get("email")
    name = google_user.get("name")
    avatar = google_user.get("picture")

    # Find or create user
    result = await db.execute(
        select(User).where(or_(User.google_id == google_id, User.email == email))
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            name=name,
            email=email,
            google_id=google_id,
            avatar_url=avatar,
            plan="free"
        )
        db.add(user)
        await db.flush()
    else:
        # Update google info if signing in with Google for first time
        if not user.google_id:
            user.google_id = google_id
        if avatar:
            user.avatar_url = avatar

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user_id=user.id, name=user.name, plan="free")
