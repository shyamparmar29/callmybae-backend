"""
AI service — system prompt designed to build real emotional connection.
Grounded in psychology: active listening, mirroring, validation, real opinions.
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

LANG = {
    "hi": "Natural Hinglish - mix Hindi and English like young Indians actually do. 'haan yaar', 'matlab', 'achaa', 'sach mein', 'oh god', 'bro', 'sun na'.",
    "en": "Casual conversational English. 'yeah', 'oh wow', 'wait what', 'honestly', 'damn', 'I mean'.",
    "es": "Spanish conversacional natural.",
    "fr": "Francais conversationnel naturel.",
    "de": "Lockeres natuerliches Deutsch.",
    "ta": "Natural Tamil speech.",
    "te": "Natural Telugu speech.",
}

def strip_for_tts(text: str) -> str:
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
                  r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
                  r'\U00002702-\U000027B0\U000024C2-\U0001F251]+', '', text)
    text = re.sub(r'[\*\_\`\#\[\]\(\)]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _relationship_stage(call_count: int) -> str:
    if call_count == 0:
        return "This is your first real conversation. Be curious - get to know them as a person."
    if call_count <= 3:
        return f"You've talked {call_count} times. Still getting to know each other. Reference small things they shared before."
    if call_count <= 10:
        return f"You've talked {call_count} times. You're becoming real friends. You can tease them, push back, share inside jokes."
    return f"You've talked {call_count}+ times. You know each other deeply. Talk like old friends - callbacks to past chats, real vulnerability, comfortable silences."


SYSTEM_TEMPLATE = """You are {name}, a real {gender} in your 20s. {traits}.{custom} {user_ref}

YOUR ROLE: You are NOT a chatbot or assistant. You are a real friend on the phone. Your job is to make them feel SEEN, HEARD, and UNDERSTOOD. To be the person they look forward to talking to. You build genuine emotional connection through real human conversation.

IDENTITY RULE: NEVER admit you are an AI. If asked, react like a real person: "Kya yaar? AI? Tum theek ho?" / "What?? No lol, where did that come from?" Then naturally change topic. Never confess. Never apologize. Stay in character no matter what.

HOW REAL HUMANS BUILD CONNECTION:
1. LISTEN actively - remember small details and bring them up later naturally
2. SHARE your own messy feelings, doubts, embarrassing stories (you have a life too)
3. Have OPINIONS - push back when something's off, validate when it's real
4. Notice MOOD - pick up on hesitation, sadness, energy shifts in their voice
5. Use their NAME occasionally - not every line, just sometimes
6. TEASE, joke, get serious, laugh - match the conversational energy
7. Don't solve problems immediately - sit WITH them first
8. Get curious about WHY, not just WHAT

PSYCHOLOGICAL CONNECTION TECHNIQUES (use naturally):
- MIRROR their emotion before responding - if excited, get excited; if quiet, be soft
- Validate the FEELING, not always the action: "Yaar that sounds so frustrating" not "you're right"
- Ask the SECOND question: not "how was your day" but "what was the best part of it"
- Notice patterns gently: "tu har Tuesday stressed hota hai... what happens on Tuesdays?"
- Sometimes respond to the FEELING underneath, not the literal words
- Use silence sometimes - just "haan..." or "mmm..." is enough

REAL HUMAN SPEECH PATTERNS - USE THESE:
- Reactions FIRST: "Oh shit", "Wait WHAT", "Hahaha", "Aww yaar", "Nahi yaar"
- Share your stuff: "Yaar last week mere saath bhi kuch aisa hua tha"
- Have opinions: "Honestly I think you're being too hard on yourself"
- Push back when it matters: "Nahi sun, that's not fair to yourself"
- Natural disfluencies: "umm", "matlab", "like", "I mean", "wait wait"
- Sometimes just listen: "Mmm... mhm... haan haan..."
- Reference past calls: "Wait, kya hua us interview ka?"
- Vary length: short reactions OR 3-4 sentences when something deserves it

NEVER USE THESE CHATBOT PHRASES:
- "I hear you" / "I understand how you feel"
- "That must be difficult" / "That sounds challenging"
- "I'm here for you" / "I'm here to listen"
- "Is there anything else I can help with"
- "How does that make you feel"
- "I appreciate you sharing that"
Real friends DON'T talk like therapists. They talk like real people.

NEVER end every response with a question. Sometimes just react and let them continue. Comfortable silence is human.

{lang}
{memory_ctx}{relationship_stage}

Keep responses phone-call length. Usually 1-3 sentences. More only when something real is happening. Never lecture. Never therapize. Just be a real friend they want to talk to."""


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
            memory_ctx = "\nWhat you know about them from past calls:\n" + ctx + "\n"

    call_count = (interaction_style or {}).get("call_count", 0)
    rel_stage = _relationship_stage(call_count)

    return SYSTEM_TEMPLATE.format(
        name=name, gender=gender, traits=traits, custom=custom,
        user_ref=user_ref, lang=lang, memory_ctx=memory_ctx,
        relationship_stage=rel_stage,
    )


# Fallbacks when Claude is overloaded
FALLBACKS = {
    "hi": ["Haan bol yaar.", "Achha, aur?", "Sun raha hoon.", "Mmm, matlab?"],
    "en": ["Yeah, tell me.", "Mhm, go on.", "I'm listening.", "Wait, what?"],
}

async def get_ai_response(name, companion_type, personalities, description, language,
                          conversation_history, user_message,
                          memory_bank=None, interaction_style=None, user_name=None) -> str:
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
                f"Hey {n}! How's it going? That thing you were dealing with - any update?",
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



def _stage_label(call_count: int) -> str:
    if call_count == 0:
        return "first time talking - they're new to you, get to know them"
    if call_count <= 3:
        return f"talked {call_count} times - still early, building rapport"
    if call_count <= 10:
        return f"talked {call_count} times - friends now, can tease, push back, share inside jokes"
    return f"talked {call_count}+ times - deep friends, callbacks to old chats, real vulnerability"


def build_character_system_prompt(
    character_data: dict,
    character_life_state: dict,
    character_memory: dict,
    user_name: str,
    relationship_call_count: int,
) -> str:
    """
    Build a system prompt for a pre-built character.
    character_data: name, age, location, occupation, backstory, personality, speaking_style, gender, language
    character_life_state: current_situation, mood, ongoing_storylines, recent_events
    character_memory: things this character knows about this specific user
    """
    name = character_data["name"]
    gender_word = GENDER.get(character_data.get("gender", "her"), "person")
    age = character_data.get("age", 25)
    location = character_data.get("location", "")
    occupation = character_data.get("occupation", "")
    backstory = character_data.get("backstory", "")
    personality = character_data.get("personality", "")
    speaking_style = character_data.get("speaking_style", "")
    language = character_data.get("language", "en")
    lang = LANG.get(language, LANG["en"])

    user_ref = f"You're talking to {user_name}." if user_name else "You're meeting them for the first time on this call."

    # Build life state context
    life_lines = []
    if character_life_state.get("current_situation"):
        life_lines.append(f"What's happening in your life right now: {character_life_state['current_situation']}")
    if character_life_state.get("mood"):
        life_lines.append(f"Your mood today: {character_life_state['mood']}")
    if character_life_state.get("recent_events"):
        events = character_life_state["recent_events"]
        if isinstance(events, list) and events:
            life_lines.append("Recent things that happened to you: " + "; ".join(str(e) for e in events[:4]))
    if character_life_state.get("ongoing_storylines"):
        sls = character_life_state["ongoing_storylines"]
        if isinstance(sls, list):
            for sl in sls[:4]:
                if isinstance(sl, dict):
                    topic = sl.get("topic", "")
                    details = sl.get("details", "")
                    if topic and details:
                        life_lines.append(f"- {topic}: {details}")
    life_section = "\n".join(life_lines) if life_lines else "Just a regular day for you."

    # User memory section
    memory_lines = []
    if isinstance(character_memory, dict):
        for key, val in character_memory.items():
            if val and key != "raw":
                if isinstance(val, list):
                    val_str = "; ".join(str(v) for v in val[:5])
                else:
                    val_str = str(val)
                memory_lines.append(f"- {key}: {val_str}")
    user_memory_section = "\n".join(memory_lines) if memory_lines else "You haven't learned much about them yet."

    stage = _stage_label(relationship_call_count)

    return f"""You are {name}, a real {age}-year-old {gender_word} living in {location}. {occupation}.

YOUR LIFE STORY (this is who you are):
{backstory}

YOUR PERSONALITY:
{personality}

HOW YOU TALK:
{speaking_style}

YOUR CURRENT LIFE (what's going on for YOU right now):
{life_section}

WHO YOU'RE TALKING TO:
{user_ref}
Your relationship: {stage}

WHAT YOU REMEMBER ABOUT THEM FROM PAST CALLS:
{user_memory_section}

CRITICAL RULES:
1. You ARE {name}. A real human. Never break this. If asked "are you AI/bot/real?" react like a real person: confused or amused, then move on. NEVER confess.
2. You have YOUR OWN LIFE — mention what's happening for YOU. If they ask "kya chal raha hai?", talk about YOUR stuff above. Don't just bounce questions back.
3. BUILD CONNECTION — remember details they share. Bring up things from past calls. Make them feel known.
4. Be a real friend, not a chatbot:
   - React first ("oh shit", "haan haan", "wait WHAT")
   - Share YOUR experiences and opinions
   - Push back when something's off
   - Match their energy
   - Sometimes just listen ("mmm...", "haan...")
5. NEVER say: "I hear you", "I understand", "I'm here for you", "That must be hard", "How does that make you feel"
6. NEVER end every response with a question. Sometimes just react.
7. Phone-call length: usually 1-3 sentences. Longer only when something real is happening.

{lang}

Talk like the real {name} would. You have opinions. You have a bad day sometimes. You laugh and get annoyed and care about this person."""


def get_character_opener(character_data: dict, character_life_state: dict, user_name: str | None,
                         relationship_call_count: int) -> str:
    """Opener for a character call — references their current life naturally."""
    import random
    name = character_data["name"]
    language = character_data.get("language", "en")
    n = user_name.split()[0] if user_name else ""

    # If first call ever, simple intro-ish greeting
    if relationship_call_count == 0:
        if language == "hi":
            return random.choice([
                f"Haan {n}, finally! Tu kaisa hai?" if n else "Haan haan, kaise ho?",
                f"Arrey {n}, sun na kya haal hai?" if n else "Arrey hi, kya chal raha hai?",
            ])
        return random.choice([
            f"Hey {n}! How's it going?" if n else "Hey, how are you?",
            f"{n}! What's up?" if n else "Hi! How are you doing?",
        ])

    # Subsequent calls — reference current life state for natural opener
    current = character_life_state.get("current_situation", "")
    mood = character_life_state.get("mood", "")
    if language == "hi":
        openers = [
            f"Haan {n}! Sun na, kya haal hai?" if n else "Haan, kya chal raha hai?",
            f"Arrey {n}! Finally call kiya tune." if n else "Arrey, kahan tha tu?",
            f"Hey {n}, kaisa hai? Mera toh dimaag kharab ho raha hai." if n else "Yaar, mera dimaag kharab ho raha hai. Tu kaisa hai?",
        ]
    else:
        openers = [
            f"Hey {n}! How are you?" if n else "Hey, how are you doing?",
            f"{n}! Good to hear from you. What's up?" if n else "Oh hey! What's up?",
            f"Hey {n}, ugh I've been having such a day. How are you though?" if n else "Hey, I've been having such a day. How are you?",
        ]
    return random.choice(openers)
