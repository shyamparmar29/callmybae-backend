import httpx
from config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

async def text_to_speech_mulaw(text: str, voice_id: str) -> bytes:
    """
    Get audio from ElevenLabs in ulaw_8000 format — 
    exactly what Plivo WebSocket expects. No conversion needed.
    """
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/basic"  # audio/basic = mulaw 8kHz
    }
    payload = {
        "text": text,
        "model_id": settings.ELEVENLABS_MODEL,
        "output_format": "ulaw_8000",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

async def text_to_speech(text: str, voice_id: str) -> bytes:
    """MP3 version for non-Plivo use."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": settings.ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

def get_voice_for_companion(companion_type: str) -> str:
    mapping = {
        "her":  settings.VOICE_ID_HER,
        "him":  settings.VOICE_ID_HIM,
        "them": settings.VOICE_ID_THEM,
    }
    return mapping.get(companion_type, settings.VOICE_ID_HER)
