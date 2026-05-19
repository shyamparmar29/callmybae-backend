from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    APP_URL: str = "https://callmybae-backend.onrender.com"
    FRONTEND_URL: str = "https://callmybae.com"
    SECRET_KEY: str = "change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 30  # 30 days

    DATABASE_URL: str = ""

    # Plivo
    PLIVO_AUTH_ID: str = ""
    PLIVO_AUTH_TOKEN: str = ""
    PLIVO_PHONE_NUMBER: str = ""
    PLIVO_WHATSAPP_NUMBER: str = ""   # Your Plivo WhatsApp-enabled number

    # AI services
    DEEPGRAM_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_MODEL: str = "eleven_turbo_v2_5"

    # Voice IDs
    VOICE_ID_HER: str = "nPczCjzI2devNBz1zQrb"   # Aria
    VOICE_ID_HIM: str = "TxGEqnHWrfWFTfGW9XjX"   # Josh
    VOICE_ID_THEM: str = "AZnzlk1XvdvUeBnXmlld"  # Domi

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "https://callmybae.com/auth/google/callback"

    # Razorpay
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    # Plans
    PLAN_SPARK_PRICE: int = 49900
    PLAN_SOULMATE_PRICE: int = 149900
    FREE_CALL_LIMIT_SECONDS: int = 300

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()
