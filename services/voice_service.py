import httpx
import asyncio
from config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

async def text_to_speech(text: str, voice_id: str) -> bytes:
    """Convert text to audio bytes using ElevenLabs."""
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

async def text_to_speech_stream(text: str, voice_id: str):
    """Stream audio chunks from ElevenLabs for lower latency."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}/stream"
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                yield chunk

def get_voice_for_companion(companion_type: str) -> str:
    mapping = {
        "her": settings.VOICE_ID_HER,
        "him": settings.VOICE_ID_HIM,
        "them": settings.VOICE_ID_THEM,
    }
    return mapping.get(companion_type, settings.VOICE_ID_HER)
