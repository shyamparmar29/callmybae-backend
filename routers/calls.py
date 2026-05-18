from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import json, asyncio, base64, logging

from database import get_db
from models import Companion, CallSession, User
from schemas import InitiateCallRequest, InitiateCallResponse, CallStatusResponse
from auth_utils import get_optional_user
from services.plivo_service import initiate_outbound_call, build_answer_xml, build_hangup_xml, get_plivo_client
from services.ai_service import get_ai_response, get_call_opener, stream_ai_response
from services.voice_service import text_to_speech, get_voice_for_companion
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory call state (use Redis in production)
active_calls: dict[str, dict] = {}

# ── INITIATE CALL (called from frontend wizard) ──
@router.post("/initiate", response_model=InitiateCallResponse)
async def initiate_call(
    body: InitiateCallRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user)
):
    # Validate phone
    phone = body.phone.replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+91" + phone  # Default to India

    # If guest (no auth), check they haven't already used their free call
    if not user:
        result = await db.execute(
            select(CallSession).where(
                CallSession.caller_phone == phone,
                CallSession.is_free_call == True
            )
        )
        previous_free = result.scalars().all()
        if len(previous_free) >= 1:
            raise HTTPException(403, "Free call already used. Please create an account to continue.")

    # Create companion (temporary if guest)
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

    # Create call session
    session = CallSession(
        companion_id=companion.id,
        caller_phone=phone,
        is_free_call=(user is None or user.plan == "free"),
        status="initiated"
    )
    db.add(session)
    await db.flush()

    # Store in-memory call state
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
        "is_free": session.is_free_call,
    }

    # Place Plivo call
    try:
        plivo_uuid = initiate_outbound_call(phone, session.id)
        session.plivo_call_uuid = plivo_uuid
        session.status = "ringing"
    except Exception as e:
        logger.error(f"Plivo call failed: {e}")
        session.status = "failed"
        raise HTTPException(500, f"Could not place call: {str(e)}")

    await db.flush()
    return InitiateCallResponse(
        call_session_id=session.id,
        companion_id=companion.id,
        status=session.status,
        message=f"Calling {phone} now! Pick up when your phone rings."
    )

# ── PLIVO ANSWER WEBHOOK (Plivo fetches this when user picks up) ──
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

    xml = build_answer_xml(session_id, opener, companion.get("voice_id", settings.VOICE_ID_HER))
    return PlainTextResponse(xml, media_type="application/xml")

# ── PLIVO HANGUP WEBHOOK ──
@router.post("/hangup/{session_id}")
async def plivo_hangup(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc)
        call_state = active_calls.pop(session_id, {})
        session.duration_secs = call_state.get("duration", 0)
        session.transcript = call_state.get("history", [])
        await db.flush()
    return {"ok": True}

# ── CALL STATUS (polled by frontend) ──
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

# ── WEBSOCKET - Real-time voice conversation ──
@router.websocket("/ws/{session_id}")
async def call_websocket(websocket: WebSocket, session_id: str):
    """
    Plivo connects here after call is answered.
    Flow: Plivo audio → Deepgram STT → Claude Haiku → ElevenLabs TTS → back to Plivo
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for session {session_id}")

    call_state = active_calls.get(session_id)
    if not call_state:
        await websocket.close(code=1008)
        return

    companion = call_state["companion"]
    audio_buffer = bytearray()
    silence_frames = 0
    SILENCE_THRESHOLD = 20  # ~2 seconds of silence triggers processing

    try:
        from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        dg_client = DeepgramClient(settings.DEEPGRAM_API_KEY)
        dg_connection = dg_client.listen.asynclive.v("1")

        transcript_buffer = []

        async def on_transcript(self, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if sentence and result.is_final:
                transcript_buffer.append(sentence)

        dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)

        options = LiveOptions(
            model="nova-2",
            language="hi" if companion["language"] == "hi" else "en-IN",
            punctuate=True,
            endpointing=500,
            interim_results=False,
        )
        await dg_connection.start(options)

        async def process_speech():
            """Called when Deepgram detects end of speech."""
            if not transcript_buffer:
                return
            user_text = " ".join(transcript_buffer)
            transcript_buffer.clear()
            logger.info(f"User said: {user_text}")

            # Add to history
            call_state["history"].append({"role": "user", "content": user_text})

            # Get AI response
            ai_text = await get_ai_response(
                companion["name"],
                companion["type"],
                companion["personalities"],
                companion["description"],
                companion["language"],
                call_state["history"],
                user_text
            )
            logger.info(f"AI response: {ai_text}")
            call_state["history"].append({"role": "assistant", "content": ai_text})

            # Convert to speech and send back to Plivo
            audio_bytes = await text_to_speech(ai_text, companion["voice_id"])
            # Encode audio as base64 for Plivo WebSocket protocol
            audio_b64 = base64.b64encode(audio_bytes).decode()
            await websocket.send_json({"event": "playAudio", "media": {"payload": audio_b64}})

            # Check free call limit
            if call_state["is_free"] and call_state["duration"] >= settings.FREE_CALL_LIMIT_SECONDS:
                farewell = f"I've loved talking to you! Our free time is up but I really want to keep talking. Create an account and we can talk as long as you want. Bye for now!"
                farewell_audio = await text_to_speech(farewell, companion["voice_id"])
                await websocket.send_json({
                    "event": "playAudio",
                    "media": {"payload": base64.b64encode(farewell_audio).decode()}
                })
                await asyncio.sleep(8)
                await websocket.send_json({"event": "hangup"})

        async def receive_audio():
            nonlocal silence_frames
            async for message in websocket.iter_text():
                data = json.loads(message)
                event = data.get("event")

                if event == "media":
                    audio_chunk = base64.b64decode(data["media"]["payload"])
                    await dg_connection.send(audio_chunk)
                    call_state["duration"] += len(audio_chunk) / 8000  # mulaw 8kHz

                elif event == "stop":
                    break

        await receive_audio()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")
    finally:
        try:
            await dg_connection.finish()
        except Exception:
            pass
        logger.info(f"WebSocket closed for session {session_id}")
