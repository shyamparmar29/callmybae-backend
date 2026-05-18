# CallMyBae Backend

FastAPI + Plivo + Deepgram + Claude Haiku + ElevenLabs + Razorpay

## Stack
- **FastAPI** - API framework
- **Plivo** - Outbound phone calls (you already have this from Priya)
- **Deepgram nova-2** - Speech-to-text
- **Claude Haiku** - Conversation AI with companion personality
- **ElevenLabs turbo v2.5** - Text-to-speech
- **Supabase** - PostgreSQL database
- **Razorpay** - Indian payments
- **Render** - Hosting

## File Structure
```
callmybae-backend/
├── main.py              # FastAPI app entry
├── config.py            # All env settings
├── database.py          # Async SQLAlchemy
├── models.py            # DB models
├── schemas.py           # Pydantic schemas
├── auth_utils.py        # JWT + password hashing
├── routers/
│   ├── auth.py          # Register / Login
│   ├── companions.py    # Companion CRUD
│   ├── calls.py         # Initiate + WebSocket + Plivo webhooks
│   └── payments.py      # Razorpay
├── services/
│   ├── ai_service.py    # Claude Haiku conversation
│   ├── voice_service.py # ElevenLabs TTS
│   └── plivo_service.py # Plivo call management
├── requirements.txt
├── render.yaml
└── .env.example
```

## Local Setup

```bash
cd callmybae-backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Fill in your API keys in .env

uvicorn main:app --reload
# API running at http://localhost:8000
# Docs at http://localhost:8000/docs
```

## Deploy to Render

1. Push this folder to a GitHub repo (separate from frontend)
2. Go to render.com → New → Web Service → connect repo
3. Render auto-detects render.yaml
4. Add your secret env vars in Render dashboard (DATABASE_URL, all API keys)
5. Deploy → get URL like https://callmybae-api.onrender.com

## Set up Supabase Database

1. Go to supabase.com → New project → name it callmybae
2. Settings → Database → Connection string → Session pooler
3. Copy the URL and add to .env as DATABASE_URL
   (replace [password] with your database password)
4. Tables are auto-created on first startup via create_tables()

## Connect Frontend to Backend

In index.html, find the commented-out fetch call in initiateCall() and replace:
```javascript
const response = await fetch('https://callmybae-api.onrender.com/api/calls/initiate', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    phone: state.phoneNumber,
    companion_name: state.companionName,
    companion_type: state.companionType,
    personalities: state.personalities,
    description: state.description,
    language: document.getElementById('langPref').value,
  })
});
const data = await response.json();
```

## Plivo Webhook Setup

In your Plivo dashboard, the answer_url and hangup_url are set automatically
by the backend when initiating each call. No manual config needed.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/auth/register | Create account |
| POST | /api/auth/login | Login |
| POST | /api/calls/initiate | Start a call (no auth for free) |
| GET | /api/calls/status/{id} | Poll call status |
| GET | /api/calls/answer/{id} | Plivo webhook - call answered |
| POST | /api/calls/hangup/{id} | Plivo webhook - call ended |
| WS | /api/calls/ws/{id} | Real-time audio WebSocket |
| POST | /api/companions/ | Create companion |
| GET | /api/companions/ | List my companions |
| POST | /api/payments/create-order | Razorpay order |
| POST | /api/payments/verify | Verify payment |
| GET | /api/payments/plans | Get plan details |
