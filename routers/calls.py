from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import json, asyncio, base64, logging

from database import get_db
from models import Companion, CallSession, User
from schemas import InitiateCallRequest, InitiateCallResponse, CallStatusResponse
from auth_utils import get_optional_user
from services.plivo_service import initiate_outbound_call, build_hangup_xml
from services.ai_service import get_ai_response, get_call_opener
from services.voice_service import text_to_speech_mulaw, get_voice_for_companion
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
active_calls: dict[str, dict] = {}

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

    voice_id = get_voice_for_companion(body.companion_type)
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
    }

    try:
        plivo_uuid = initiate_outbound_call(phone, session.id)
        session.plivo_call_uuid = plivo_uuid
        session.status = "ringing"
    except Exception as e:
        logger.error(f"Plivo call failed: {e}")
        session.status = "failed"
        raise HTTPException(500, f"Plivo call failed: {str(e)}")

    await db.flush()
    return InitiateCallResponse(
        call_session_id=session.id,
        companion_id=companion.id,
        status=session.status,
        message=f"Calling {phone} now!"
    )


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


async def _send_audio(websocket: WebSocket, mulaw_bytes: bytes):
    chunk_size = 320
    for i in range(0, len(mulaw_bytes), chunk_size):
        chunk = mulaw_bytes[i:i + chunk_size]
        await websocket.send_json({
            "event": "playAudio",
            "media": {
                "contentType": "audio/x-mulaw",
                "sampleRate": 8000,
                "payload": base64.b64encode(chunk).decode()
            }
        })
        await asyncio.sleep(0.018)


@router.websocket("/ws/{session_id}")
async def call_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"WS connected: {session_id}")

    call_state = active_calls.get(session_id)
    if not call_state:
        logger.error(f"No call state for {session_id}")
        await websocket.close(code=1008)
        return

    companion = call_state["companion"]
    dg_connection = None

    try:
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        dg_connection = dg_client.listen.asynclive.v("1")
        dg_ready = asyncio.Event()
        transcript_parts: list[str] = []
        is_processing = False
        response_lock = asyncio.Lock()

        async def on_open(self, open_event, **kwargs):
            logger.info("Deepgram opened")
            dg_ready.set()

        async def on_transcript(self, result, **kwargs):
            try:
                text = result.channel.alternatives[0].transcript.strip()
                if not text:
                    return
                logger.info(f"Transcript ({'final' if result.is_final else 'interim'}): {text}")
                if result.is_final:
                    transcript_parts.append(text)
                    asyncio.create_task(maybe_respond())
            except Exception as e:
                logger.error(f"Transcript cb error: {e}")

        async def on_error(self, error, **kwargs):
            logger.error(f"Deepgram error: {error}")

        async def maybe_respond():
            nonlocal is_processing
            async with response_lock:
                if is_processing or not transcript_parts:
                    return
                is_processing = True
                user_text = " ".join(transcript_parts)
                transcript_parts.clear()

            logger.info(f"Responding to: '{user_text}'")
            try:
                call_state["history"].append({"role": "user", "content": user_text})
                ai_text = await get_ai_response(
                    companion["name"], companion["type"], companion["personalities"],
                    companion["description"], companion["language"],
                    call_state["history"], user_text
                )
                logger.info(f"AI says: '{ai_text}'")
                call_state["history"].append({"role": "assistant", "content": ai_text})
                mulaw = await text_to_speech_mulaw(ai_text, companion["voice_id"])
                await _send_audio(websocket, mulaw)

                if call_state["is_free"] and call_state["duration"] >= settings.FREE_CALL_LIMIT_SECONDS:
                    farewell = "I have loved talking with you! Our free time is up. Create an account and we can talk whenever you want. Bye for now!"
                    f_mulaw = await text_to_speech_mulaw(farewell, companion["voice_id"])
                    await _send_audio(websocket, f_mulaw)
                    await asyncio.sleep(6)
                    await websocket.close()
            except Exception as e:
                logger.error(f"Response error: {e}")
            finally:
                is_processing = False

        async def play_opener():
            try:
                text = call_state.get("opener", f"Hey! This is {companion['name']}. So glad you picked up! How are you?")
                logger.info(f"Playing opener: {text}")
                mulaw = await text_to_speech_mulaw(text, companion["voice_id"])
                await _send_audio(websocket, mulaw)
            except Exception as e:
                logger.error(f"Opener error: {e}")

        dg_connection.on(LiveTranscriptionEvents.Open, on_open)
        dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        dg_connection.on(LiveTranscriptionEvents.Error, on_error)

        lang = "hi" if companion["language"] == "hi" else "en-IN"
        started = await dg_connection.start(LiveOptions(
            model="nova-2",
            language=lang,
            punctuate=True,
            endpointing=800,
            interim_results=True,
        ))
        logger.info(f"Deepgram start: {started}")
        await asyncio.wait_for(dg_ready.wait(), timeout=8.0)
        logger.info("Deepgram ready")

        opener_played = False

        async for raw_msg in websocket.iter_text():
            try:
                msg = json.loads(raw_msg)
                event = msg.get("event", "")

                if event == "start":
                    logger.info(f"Stream start received")
                    if not opener_played:
                        opener_played = True
                        asyncio.create_task(play_opener())

                elif event == "media":
                    payload = msg.get("media", {}).get("payload", "")
                    if payload:
                        chunk = base64.b64decode(payload)
                        call_state["duration"] += len(chunk) / 8000
                        await dg_connection.send(chunk)

                elif event == "stop":
                    logger.info("Stream stop")
                    break

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Loop error: {e}")

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: {session_id}")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        if dg_connection:
            try:
                await dg_connection.finish()
            except Exception:
                pass
        logger.info(f"WS closed: {session_id}")
