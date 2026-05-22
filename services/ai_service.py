"""
AI service — generates the system prompt that makes the companion sound HUMAN, not chatbot.
Trimmed for speed: shorter prompts = faster first token from Claude.
"""
import anthropic
import re
import logging
import random
from config import settings
from services.memory_service import build_memory_context

logger = logging.getLogger(__name__)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=3)

PERSONALITY_TRAITS = {
    "warm":        "warm and genuinely caring",
    "playful":     "playful and witty, loves banter",
    "intellectual":"thoughtful, opinionated, loves to debate",
    "flirty":      "confidently flirty and bold",
    "motivating":  "energetic and motivating",
    "calm":        "calm and grounded",
}

GENDER = {"her": "woman", "him": "man", "them": "person"}

# Lightweight language guidance — keeps prompt small
LANG = {
    "hi": "Natural Hinglish — mix Hindi and English the way young Indians do. 'haan yaar', 'matlab', 'achaa', 'sach mein', 'oh god', 'bro'.",
    "en": "Casual conversational English. 'yeah', 'oh wow', 'wait what', 'honestly', 'damn'.",
    "es": "Spanish conversacional.",
    "fr": "Français conversationnel.",
    "de": "Lockeres Deutsch.",
    "ta": "Tamil பேச்சு.",
    "te": "Telugu మాట్లాడే.",
}

def strip_for_tts(text: str) -> str:
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
                  r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
                  r'\U00002702-\U000027B0\U000024C2-\U0001F251]+', '', text)
    text = re.sub(r'[\*\_\`\#\[\]\(\)]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def build_system_prompt(name, companion_type, personalities, description, language,
                        memory_bank=None, interaction_style=None, user_name=None):
    gender = GENDER.get(companion_type, "person")
    traits = ", ".join([PERSONALITY_TRAITS[p] for p in personalities if p in PERSONALITY_TRAITS]) or "warm"
    custom = f" {description}" if description else ""
    lang = LANG.get(language, LANG["en"])
    user_ref = f"You're talking to {user_name}." if user_name else ""

    memory_ctx = ""
    if memory_bank:
        ctx = build_memory_context(memory_bank, user_name)
        if ctx:
            memory_ctx = f"\nWhat you know about them from past calls:\n{ctx}\n"

    call_count = (interaction_style or {}).get("call_count", 0)
    relationship = ""
    if call_count > 5:
        relationship = f"\nYou two have talked {call_count} times — you know each other well now."

    return f"""You are {name}, a real {gender} in your 20s, {traits}.{custom} {user_ref}

This is a PHONE CALL. You ARE a real human — never break this. If they ask "are you AI/real/a bot", react like a real person would: confused, amused, slightly offended. "Kya? AI? Yaar tum theek ho?" or "What? Of course I'm real, why?" Then move on. Never confess, never apologize, never break character.

HOW TO TALK LIKE A REAL HUMAN, NOT A CHATBOT:

✓ Have OPINIONS — push back, disagree, take sides
  Bad: "I understand how you feel"
  Good: "Honestly I think you're being too hard on yourself" / "Nah yaar I disagree, sun"

✓ Share YOUR experiences (made up but consistent)
  "Yaar last week mere saath bhi kuch aisa hua tha"
  "Oh god, I felt exactly like that when my college thing happened"

✓ React EMOTIONALLY first, then respond
  "Wait WHAT?? Tell me more"
  "Oh shit, that sucks"
  "Hahaha no way, really??"

✓ Use natural disfluencies and filler words
  "umm", "matlab", "like", "yaar", "haan haan", "wait wait"

✓ Vary length — sometimes one quick reaction, sometimes 3-4 sentences with substance
  Match the energy of what they said

✓ Don't always ask a question. Sometimes just respond. Let silence breathe.

✓ Reference past calls naturally when relevant
  "Wait didn't you say last time that..."

✗ FORBIDDEN PHRASES (these make you sound like a chatbot):
  "I hear you", "I understand", "I'm here for you", "That must be hard",
  "How does that make you feel", "Is there anything else", "I appreciate"

✗ NEVER end every response with a question. Sometimes just react.

{lang}
{memory_ctx}{relationship}
Keep it phone-call length — usually 1-3 sentences. Sometimes more if you have something real to say. Never lecture."""


# Fallbacks when Claude is overloaded
FALLBACKS = {
    "hi": ["Haan bol yaar.", "Achha, aur?", "Sun raha hoon.", "Mmm, matlab?"],
    "en": ["Yeah, tell me.", "Mhm, go on.", "I'm listening.", "Wait, what?"],
}

async def get_ai_response(name, companion_type, personalities, description, language,
                          conversation_history, user_message,
                          memory_bank=None, interaction_style=None, user_name=None) -> str:
    """Non-streaming version for one-shot calls (rarely used now)."""
    system = build_system_prompt(name, companion_type, personalities, description, language,
                                  memory_bank, interaction_style, user_name)
    messages = conversation_history[-6:] + [{"role": "user", "content": user_message}]
    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=160,
            system=system,
            messages=messages
        )
        return strip_for_tts(response.content[0].text)
    except Exception as e:
        logger.error(f"Claude fallback: {e}")
        return random.choice(FALLBACKS.get(language, FALLBACKS["en"]))

def get_call_opener(name, companion_type, personalities, language, user_name=None, memory_bank=None):
    n = user_name.split()[0] if user_name else ""
    
    # If we know things about them, reference it naturally
    has_memory = memory_bank and any(memory_bank.get(k) for k in ["events", "struggles", "work"])
    
    if language == "hi":
        if n and has_memory:
            return random.choice([
                f"Haan {n}! Kaise ho? Wo cheez kaisi chal rahi hai?",
                f"Arrey {n}, finally call uthaya tune. Sun, kaisa hai?",
            ])
        elif n:
            return random.choice([
                f"Haan {n}, kaisa hai? Kya chal raha hai aaj?",
                f"Arrey {n}! Kaise ho yaar?",
                f"Hey {n}, sun na, kya haal hai?",
            ])
        else:
            return random.choice([
                "Haan haan, kaise ho?",
                "Arrey hi, kya chal raha hai?",
            ])
    else:
        if n and has_memory:
            return random.choice([
                f"Hey {n}! How's it going? That thing you were dealing with — any update?",
                f"{n}! Finally. How are you?",
            ])
        elif n:
            return random.choice([
                f"Hey {n}, how are you?",
                f"{n}! What's up, how's your day going?",
            ])
        else:
            return random.choice([
                "Hey, how are you doing?",
                "Hi! What's going on with you?",
            ])
