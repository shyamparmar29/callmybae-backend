from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # App
    APP_URL: str = "https://api.callmybae.com"
    FRONTEND_URL: str = "https://callmybae.com"
    SECRET_KEY: str = "change-this-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # Database (Supabase PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@host:5432/callmybae"

    # Plivo (outbound calls)
    PLIVO_AUTH_ID: str = ""
    PLIVO_AUTH_TOKEN: str = ""
    PLIVO_PHONE_NUMBER: str = ""   # e.g. +911XXXXXXXXXX

    # Deepgram (speech-to-text)
    DEEPGRAM_API_KEY: str = ""

    # Anthropic (Claude Haiku for conversation)
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"

    # ElevenLabs (text-to-speech)
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_MODEL: str = "eleven_turbo_v2_5"

    # Voice IDs by companion type
    VOICE_ID_HER: str = "21m00Tcm4TlvDq8ikWAM"    # Rachel - warm female
    VOICE_ID_HIM: str = "TxGEqnHWrfWFTfGW9XjX"    # Josh - warm male
    VOICE_ID_THEM: str = "AZnzlk1XvdvUeBnXmlld"   # Domi - neutral

    # Razorpay (Indian payments)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # Plans (INR paise = rupees × 100)
    PLAN_SPARK_PRICE: int = 49900      # ₹499
    PLAN_SOULMATE_PRICE: int = 149900  # ₹1499

    # Free call limit (seconds)
    FREE_CALL_LIMIT_SECONDS: int = 300  # 5 minutes

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
