from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from database import create_tables
from routers import auth, companions, calls, payments
from config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield

app = FastAPI(
    title="CallMyBae API",
    version="1.0.0",
    lifespan=lifespan
)

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

@app.get("/")
async def root():
    return {"status": "CallMyBae API running", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
