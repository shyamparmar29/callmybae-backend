import httpx
from config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# ElevenLabs voice library — mapped by gender + personality
VOICES = {
    "her": {
        "warm":        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
        "flirty":      {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
        "playful":     {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli"},
        "intellectual":{"id": "piTKgcLEGmPE4e6mEKli", "name": "Nicole"},
        "motivating":  {"id": "ThT5KcBeYPX3keUQqHPh", "name": "Dorothy"},
        "calm":        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
        "default":     {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
    },
    "him": {
        "warm":        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh"},
        "flirty":      {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni"},
        "playful":     {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam"},
        "intellectual":{"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold"},
        "motivating":  {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
        "calm":        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh"},
        "default":     {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh"},
    },
    "them": {
        "default":     {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
        "warm":        {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
        "playful":     {"id": "zrHiDhphv9ZnVXBqCLjz", "name": "Glinda"},
        "calm":        {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
    }
}

def select_voice(companion_type: str, personalities: list) -> str:
    """Pick best ElevenLabs voice ID based on type + dominant personality."""
    type_voices = VOICES.get(companion_type, VOICES["her"])
    for trait in personalities:
        if trait in type_voices:
            return type_voices[trait]["id"]
    return type_voices["default"]["id"]

async def text_to_speech_mulaw(text: str, voice_id: str) -> bytes:
    """Get audio from ElevenLabs in ulaw_8000 — what Plivo WebSocket needs."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": "ulaw_8000",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.2,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

async def text_to_speech(text: str, voice_id: str) -> bytes:
    """MP3 for non-Plivo use."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

def get_voice_for_companion(companion_type: str) -> str:
    return VOICES.get(companion_type, VOICES["her"])["default"]["id"]
