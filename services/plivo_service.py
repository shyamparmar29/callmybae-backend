import plivo
from config import settings

def get_plivo_client():
    return plivo.RestClient(settings.PLIVO_AUTH_ID, settings.PLIVO_AUTH_TOKEN)

def initiate_outbound_call(to_phone: str, call_session_id: str) -> str:
    """Place outbound call. Recording is started separately after answer."""
    client = get_plivo_client()
    answer_url = f"https://callmybae-backend.onrender.com/api/calls/answer/{call_session_id}"
    hangup_url = f"https://callmybae-backend.onrender.com/api/calls/hangup/{call_session_id}"

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

def start_recording(call_uuid: str, callback_url: str) -> dict:
    """
    Start recording an active call via REST API.
    Called after the call is answered (from the answer webhook).
    callback_url receives the recording URL when call ends.
    """
    client = get_plivo_client()
    try:
        response = client.calls.record(
            call_uuid=call_uuid,
            time_limit=3600,
            file_format="mp3",
            callback_url=callback_url,
            callback_method="POST",
        )
        return response
    except Exception as e:
        return {"error": str(e)}

def build_hangup_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response><Hangup/></Response>"""
