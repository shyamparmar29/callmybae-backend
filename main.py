from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from database import create_tables, AsyncSessionLocal
from routers import auth, companions, calls, payments, whatsapp, admin, profile, credits, characters
from services.character_service import seed_characters_if_needed
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    # Seed characters on startup
    try:
        async with AsyncSessionLocal() as db:
            await seed_characters_if_needed(db)
            await db.commit()
    except Exception as e:
        logging.error(f"Character seed on startup failed: {e}")
    yield


app = FastAPI(title="CallMyBae API", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://callmybae.com", "https://www.callmybae.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,       prefix="/api/auth",       tags=["auth"])
app.include_router(companions.router, prefix="/api/companions",  tags=["companions"])
app.include_router(calls.router,      prefix="/api/calls",       tags=["calls"])
app.include_router(payments.router,   prefix="/api/payments",    tags=["payments"])
app.include_router(whatsapp.router,   prefix="/api/whatsapp",    tags=["whatsapp"])
app.include_router(admin.router,      prefix="/api/admin",       tags=["admin"])
app.include_router(profile.router,    prefix="/api/profile",     tags=["profile"])
app.include_router(credits.router,    prefix="/api/credits",     tags=["credits"])
app.include_router(characters.router, prefix="/api/characters",  tags=["characters"])


@app.get("/")
async def root():
    return {"status": "CallMyBae API v2.1", "version": "2.1.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}
