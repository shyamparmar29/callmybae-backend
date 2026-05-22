from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import json, asyncio, base64, logging, traceback, httpx, time

from database import get_db
from models import Companion, CallSession, User, UserProfile
from schemas import InitiateCallRequest, InitiateCallResponse, CallStatusResponse
from auth_utils import get_optional_user
from services.plivo_service import initiate_outbound_call, build_hangup_xml, start_recording
from services.ai_service import get_ai_response, get_call_opener, build_character_system_prompt, get_character_opener
from services.voice_service import text_to_speech_mp3, select_voice
from services.memory_service import extract_memories_from_transcript, merge_memories, advance_character_life, extract_user_memory_for_character
from services.streaming_voice import stream_response_to_plivo, stream_text_to_plivo, pick_checkin
from services.ai_service import build_system_prompt
from routers.credits import get_or_create_credits, deduct_credits_for_call, CREDITS_PER_MINUTE
from routers.profile import get_or_create_profile
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

    memory_bank = {}
    interaction_style = {}
    user_name = None
    description = body.description

    if user:
        credits = await get_or_create_credits(user.id, db)
        profile = await get_or_create_profile(user, db)
        if credits.balance < CREDITS_PER_MINUTE and phone not in BYPASS_NUMBERS:
            raise HTTPException(402, "Insufficient credits. Please top up to continue.")
        memory_bank = profile.memory_bank or {}
        interaction_style = profile.interaction_style or {}
        user_name = profile.first_name or user.name
        voice_id = select_voice(
            profile.companion_type or body.companion_type,
            profile.companion_personalities or body.personalities
        )
        companion_name = profile.companion_name or body.companion_name
        companion_type = profile.companion_type or body.companion_type
        personalities = profile.companion_personalities or body.personalities
        language = profile.companion_language or body.language
        description = profile.companion_description or body.description
    else:
        voice_id = select_voice(body.companion_type, body.personalities)
        companion_name = body.companion_name
        companion_type = body.companion_type
        personalities = body.personalities
        language = body.language

    companion = Companion(
        user_id=user.id if user else None,
        name=companion_name, companion_type=companion_type,
        personalities=personalities, description=description,
        language=language, voice_id=voice_id,
    )
    db.add(companion)
    await db.flush()

    session = CallSession(
        companion_id=companion.id, caller_phone=phone,
        is_free_call=(user is None) and phone not in BYPASS_NUMBERS,
        status="initiated"
    )
    db.add(session)
    await db.flush()

    active_calls[session.id] = {
        "companion": {
            "name": companion.name, "type": companion.companion_type,
            "personalities": companion.personalities, "description": companion.description,
            "language": companion.language, "voice_id": voice_id,
        },
        "user_id": user.id if user else None,
        "user_name": user_name,
        "memory_bank": memory_bank,
        "interaction_style": interaction_style,
        "history": [],
        "duration": 0,
        "is_free": session.is_free_call,
        "call_uuid": None,
        "mute_until": 0.0,
        # Latest-intent tracking
        "latest_text": "",
        "latest_ts": 0.0,
        "respond_task": None,
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
        call_session_id=session.id, companion_id=companion.id,
        status=session.status, message=f"Calling {phone} now!"
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
    try:
        audio = await text_to_speech_mp3(text, voice_id)
        idx = audio_counter.get(session_id, 0)
        audio_counter[session_id] = idx + 1
        key = f"{session_id}_{idx}"
        audio_cache[key] = audio
        audio_url = f"https://callmybae-backend.onrender.com/api/calls/audio/{session_id}/{idx}"
        duration = len(audio) / 16000 + 0.5
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

    if session.plivo_call_uuid:
        recording_cb = f"https://callmybae-backend.onrender.com/api/calls/recording/{session_id}"
        asyncio.create_task(asyncio.to_thread(start_recording, session.plivo_call_uuid, recording_cb))

    await db.flush()

    call_state = active_calls.get(session_id, {})
    companion = call_state.get("companion", {})
    if call_state.get("is_character_call"):
        opener = get_character_opener(
            character_data=call_state.get("character_data", {}),
            character_life_state=call_state.get("character_life_state", {}),
            user_name=call_state.get("user_name"),
            relationship_call_count=call_state.get("relationship_call_count", 0),
        )
    else:
        opener = get_call_opener(
            companion.get("name", "Luna"), companion.get("type", "her"),
            companion.get("personalities", []), companion.get("language", "en"),
            user_name=call_state.get("user_name"), memory_bank=call_state.get("memory_bank"),
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
        # Cancel any pending response task
        task = call_state.get("respond_task")
        if task and not task.done():
            task.cancel()
        session.duration_secs = int(call_state.get("duration", 0))
        session.transcript = call_state.get("history", [])

        user_id = call_state.get("user_id")
        if user_id and session.duration_secs > 0:
            try:
                credits_used = await deduct_credits_for_call(user_id, session.duration_secs, session.id, db)
                session.credits_used = credits_used
            except Exception as e:
                logger.error(f"Credit deduction error: {e}")

        if user_id and session.transcript:
            try:
                profile_result = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
                profile = profile_result.scalar_one_or_none()
                if profile:
                    new_memories = await extract_memories_from_transcript(session.transcript)
                    if new_memories:
                        profile.memory_bank = merge_memories(profile.memory_bank or {}, new_memories)
                    profile.total_call_minutes = (profile.total_call_minutes or 0) + session.duration_secs / 60
                    profile.last_call_at = datetime.now(timezone.utc)
                    style = profile.interaction_style or {}
                    style["call_count"] = style.get("call_count", 0) + 1
                    profile.interaction_style = style
            except Exception as e:
                logger.error(f"Memory save error: {e}")

        # ── CHARACTER CALL: Advance character\'s life + update user memory ──
        if user_id and call_state.get("is_character_call") and session.transcript:
            try:
                from models import UserCharacterRelationship, Character
                character_id = call_state.get("character_id")
                character_name = call_state.get("character_data", {}).get("name", "")
                current_life = call_state.get("character_life_state", {})
                current_memory = call_state.get("character_memory", {})

                # 1. Advance character\'s life one step
                new_life = await advance_character_life(character_name, current_life, session.transcript)
                # 2. Extract what user shared with this character
                new_memory = await extract_user_memory_for_character(session.transcript, current_memory)

                # 3. Save to relationship
                rel_result = await db.execute(
                    select(UserCharacterRelationship).where(
                        UserCharacterRelationship.user_id == user_id,
                        UserCharacterRelationship.character_id == character_id,
                    )
                )
                rel = rel_result.scalar_one_or_none()
                if rel:
                    rel.character_life_state = new_life
                    rel.conversation_memory = new_memory
                    rel.call_count = (rel.call_count or 0) + 1
                    rel.total_call_minutes = (rel.total_call_minutes or 0) + session.duration_secs / 60
                    rel.relationship_depth = min(10, (rel.relationship_depth or 0) + 1)
                    rel.last_call_at = datetime.now(timezone.utc)
                logger.info(f"Character {character_name} life advanced + user memory updated")
            except Exception as e:
                logger.error(f"Character post-call update error: {e}")

        await db.flush()
    for k in [k for k in audio_cache if k.startswith(session_id)]:
        del audio_cache[k]
    return {"ok": True}


@router.post("/recording/{session_id}")
async def plivo_recording(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        form = await request.form()
        recording_url = form.get("RecordUrl") or form.get("recording_url", "")
        if recording_url:
            result = await db.execute(select(CallSession).where(CallSession.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.recording_url = recording_url
                await db.flush()
    except Exception as e:
        logger.error(f"Recording webhook error: {e}")
    return {"ok": True}


@router.get("/status/{session_id}", response_model=CallStatusResponse)
async def call_status(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CallSession).where(CallSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Call session not found")
    return CallStatusResponse(
        call_session_id=session.id, status=session.status,
        duration_secs=session.duration_secs, is_free_call=session.is_free_call,
    )


@router.websocket("/ws/{session_id}")
async def call_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    call_state = active_calls.get(session_id)
    if not call_state:
        await websocket.close(code=1008)
        return

    companion = call_state["companion"]
    dg_connection = None
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
                if not ws_open:
                    return
                text = result.channel.alternatives[0].transcript.strip()
                if not text:
                    return
                if not result.is_final:
                    return
                now = time.time()

                # ── ECHO PROTECTION ──
                # If AI is actively speaking, short transcripts are likely echo
                # Long transcripts (>= 3 words) are real barge-in
                mute_until = call_state.get("mute_until", 0)
                if now < mute_until:
                    word_count = len(text.split())
                    if word_count < 3:
                        # Likely echo of AI's own voice — ignore
                        return
                    # Otherwise it's a barge-in, treat as new speech

                # ── LATEST-INTENT-WINS ──
                call_state["latest_text"] = text
                call_state["latest_ts"] = now

                logger.info(f"HEARD: '{text}'")

                # Cancel any in-flight response task + clear mute immediately
                old_task = call_state.get("respond_task")
                if old_task and not old_task.done():
                    old_task.cancel()
                    # CRITICAL: clear mute_until NOW so new task isn't blocked
                    call_state["mute_until"] = 0.0
                    # Also signal cancellation to the streaming pipeline
                    ce = call_state.get("current_cancel_event")
                    if ce:
                        ce.set()
                    logger.info("Cancelled stale response — user interrupted")

                # Schedule response with tiny debounce
                task = asyncio.create_task(_debounced_respond(session_id, call_state, companion, websocket, now))
                call_state["respond_task"] = task

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
            endpointing=150,
            interim_results=False,
        ))
        try:
            await asyncio.wait_for(dg_ready.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            pass

    except Exception as e:
        logger.error(f"Deepgram setup failed: {e}")
        dg_connection = None

    opener_played = False
    call_state["ws_open"] = True
    call_state["last_speech_ts"] = time.time()
    silence_task = asyncio.create_task(_silence_monitor(call_state, websocket, session_id))

    try:
        async for raw_msg in websocket.iter_text():
            try:
                msg = json.loads(raw_msg)
                event = msg.get("event", "")

                if event == "start":
                    start_data = msg.get("start", {})
                    plivo_call_id = (
                        start_data.get("callId") or start_data.get("call_uuid") or
                        start_data.get("CallUUID") or call_state.get("call_uuid", "")
                    )
                    if plivo_call_id:
                        call_state["call_uuid"] = plivo_call_id
                    logger.info(f"STREAM START")

                    if not opener_played:
                        opener_played = True
                        opener_text = call_state.get("opener") or f"Hey, it's {companion['name']}. How are you?"
                        # Stream the opener directly via WebSocket for fast first audio
                        call_state["mute_until"] = time.time() + 8.0
                        async def play_opener():
                            try:
                                from services.streaming_voice import stream_response_to_plivo, stream_text_to_plivo, pick_checkin
                                # We already have the text — fake a 1-token "response"
                                # Easier: use ElevenLabs WS directly for static text
                                import websockets as ws_lib
                                import base64
                                voice_id = companion["voice_id"]
                                el_url = (
                                    f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
                                    f"?model_id=eleven_flash_v2_5&output_format=ulaw_8000"
                                    f"&optimize_streaming_latency=3"
                                )
                                total_bytes = 0
                                async with ws_lib.connect(el_url, max_size=10*1024*1024) as el_ws:
                                    await el_ws.send(json.dumps({
                                        "text": " ",
                                        "voice_settings": {"stability": 0.35, "similarity_boost": 0.8, "style": 0.4, "use_speaker_boost": True},
                                        "xi_api_key": settings.ELEVENLABS_API_KEY,
                                    }))
                                    await el_ws.send(json.dumps({"text": opener_text}))
                                    await el_ws.send(json.dumps({"text": ""}))
                                    while True:
                                        try:
                                            msg = await asyncio.wait_for(el_ws.recv(), timeout=10.0)
                                        except asyncio.TimeoutError:
                                            break
                                        data = json.loads(msg)
                                        if data.get("audio"):
                                            try:
                                                total_bytes += len(base64.b64decode(data["audio"]))
                                            except Exception:
                                                pass
                                            await websocket.send_text(json.dumps({
                                                "event": "playAudio",
                                                "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": data["audio"]}
                                            }))
                                        if data.get("isFinal"):
                                            break
                                duration = total_bytes / 8000.0
                                call_state["mute_until"] = time.time() + duration + 0.5
                            except Exception as e:
                                logger.error(f"Opener stream error: {e}")
                        asyncio.create_task(play_opener())

                elif event == "media":
                    payload = msg.get("media", {}).get("payload", "")
                    if payload and dg_connection:
                        chunk = base64.b64decode(payload)
                        call_state["duration"] += len(chunk) / 8000
                        await dg_connection.send(chunk)

                elif event == "stop":
                    pass

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Loop error: {e}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        ws_open = False
        call_state["ws_open"] = False
        if silence_task and not silence_task.done():
            silence_task.cancel()
        task = call_state.get("respond_task")
        if task and not task.done():
            task.cancel()
        if dg_connection:
            try:
                await dg_connection.finish()
            except Exception:
                pass




async def _silence_monitor(call_state: dict, websocket, session_id: str):
    """
    If user is silent for >7s while we're not speaking and not processing,
    AI checks in like a real person: "Hello? You still there?"
    """
    last_checkin = 0.0
    consecutive_checkins = 0
    try:
        while True:
            await asyncio.sleep(2.5)
            if not call_state.get("ws_open", True):
                break
            now = time.time()
            last_speech = call_state.get("last_speech_ts", now)
            mute_until = call_state.get("mute_until", 0)
            respond_task = call_state.get("respond_task")
            is_processing = respond_task and not respond_task.done()

            silence_duration = now - last_speech
            time_since_checkin = now - last_checkin

            # Conditions for check-in:
            # - User silent >7s
            # - AI not currently speaking
            # - No response in flight
            # - At least 12s since last check-in
            if (silence_duration > 7
                and now > mute_until + 0.5
                and not is_processing
                and time_since_checkin > 12):

                # After 3 check-ins with no response, stop bothering
                if consecutive_checkins >= 3:
                    continue

                lang = call_state.get("companion", {}).get("language", "en")
                voice_id = call_state.get("companion", {}).get("voice_id")
                checkin = pick_checkin(lang)
                logger.info(f"SILENCE CHECK-IN: '{checkin}'")

                call_state["mute_until"] = now + 4.0
                try:
                    duration = await stream_text_to_plivo(checkin, voice_id, websocket)
                    call_state["mute_until"] = time.time() + duration + 0.3
                except Exception as e:
                    logger.error(f"Check-in error: {e}")

                last_checkin = time.time()
                consecutive_checkins += 1
            elif silence_duration < 5:
                # User is active — reset check-in counter
                consecutive_checkins = 0
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Silence monitor error: {e}")

async def _debounced_respond(session_id: str, call_state: dict, companion: dict,
                              websocket, my_ts: float):
    """
    Real-time streaming response.
    Claude tokens → ElevenLabs WebSocket → Plivo WebSocket
    Target latency: ~600ms time-to-first-audio
    """
    try:
        # Tiny debounce — collapses rapid sentence fragments
        await asyncio.sleep(0.15)

        # If newer speech arrived, abort
        if call_state.get("latest_ts") != my_ts:
            return
        if time.time() < call_state.get("mute_until", 0):
            return

        user_text = call_state.get("latest_text", "").strip()
        if not user_text:
            return

        # Lock latest so we don't double-respond
        call_state["latest_text"] = ""
        call_state["latest_ts"] = 0.0

        logger.info(f"RESPONDING (streaming): '{user_text}'")
        call_state["history"].append({"role": "user", "content": user_text})

        # Build system prompt with memory
        system_prompt = build_system_prompt(
            companion["name"], companion["type"], companion["personalities"],
            companion["description"], companion["language"],
            memory_bank=call_state.get("memory_bank"),
            interaction_style=call_state.get("interaction_style"),
            user_name=call_state.get("user_name"),
        )
        # Last 10 messages only — less tokens = faster
        messages = call_state["history"][-10:]

        # Create cancellation event tied to this response
        cancel_event = asyncio.Event()
        call_state["current_cancel_event"] = cancel_event

        # Pre-mute Deepgram (will refine after we know actual duration)
        call_state["mute_until"] = time.time() + 20.0  # generous initial mute

        # ── STREAM THE PIPELINE ──
        full_text, audio_duration = await stream_response_to_plivo(
            voice_id=companion["voice_id"],
            system_prompt=system_prompt,
            messages=messages,
            plivo_ws=websocket,
            cancel_event=cancel_event,
        )

        # Refine mute_until based on actual audio duration
        call_state["mute_until"] = time.time() + audio_duration + 0.5

        if full_text:
            logger.info(f"AI streamed: '{full_text}' ({audio_duration:.1f}s)")
            call_state["history"].append({"role": "assistant", "content": full_text})

    except asyncio.CancelledError:
        logger.info("Streaming response cancelled — user interrupted")
        # Cancel the inner pipeline too
        ce = call_state.get("current_cancel_event")
        if ce:
            ce.set()
        call_state["mute_until"] = 0.0  # allow user speech immediately
    except Exception as e:
        logger.error(f"Streaming response error: {e}\n{traceback.format_exc()}")
        call_state["mute_until"] = 0.0
