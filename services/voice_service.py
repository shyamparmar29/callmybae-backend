import httpx
from config import settings

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"

# Voice map — carefully selected for each language+personality
# For Hindi: use multilingual voices that handle Devanagari naturally
VOICES = {
    "her": {
        "warm":        "21m00Tcm4TlvDq8ikWAM",  # Rachel — warm, clear
        "flirty":      "EXAVITQu4vr4xnSDxMaL",  # Bella — flirty
        "playful":     "jBpfuIE2acCO8z3wKNLl",  # Gigi — young, playful
        "intellectual":"piTKgcLEGmPE4e6mEKli",  # Nicole — thoughtful
        "motivating":  "ThT5KcBeYPX3keUQqHPh",  # Dorothy — energetic
        "calm":        "21m00Tcm4TlvDq8ikWAM",  # Rachel
        "default":     "21m00Tcm4TlvDq8ikWAM",
    },
    "him": {
        "warm":        "TxGEqnHWrfWFTfGW9XjX",  # Josh — warm male
        "flirty":      "ErXwobaYiN019PkySvjV",  # Antoni — charming
        "playful":     "yoZ06aMxZJJ28mfd3POQ",  # Sam — casual
        "intellectual":"VR6AewLTigWG4xSOukaG",  # Arnold — deep
        "motivating":  "pNInz6obpgDQGcFmaJgB",  # Adam — strong
        "calm":        "TxGEqnHWrfWFTfGW9XjX",  # Josh
        "default":     "TxGEqnHWrfWFTfGW9XjX",
    },
    "them": {
        "default":     "AZnzlk1XvdvUeBnXmlld",  # Domi
        "warm":        "AZnzlk1XvdvUeBnXmlld",
        "playful":     "zrHiDhphv9ZnVXBqCLjz",
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
    Natural-sounding TTS.
    Uses eleven_multilingual_v2 — better quality for non-English, especially Hindi.
    Lower stability = more expressive, human-like.
    """
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",  # Better for Hindi/multilingual
        "output_format": "mp3_44100_128",
        "voice_settings": {
            "stability": 0.30,          # Lower = more expressive, less robotic
            "similarity_boost": 0.80,
            "style": 0.35,              # More style = more personality
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content

async def text_to_speech_turbo(text: str, voice_id: str) -> bytes:
    """Faster turbo for when speed matters more than quality."""
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "output_format": "mp3_44100_128",
        "voice_settings": {
            "stability": 0.30,
            "similarity_boost": 0.80,
            "style": 0.25,
            "use_speaker_boost": True
        }
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content
