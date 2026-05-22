"""
Real-time streaming pipeline: Claude tokens → ElevenLabs WebSocket → Plivo WebSocket
Target latency: ~600ms time-to-first-audio (competitive with OpenAI Realtime).

Architecture:
  1. Claude streams tokens as they're generated (no waiting for full response)
  2. Tokens are piped to ElevenLabs WebSocket (eleven_flash_v2_5, ulaw_8000)
  3. ElevenLabs streams mulaw audio chunks as they're generated
  4. Audio chunks are forwarded directly to Plivo's bidirectional WebSocket
  5. User hears the first word in ~600ms (vs ~2.3s with REST API approach)
"""
import asyncio
import json
import logging
import re
import websockets
import anthropic
from typing import Callable, Optional
from config import settings

logger = logging.getLogger(__name__)

# Anthropic client with retries
anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)


def _strip_for_tts_token(token: str) -> str:
    """Remove emojis/markdown from a single streaming token."""
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
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[str, float]:
    """
    Stream Claude → ElevenLabs → Plivo in real-time.
    Returns (full_response_text, estimated_play_duration_seconds).
    """
    full_text = ""
    audio_byte_count = 0

    # ElevenLabs WebSocket URL with flash model for lowest latency
    el_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id=eleven_flash_v2_5"
        f"&output_format=ulaw_8000"
        f"&optimize_streaming_latency=4"
        f"&inactivity_timeout=30"
    )

    try:
        async with websockets.connect(el_url, max_size=10 * 1024 * 1024) as el_ws:
            # Initialize ElevenLabs session with voice settings
            await el_ws.send(json.dumps({
                "text": " ",
                "voice_settings": {
                    "stability": 0.35,
                    "similarity_boost": 0.80,
                    "style": 0.40,
                    "use_speaker_boost": True,
                },
                "generation_config": {
                    "chunk_length_schedule": [50, 80, 110, 150],
                },
                "xi_api_key": settings.ELEVENLABS_API_KEY,
            }))

            send_done = asyncio.Event()
            recv_done = asyncio.Event()

            # ── Task A: Stream Claude tokens to ElevenLabs ──
            async def claude_to_elevenlabs():
                nonlocal full_text
                try:
                    # Prompt caching: system prompt cached for 5 mins
                    # Saves ~200ms on subsequent calls in same conversation
                    cached_system = [{
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }]
                    async with anthropic_client.messages.stream(
                        model=settings.CLAUDE_MODEL,
                        max_tokens=100,
                        system=cached_system,
                        messages=messages,
                    ) as stream:
                        async for token in stream.text_stream:
                            if cancel_event and cancel_event.is_set():
                                logger.info("Claude stream cancelled")
                                break
                            full_text += token
                            clean = _strip_for_tts_token(token)
                            if clean:
                                await el_ws.send(json.dumps({"text": clean}))
                    # Flush ElevenLabs (signals end of text)
                    await el_ws.send(json.dumps({"text": ""}))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Claude→EL error: {e}")
                finally:
                    send_done.set()

            # ── Task B: Stream ElevenLabs audio to Plivo ──
            async def elevenlabs_to_plivo():
                nonlocal audio_byte_count
                try:
                    while True:
                        if cancel_event and cancel_event.is_set():
                            logger.info("EL→Plivo cancelled")
                            break
                        try:
                            msg = await asyncio.wait_for(el_ws.recv(), timeout=12.0)
                        except asyncio.TimeoutError:
                            if send_done.is_set():
                                break
                            continue

                        data = json.loads(msg)

                        if data.get("audio"):
                            # ElevenLabs returns base64 mulaw — forward directly to Plivo
                            audio_b64 = data["audio"]
                            # Count bytes for duration estimate
                            import base64 as b64lib
                            try:
                                audio_byte_count += len(b64lib.b64decode(audio_b64))
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
                finally:
                    recv_done.set()

            await asyncio.gather(
                claude_to_elevenlabs(),
                elevenlabs_to_plivo(),
                return_exceptions=True
            )

        # mulaw 8kHz: 1 byte = 1 sample = 1/8000 sec
        duration = audio_byte_count / 8000.0
        return full_text.strip(), duration

    except asyncio.CancelledError:
        logger.info("Streaming pipeline cancelled")
        return full_text.strip(), audio_byte_count / 8000.0
    except Exception as e:
        logger.error(f"Streaming pipeline error: {e}")
        return full_text.strip(), 0.0
