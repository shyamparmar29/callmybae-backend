from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import json, asyncio, base64, logging, traceback, httpx, time

from database import get_db
from models import Companion, CallSession, User
from schemas import InitiateCallRequest, InitiateCallResponse, CallStatusResponse
from auth_utils import get_optional_user
from services.plivo_service import initiate_outbound_call, build_hangup_xml
from services.ai_service import get_ai_response, get_call_opener
from services.voice_service import text_to_speech_mp3, select_voice
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
active_calls: dict[str, dict] = {}
audio_cache: dict[str, bytes] = {}
audio_counter: dict[str, int] = {}

BYPASS_NUMBERS = ["+919601971754", "+918849798063"]


@router.post("/initiate", response_model=InitiateCallResponse)
async def initiate_call(
    body: InitiateCallRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user)
):
    phone = body.phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+91" + phone

    if not user and phone not in BYPASS_NUMBERS:
        result = await db.execute(
            select(CallSession).where(
                CallSession.caller_phone == phone,
                CallSession.is_free_call == True
            )
        )
        if len(result.scalars().all()) >= 1:
            raise HTTPException(403, "Free call already used. Please create an account.")

    voice_id = select_voice(body.companion_type, body.personalities)
    companion = Companion(
        user_id=user.id if user else None,
        name=body.companion_name,
        companion_type=body.companion_type,
        personalities=body.personalities,
        description=body.description,
        language=body.language,
        voice_id=voice_id,
    )
    db.add(companion)
    await db.flush()

    session = CallSession(
        companion_id=companion.id,
        caller_phone=phone,
        is_free_call=(user is None or user.plan == "free"),
        status="initiated"
    )
    db.add(session)
    await db.flush()

    active_calls[session.id] = {
        "companion": {
            "name": companion.name,
            "type": companion.companion_type,
            "personalities": companion.personalities,
            "description": companion.description,
            "language": companion.language,
            "voice_id": voice_id,
        },
        "history": [],
        "duration": 0,
        "is_free": session.is_free_call and phone not in BYPASS_NUMBERS,
        "opener": None,
        "call_uuid": None,
        "mute_until": 0.0,
    }
    audio_counter[session.id] = 0

    try:
        plivo_uuid = initiate_outbound_call(phone, session.id)
        session.plivo_call_uuid = plivo_uuid
        active_calls[session.id]["call_uuid"] = plivo_uuid
        session.status = "ringing"
    except Exception as e:
        logger.error(f"Plivo failed: {e}")
        raise HTTPException(500, f"Plivo call failed: {str(e)}")

    await db.flush()
    return InitiateCallResponse(
        call_session_id=session.id,
        companion_id=companion.id,
        status=session.status,
        message=f"Calling {phone} now!"
    )


@router.get("/audio/{session_id}/{index}")
async def serve_audio(session_id: str, index: int):
    key = f"{session_id}_{index}"
    audio = audio_cache.get(key)
    if not audio:
        raise HTTPException(404, "Audio not found")
    return Response(content=audio, media_type="audio/mpeg")


async def play_on_call(session_id: str, call_uuid: str, text: str,
                       voice_id: str, call_state: dict) -> float:
    """Generate TTS and play via Plivo REST. Returns duration seconds."""
    try:
        audio = await text_to_speech_mp3(text, voice_id)
        idx = audio_counter.get(session_id, 0)
        audio_counter[session_id] = idx + 1
        key = f"{session_id}_{idx}"
        audio_cache[key] = audio
        audio_url = f"https://callmybae-backend.onrender.com/api/calls/audio/{session_id}/{idx}"
        duration = len(audio) / 16000 + 0.5

        # Mute Deepgram for duration so AI doesn't hear itself
        call_state["mute_until"] = time.time() + duration

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"https://api.plivo.com/v1/Account/{settings.PLIVO_AUTH_ID}/Call/{call_uuid}/Play/",
                auth=(settings.PLIVO_AUTH_ID, settings.PLIVO_AUTH_TOKEN),
                json={"urls": audio_url, "length": 300}
            )
            logger.info(f"Play {resp.status_code}")

        return duration
    except Exception as e:
        logger.error(f"play_on_call error: {e}")
        return 0


@router.get("/answer/{session_id}")
async def plivo_answer(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        return PlainTextResponse(build_hangup_xml(), media_type="application/xml")
    session.status = "connected"
    await db.flush()

    call_state = active_calls.get(session_id, {})
    companion = call_state.get("companion", {})
    opener = get_call_opener(
        companion.get("name", "Luna"),
        companion.get("type", "her"),
        companion.get("personalities", []),
        companion.get("language", "en"),
    )
    call_state["opener"] = opener

    ws_url = f"wss://callmybae-backend.onrender.com/api/calls/ws/{session_id}"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Stream streamTimeout="300" keepCallAlive="true" bidirectional="true" audioTrack="inbound" contentType="audio/x-mulaw;rate=8000" maxDuration="300">
        {ws_url}
    </Stream>
</Response>"""
    return PlainTextResponse(xml, media_type="application/xml")


@router.post("/hangup/{session_id}")
async def plivo_hangup(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc)
        call_state = active_calls.pop(session_id, {})
        session.duration_secs = int(call_state.get("duration", 0))
        session.transcript = call_state.get("history", [])
        await db.flush()
    for k in [k for k in audio_cache if k.startswith(session_id)]:
        del audio_cache[k]
    return {"ok": True}


@router.get("/status/{session_id}", response_model=CallStatusResponse)
async def call_status(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Call session not found")
    return CallStatusResponse(
        call_session_id=session.id,
        status=session.status,
        duration_secs=session.duration_secs,
        is_free_call=session.is_free_call,
    )


@router.websocket("/ws/{session_id}")
async def call_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"WS: {session_id}", flush=True)

    call_state = active_calls.get(session_id)
    if not call_state:
        await websocket.close(code=1008)
        return

    companion = call_state["companion"]
    dg_connection = None
    transcript_parts: list[str] = []
    is_processing = False
    ws_open = True

    try:
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        dg_connection = dg_client.listen.asynclive.v("1")
        dg_ready = asyncio.Event()

        async def on_open(self, open_event, **kwargs):
            dg_ready.set()

        async def on_transcript(self, result, **kwargs):
            try:
                if time.time() < call_state.get("mute_until", 0):
                    return  # AI speaking, ignore
                text = result.channel.alternatives[0].transcript.strip()
                if not text or not ws_open:
                    return
                if result.is_final:
                    logger.info(f"HEARD: '{text}'")
                    transcript_parts.append(text)
                    asyncio.create_task(maybe_respond())
            except Exception as e:
                logger.error(f"Transcript error: {e}")

        async def on_error(self, error, **kwargs):
            logger.error(f"Deepgram error: {error}")

        async def on_close(self, **kwargs):
            pass

        dg_connection.on(LiveTranscriptionEvents.Open, on_open)
        dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)
        dg_connection.on(LiveTranscriptionEvents.Close, on_close)

        lang = companion["language"]
        if len(lang) > 5:
            lang = "en"

        await dg_connection.start(LiveOptions(
            model="nova-2",
            language=lang,
            encoding="mulaw",
            sample_rate=8000,
            punctuate=True,
            endpointing=400,
            interim_results=False,
        ))
        try:
            await asyncio.wait_for(dg_ready.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            pass

    except Exception as e:
        logger.error(f"Deepgram setup failed: {e}")
        dg_connection = None

    async def maybe_respond():
        nonlocal is_processing
        if is_processing or not transcript_parts or not ws_open:
            return
        if time.time() < call_state.get("mute_until", 0):
            return
        is_processing = True
        user_text = " ".join(transcript_parts)
        transcript_parts.clear()
        logger.info(f"RESPONDING: '{user_text}'")
        try:
            call_state["history"].append({"role": "user", "content": user_text})
            ai_text = await get_ai_response(
                companion["name"], companion["type"], companion["personalities"],
                companion["description"], companion["language"],
                call_state["history"], user_text
            )
            logger.info(f"AI: '{ai_text}'")
            call_state["history"].append({"role": "assistant", "content": ai_text})

            call_uuid = call_state.get("call_uuid")
            if call_uuid:
                duration = await play_on_call(
                    session_id, call_uuid, ai_text,
                    companion["voice_id"], call_state
                )
                logger.info(f"Playing for {duration:.1f}s")

            if call_state["is_free"] and call_state["duration"] >= settings.FREE_CALL_LIMIT_SECONDS:
                farewell = {
                    "hi": "यार फ्री टाइम खत्म हो गया। अकाउंट बनाओ और फिर बात करते हैं।",
                    "en": "Our free time is up. Create an account and we can talk anytime. Bye!"
                }.get(companion["language"], "Our free time is up. Bye!")
                if call_uuid:
                    await play_on_call(session_id, call_uuid, farewell, companion["voice_id"], call_state)

        except Exception as e:
            logger.error(f"Response error: {e}\n{traceback.format_exc()}")
        finally:
            is_processing = False

    opener_played = False

    try:
        async for raw_msg in websocket.iter_text():
            try:
                msg = json.loads(raw_msg)
                event = msg.get("event", "")

                if event == "start":
                    start_data = msg.get("start", {})
                    plivo_call_id = (
                        start_data.get("callId") or
                        start_data.get("call_uuid") or
                        start_data.get("CallUUID") or
                        call_state.get("call_uuid", "")
                    )
                    if plivo_call_id:
                        call_state["call_uuid"] = plivo_call_id
                    logger.info(f"STREAM START | {call_state.get('call_uuid')}")

                    if not opener_played:
                        opener_played = True
                        opener_text = call_state.get("opener") or \
                            f"Hey, it's {companion['name']}. How are you?"
                        # Mute BEFORE creating task so barge-in doesn't fire during opener
                        opener_est = len(opener_text) * 0.07 + 3.0
                        call_state["mute_until"] = time.time() + opener_est
                        asyncio.create_task(
                            play_on_call(session_id, call_state.get("call_uuid", ""),
                                        opener_text, companion["voice_id"], call_state)
                        )

                elif event == "media":
                    payload = msg.get("media", {}).get("payload", "")
                    if payload and dg_connection:
                        chunk = base64.b64decode(payload)
                        call_state["duration"] += len(chunk) / 8000
                        await dg_connection.send(chunk)

                elif event == "stop":
                    pass  # ignore, Plivo sends this after Play finishes

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Loop error: {e}")

    except WebSocketDisconnect:
        logger.info("Call ended")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        ws_open = False
        if dg_connection:
            try:
                await dg_connection.finish()
            except Exception:
                pass
        logger.info(f"WS closed: {session_id}")
