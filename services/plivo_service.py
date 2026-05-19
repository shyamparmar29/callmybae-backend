import plivo
from config import settings

def get_plivo_client():
    return plivo.RestClient(settings.PLIVO_AUTH_ID, settings.PLIVO_AUTH_TOKEN)

def initiate_outbound_call(to_phone: str, call_session_id: str) -> str:
    """Place outbound call with recording enabled."""
    client = get_plivo_client()
    answer_url = f"https://callmybae-backend.onrender.com/api/calls/answer/{call_session_id}"
    hangup_url = f"https://callmybae-backend.onrender.com/api/calls/hangup/{call_session_id}"
    record_url = f"https://callmybae-backend.onrender.com/api/calls/recording/{call_session_id}"

    response = client.calls.create(
        from_=settings.PLIVO_PHONE_NUMBER,
        to_=to_phone,
        answer_url=answer_url,
        answer_method="GET",
        hangup_url=hangup_url,
        hangup_method="POST",
        time_limit=settings.FREE_CALL_LIMIT_SECONDS + 30,
        record=True,                  # Enable recording
        record_callback_url=record_url,
        record_callback_method="POST",
    )
    return response["request_uuid"]

def build_hangup_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Response><Hangup/></Response>"""
