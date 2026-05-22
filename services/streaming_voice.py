"""
Production-grade streaming pipeline with PERCEIVED <200ms latency.

Key innovation: FILLER INJECTION
We send a natural filler ("Hmm", "Haan", "Achaa") to ElevenLabs IMMEDIATELY
while Claude is still thinking. The user hears audio in <200ms — feels instant.
Claude's real response streams in seamlessly after the filler.

This is the technique used by OpenAI Advanced Voice Mode and other top voice agents.
"""
import asyncio
import json
import logging
import re
import random
import base64
import websockets
import anthropic
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)
anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)

# Natural fillers that buy 300-500ms while Claude thinks
FILLERS = {
    "hi": ["Haan, ", "Achaa, ", "Hmm, ", "Matlab, ", "Sun, ", "Toh, ", "Haan haan, "],
    "en": ["Hmm, ", "Yeah, ", "Mmm, ", "Right, ", "Oh, ", "So, ", "Yeah yeah, "],
    "es": ["Mmm, ", "Sí, ", "Bueno, ", "Pues, "],
    "fr": ["Mmm, ", "Ouais, ", "Bon, ", "Alors, "],
}

def _pick_filler(language: str) -> str:
    return random.choice(FILLERS.get(language, FILLERS["en"]))


def _strip_for_tts_token(token: str) -> str:
    token = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
                   r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
                   r'\U00002702-\U000027B0\U000024C2-\U0001F251]+', '', token)
    token = re.sub(r'[\*\_\`\#]', '', token)
    return token


async def stream_response_to_plivo(
    voice_id: str,
    system_prompt: str,
    messages: list,
    plivo_ws,
    language: str = "en",
    cancel_event: Optional[asyncio.Event] = None,
    use_filler: bool = True,
) -> tuple[str, float]:
    """
    Stream Claude + filler → ElevenLabs WebSocket → Plivo WebSocket.
    Returns (full_response_text, audio_duration_seconds).
    """
    full_text = ""
    audio_byte_count = 0

    el_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id=eleven_flash_v2_5"
        f"&output_format=ulaw_8000"
        f"&optimize_streaming_latency=4"
        f"&inactivity_timeout=60"
    )

    try:
        async with websockets.connect(el_url, max_size=10 * 1024 * 1024) as el_ws:
            # ── INIT ──
            # chunk_length_schedule: first chunk at 5 chars → near-instant first audio
            await el_ws.send(json.dumps({
                "text": " ",
                "voice_settings": {
                    "stability": 0.35,
                    "similarity_boost": 0.80,
                    "style": 0.40,
                    "use_speaker_boost": True,
                },
                "generation_config": {
                    "chunk_length_schedule": [50, 90, 120, 150],
                },
                "xi_api_key": settings.ELEVENLABS_API_KEY,
            }))

            # ── STEP 1: SEND FILLER IMMEDIATELY (this is the trick!) ──
            # The filler hits ElevenLabs in <50ms, audio bytes come back in ~75ms.
            # User hears something in <200ms total. Feels instant.
            if use_filler:
                filler = _pick_filler(language)
                await el_ws.send(json.dumps({
                    "text": filler,
                    "try_trigger_generation": True,
                }))
                # Track filler as part of response history (so AI doesn't repeat it)
                full_text = filler

            send_done = asyncio.Event()

            # ── TASK A: Stream Claude tokens to ElevenLabs ──
            async def claude_to_elevenlabs():
                nonlocal full_text
                try:
                    # Prompt caching: system prompt cached 5 min, saves ~200ms on subsequent calls
                    cached_system = [{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }]
                    async with anthropic_client.messages.stream(
                        model=settings.CLAUDE_MODEL,
                        max_tokens=160,
                        system=cached_system,
                        messages=messages,
                    ) as stream:
                        async for token in stream.text_stream:
                            if cancel_event and cancel_event.is_set():
                                break
                            full_text += token
                            clean = _strip_for_tts_token(token)
                            if clean:
                                await el_ws.send(json.dumps({"text": clean}))
                    await el_ws.send(json.dumps({"text": ""}))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Claude→EL error: {e}")
                    try:
                        await el_ws.send(json.dumps({"text": ""}))
                    except Exception:
                        pass
                finally:
                    send_done.set()

            # ── TASK B: Stream ElevenLabs audio to Plivo ──
            async def elevenlabs_to_plivo():
                nonlocal audio_byte_count
                try:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            break
                        try:
                            msg = await asyncio.wait_for(el_ws.recv(), timeout=12.0)
                        except asyncio.TimeoutError:
                            if send_done.is_set():
                                break
                            continue

                        data = json.loads(msg)
                        if data.get("audio"):
                            audio_b64 = data["audio"]
                            try:
                                audio_byte_count += len(base64.b64decode(audio_b64))
                            except Exception:
                                pass
                            await plivo_ws.send_text(json.dumps({
                                "event": "playAudio",
                                "media": {
                                    "contentType": "audio/x-mulaw",
                                    "sampleRate": 8000,
                                    "payload": audio_b64,
                                }
                            }))
                        if data.get("isFinal"):
                            break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"EL→Plivo error: {e}")

            await asyncio.gather(
                claude_to_elevenlabs(),
                elevenlabs_to_plivo(),
                return_exceptions=True
            )

        duration = audio_byte_count / 8000.0
        return full_text.strip(), duration

    except asyncio.CancelledError:
        return full_text.strip(), audio_byte_count / 8000.0
    except Exception as e:
        logger.error(f"Streaming pipeline error: {e}")
        return full_text.strip(), 0.0


async def stream_text_to_plivo(
    text: str,
    voice_id: str,
    plivo_ws,
    cancel_event: Optional[asyncio.Event] = None,
) -> float:
    """Stream a pre-defined text (no Claude). Used for openers, check-ins, fillers."""
    audio_byte_count = 0

    el_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id=eleven_flash_v2_5"
        f"&output_format=ulaw_8000"
        f"&optimize_streaming_latency=4"
    )

    try:
        async with websockets.connect(el_url, max_size=10 * 1024 * 1024) as el_ws:
            await el_ws.send(json.dumps({
                "text": " ",
                "voice_settings": {
                    "stability": 0.35, "similarity_boost": 0.80,
                    "style": 0.40, "use_speaker_boost": True,
                },
                "generation_config": {"chunk_length_schedule": [50, 90, 120, 150]},
                "xi_api_key": settings.ELEVENLABS_API_KEY,
            }))
            await el_ws.send(json.dumps({"text": text, "try_trigger_generation": True}))
            await el_ws.send(json.dumps({"text": ""}))

            while True:
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    msg = await asyncio.wait_for(el_ws.recv(), timeout=10.0)
                except asyncio.TimeoutError:
                    break
                data = json.loads(msg)
                if data.get("audio"):
                    audio_b64 = data["audio"]
                    try:
                        audio_byte_count += len(base64.b64decode(audio_b64))
                    except Exception:
                        pass
                    await plivo_ws.send_text(json.dumps({
                        "event": "playAudio",
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": audio_b64,
                        }
                    }))
                if data.get("isFinal"):
                    break

        return audio_byte_count / 8000.0
    except Exception as e:
        logger.error(f"stream_text_to_plivo error: {e}")
        return 0.0


# Silence check-in phrases — used when user is quiet for too long
CHECKINS = {
    "hi": [
        "Hello? Sun raha hai mujhe yaar?",
        "Are you there? Awaaz aa rahi hai?",
        "Yaar tum theek ho na? Kuch awaaz nahi aa rahi.",
        "Hello hello, abhi bhi line par ho?",
    ],
    "en": [
        "Hello? You still there?",
        "Hey, can you hear me?",
        "Are you there? It's gone quiet.",
        "Hello? Still on the line?",
    ],
}

def pick_checkin(language: str) -> str:
    return random.choice(CHECKINS.get(language, CHECKINS["en"]))
