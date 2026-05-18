import plivo
import httpx
from config import settings

def get_plivo_client():
    return plivo.RestClient(settings.PLIVO_AUTH_ID, settings.PLIVO_AUTH_TOKEN)

def initiate_outbound_call(to_phone: str, call_session_id: str) -> str:
    """
    Place outbound call from Plivo to user's phone.
    When answered, Plivo fetches XML from our /api/calls/answer webhook.
    Returns plivo call_uuid.
    """
    client = get_plivo_client()
    answer_url = f"{settings.APP_URL}/api/calls/answer/{call_session_id}"
    hangup_url = f"{settings.APP_URL}/api/calls/hangup/{call_session_id}"

    response = client.calls.create(
        from_=settings.PLIVO_PHONE_NUMBER,
        to_=to_phone,
        answer_url=answer_url,
        answer_method="GET",
        hangup_url=hangup_url,
        hangup_method="POST",
        time_limit=settings.FREE_CALL_LIMIT_SECONDS + 30,
    )
    return response["request_uuid"]

def build_answer_xml(call_session_id: str, opener_text: str, voice_id: str) -> str:
    """
    Returns Plivo XML that:
    1. Plays the AI opener via <Speak> or <Play> (we'll use <Speak> for now, replace with ElevenLabs audio URL later)
    2. Opens a WebSocket stream for real-time bidirectional audio
    """
    ws_url = f"wss://{settings.APP_URL.replace('https://', '')}/api/calls/ws/{call_session_id}"

    # For production: generate ElevenLabs audio URL and use <Play> instead of <Speak>
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="Polly.Aditi" language="en-IN">{opener_text}</Speak>
    <Stream streamTimeout="300" keepCallAlive="true" bidirectional="true" audioTrack="inbound" contentType="audio/x-mulaw;rate=8000">
        {ws_url}
    </Stream>
</Response>"""
    return xml

def build_hangup_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="Polly.Aditi">Thank you for calling. Goodbye!</Speak>
    <Hangup/>
</Response>"""
