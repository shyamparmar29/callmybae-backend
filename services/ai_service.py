import anthropic
import re
import logging
from config import settings
from services.memory_service import build_memory_context, build_personality_evolution_context

logger = logging.getLogger(__name__)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=4)

PERSONALITY_PROMPTS = {
    "warm":        "deeply nurturing and caring, emotionally supportive",
    "playful":     "playful, witty, loves to joke and tease",
    "intellectual":"thoughtful, loves deep meaningful conversation",
    "flirty":      "confidently flirty, bold, electric tension",
    "motivating":  "energetic, encouraging, celebrates every win",
    "calm":        "calm, soothing, peaceful presence",
}

TYPE_PROMPTS = {
    "her":  "You are {name}, a warm emotionally intelligent female companion.",
    "him":  "You are {name}, a warm emotionally intelligent male companion.",
    "them": "You are {name}, a warm emotionally intelligent companion.",
}

LANG_INSTRUCTIONS = {
    "hi": "Respond naturally like a real young Indian person on the phone. Mix Hindi and English the way Indians actually talk (Hinglish). Example: 'Arrey yaar, sun na, sab theek hai na? Kya hua aaj?' Keep it real and warm.",
    "en": "Respond in natural conversational English. Sound like a real person on the phone. Warm and genuine.",
    "es": "Respond in natural conversational Spanish.",
    "fr": "Respond in natural conversational French.",
    "de": "Respond in natural conversational German.",
    "ta": "Respond in natural conversational Tamil.",
    "te": "Respond in natural conversational Telugu.",
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
    base = TYPE_PROMPTS.get(companion_type, TYPE_PROMPTS["her"]).format(name=name)
    traits = " and ".join([PERSONALITY_PROMPTS[p] for p in personalities if p in PERSONALITY_PROMPTS])
    if not traits:
        traits = "warm and genuine"
    custom = f"\n\nPersonality details: {description}" if description else ""
    lang = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["en"])

    # Build memory context
    memory_ctx = ""
    if memory_bank:
        memory_ctx = build_memory_context(memory_bank, user_name)
    
    personality_ctx = ""
    if interaction_style:
        personality_ctx = build_personality_evolution_context(interaction_style)

    user_ref = f"Their name is {user_name}. " if user_name else ""

    return f"""{base}

Your character: {traits}.{custom}

{user_ref}You are on a REAL PHONE CALL. Critical rules:
- 1-2 SHORT sentences maximum. This is a phone call, not an essay.
- Sound 100% human. Natural, warm, genuine.
- NEVER say you are an AI. You are {name}. Always.
- No emojis. No lists. No markdown.
- React emotionally to what they say.
- Use their name occasionally to make it personal.
- If they seem upset, be present and caring first before asking questions.

{lang}

{memory_ctx}

{personality_ctx}

USE MEMORIES NATURALLY: Don't recite facts. If relevant, weave them in naturally like "Oh, how's that startup thing going?" or "Still dealing with that back pain?"
"""

FALLBACKS_HI = [
    "Haan yaar, main sun raha hoon. Bolo kya hua?",
    "Ek second, kuch connectivity issue lag raha hai. Tum kya keh rahe the?",
    "Sorry yaar, ek baar phir bologe? Main poora sun raha hoon.",
]
FALLBACKS_EN = [
    "Hey, I'm here. Tell me more.",
    "Sorry, one sec — say that again?",
    "I'm listening, go on.",
]

async def get_ai_response(name, companion_type, personalities, description, language,
                          conversation_history, user_message,
                          memory_bank=None, interaction_style=None, user_name=None) -> str:
    import random
    system = build_system_prompt(name, companion_type, personalities, description, language,
                                  memory_bank, interaction_style, user_name)
    messages = conversation_history[-16:] + [{"role": "user", "content": user_message}]
    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=180,
            system=system,
            messages=messages
        )
        return strip_for_tts(response.content[0].text)
    except Exception as e:
        logger.error(f"Claude API error (using fallback): {e}")
        fallbacks = FALLBACKS_HI if language == "hi" else FALLBACKS_EN
        return random.choice(fallbacks)

def get_call_opener(name, companion_type, personalities, language, user_name=None, memory_bank=None):
    import random
    
    greeting = user_name.split()[0] if user_name else ""
    
    if language == "hi":
        if greeting:
            openers = [
                f"Haan {greeting}! Main {name} bol rahi hoon. Kaise ho?",
                f"Hey {greeting}! Main {name} hoon. Kya haal hai?",
            ]
        else:
            openers = [
                f"Haan! Main {name} bol rahi hoon. Kaise ho aap?",
                f"Hello! {name} here. Sab theek hai?",
            ]
    else:
        if greeting:
            openers = [
                f"Hey {greeting}! It's {name}. How are you doing?",
                f"Hi {greeting}! {name} here. What's up?",
            ]
        else:
            openers = [
                f"Hey! It's {name}. How are you doing?",
                f"Hi! {name} here. How's your day going?",
            ]

    if "flirty" in personalities:
        if greeting:
            openers = [f"Well, {greeting} actually picked up. I'm {name}. How are you?"]
        else:
            openers = [f"Well, you actually picked up. I'm {name}. How are you?"]

    return random.choice(openers)
