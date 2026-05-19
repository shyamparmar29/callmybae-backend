import httpx
from config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# Best voices per language + personality
# Hindi: use multilingual voices that handle Devanagari well
VOICES = {
    "her": {
        "warm":        "21m00Tcm4TlvDq8ikWAM",  # Rachel
        "flirty":      "EXAVITQu4vr4xnSDxMaL",  # Bella
        "playful":     "jBpfuIE2acCO8z3wKNLl",  # Gigi
        "intellectual":"piTKgcLEGmPE4e6mEKli",  # Nicole
        "motivating":  "ThT5KcBeYPX3keUQqHPh",  # Dorothy
        "calm":        "21m00Tcm4TlvDq8ikWAM",  # Rachel
        "default":     "21m00Tcm4TlvDq8ikWAM",  # Rachel
    },
    "him": {
        "warm":        "TxGEqnHWrfWFTfGW9XjX",  # Josh
        "flirty":      "ErXwobaYiN019PkySvjV",  # Antoni
        "playful":     "yoZ06aMxZJJ28mfd3POQ",  # Sam
        "intellectual":"VR6AewLTigWG4xSOukaG",  # Arnold
        "motivating":  "pNInz6obpgDQGcFmaJgB",  # Adam
        "calm":        "TxGEqnHWrfWFTfGW9XjX",  # Josh
        "default":     "TxGEqnHWrfWFTfGW9XjX",  # Josh
    },
    "them": {
        "default":     "AZnzlk1XvdvUeBnXmlld",  # Domi
        "warm":        "AZnzlk1XvdvUeBnXmlld",
        "playful":     "zrHiDhphv9ZnVXBqCLjz",  # Glinda
        "calm":        "AZnzlk1XvdvUeBnXmlld",
    }
}

def select_voice(companion_type: str, personalities: list) -> str:
    type_voices = VOICES.get(companion_type, VOICES["her"])
    for trait in personalities:
        if trait in type_voices:
            return type_voices[trait]
    return type_voices["default"]

def get_voice_for_companion(companion_type: str) -> str:
    return VOICES.get(companion_type, VOICES["her"])["default"]

async def text_to_speech_mp3(text: str, voice_id: str) -> bytes:
    """
    MP3 audio from ElevenLabs using turbo model for lowest latency.
    Used for Plivo REST API play injection.
    """
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",   # Fastest model — 50% lower latency
        "output_format": "mp3_44100_128",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.85,
            "style": 0.1,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

async def text_to_speech_mulaw(text: str, voice_id: str) -> bytes:
    """ulaw_8000 for direct WebSocket streaming."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "output_format": "ulaw_8000",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.85,
            "style": 0.1,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content
