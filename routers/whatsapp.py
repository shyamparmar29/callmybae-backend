from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx, logging

from database import get_db
from models import Companion, WhatsAppSession, User
from services.ai_service import get_ai_response
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Default companion config for WhatsApp users who haven't set one up
DEFAULT_COMPANION = {
    "name": "Luna",
    "type": "her",
    "personalities": ["warm", "playful"],
    "description": "A warm and caring companion",
    "language": "en",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
}

async def send_whatsapp_message(to: str, text: str):
    """Send WhatsApp message via Plivo API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.plivo.com/v1/Account/{settings.PLIVO_AUTH_ID}/Message/",
                auth=(settings.PLIVO_AUTH_ID, settings.PLIVO_AUTH_TOKEN),
                json={
                    "src": settings.PLIVO_WHATSAPP_NUMBER,
                    "dst": to,
                    "text": text,
                    "type": "whatsapp",
                    "template": None,
                }
            )
            logger.info(f"WA send {resp.status_code}: {to}")
    except Exception as e:
        logger.error(f"WA send error: {e}")

@router.post("/message")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Plivo WhatsApp inbound message webhook."""
    try:
        form = await request.form()
        from_number = form.get("From", "").replace("whatsapp:", "")
        message_text = form.get("Text", "").strip()
        
        if not from_number or not message_text:
            return PlainTextResponse("ok")

        logger.info(f"WA from {from_number}: {message_text}")

        # Find or create WhatsApp session
        result = await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.user_phone == from_number)
        )
        session = result.scalar_one_or_none()

        if not session:
            # New user — create session with default companion
            session = WhatsAppSession(
                user_phone=from_number,
                history=[]
            )
            db.add(session)
            await db.flush()

            # Send welcome message
            await send_whatsapp_message(
                from_number,
                "Hey! I'm Luna, your AI companion on CallMyBae 💕 I'm here to chat, listen, and be your companion. Tell me how you're doing!"
            )
            return PlainTextResponse("ok")

        # Get companion config (use linked companion or default)
        companion_config = DEFAULT_COMPANION
        if session.companion_id:
            comp_result = await db.execute(
                select(Companion).where(Companion.id == session.companion_id)
            )
            comp = comp_result.scalar_one_or_none()
            if comp:
                companion_config = {
                    "name": comp.name,
                    "type": comp.companion_type,
                    "personalities": comp.personalities or [],
                    "description": comp.description,
                    "language": comp.language,
                    "voice_id": comp.voice_id,
                }

        # Detect language from message
        lang = companion_config["language"]
        if any('\u0900' <= c <= '\u097F' for c in message_text):
            lang = "hi"

        # Build conversation history
        history = session.history or []

        # Get AI response
        ai_reply = await get_ai_response(
            companion_config["name"],
            companion_config["type"],
            companion_config["personalities"],
            companion_config["description"],
            lang,
            history[-20:],
            message_text
        )

        # Update history
        history.append({"role": "user", "content": message_text})
        history.append({"role": "assistant", "content": ai_reply})
        session.history = history[-40:]  # Keep last 40 messages
        await db.flush()

        # Send reply
        await send_whatsapp_message(from_number, ai_reply)

    except Exception as e:
        logger.error(f"WA webhook error: {e}")

    return PlainTextResponse("ok")

@router.get("/message")
async def whatsapp_verify(request: Request):
    """Plivo webhook verification."""
    return PlainTextResponse("ok")
