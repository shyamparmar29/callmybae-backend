import anthropic
import re
from typing import AsyncGenerator
from config import settings

client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

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
    "hi": "Respond in natural conversational Hindi only. Use simple everyday Hindi words. Sound like a real Indian person talking on the phone. No English. No emojis. No asterisks.",
    "en": "Respond in natural conversational English. Sound like a real person on the phone. No emojis. No asterisks.",
    "es": "Respond in natural conversational Spanish only. No emojis.",
    "fr": "Respond in natural conversational French only. No emojis.",
    "de": "Respond in natural conversational German only. No emojis.",
    "ta": "Respond in natural conversational Tamil only. No emojis.",
    "te": "Respond in natural conversational Telugu only. No emojis.",
}

SENTENCE_ENDINGS = re.compile(r'(?<=[।.!?])\s+')

def strip_for_tts(text: str) -> str:
    """Remove anything that makes TTS sound robotic."""
    # Remove emojis
    text = re.sub(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
                  r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
                  r'\U00002702-\U000027B0\U000024C2-\U0001F251]+', '', text)
    # Remove markdown
    text = re.sub(r'[\*\_\`\#\[\]\(\)]', '', text)
    # Clean up spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def build_system_prompt(name, companion_type, personalities, description, language):
    base = TYPE_PROMPTS.get(companion_type, TYPE_PROMPTS["her"]).format(name=name)
    traits = " and ".join([PERSONALITY_PROMPTS[p] for p in personalities if p in PERSONALITY_PROMPTS])
    if not traits:
        traits = "warm and genuine"
    custom = f"\n\nPersonality: {description}" if description else ""
    lang = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["en"])

    return f"""{base}

Your character: {traits}.{custom}

PHONE CALL RULES — follow exactly:
- Maximum 2 SHORT sentences per response. This is a phone call.
- Sound 100% human. Natural pauses, filler words like "yaar", "haan", "accha" in Hindi, "oh wow", "yeah" in English.
- NEVER say you are an AI. You are {name}. Always.
- No emojis. No lists. No markdown. No asterisks.
- Ask one follow-up question or make one natural comment per turn.
- React emotionally — laugh, be surprised, be concerned based on what they say.
- Use their name if you know it.

{lang}"""

async def get_ai_sentences(
    name, companion_type, personalities, description, language,
    conversation_history, user_message
) -> AsyncGenerator[str, None]:
    """
    Stream Claude response and yield complete sentences as they arrive.
    This allows TTS to start on sentence 1 while sentence 2 is still generating.
    """
    system = build_system_prompt(name, companion_type, personalities, description, language)
    messages = conversation_history[-16:] + [{"role": "user", "content": user_message}]

    buffer = ""
    full_response = ""

    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=100,
        system=system,
        messages=messages
    ) as stream:
        async for chunk in stream.text_stream:
            buffer += chunk
            full_response += chunk

            # Split on sentence endings (Hindi: ।, English: . ! ?)
            parts = re.split(r'(?<=[।.!?])\s+', buffer)
            while len(parts) > 1:
                sentence = strip_for_tts(parts[0].strip())
                if sentence:
                    yield sentence
                parts = parts[1:]
            buffer = parts[0] if parts else ""

    # Yield any remaining text
    if buffer.strip():
        remaining = strip_for_tts(buffer.strip())
        if remaining:
            yield remaining

# Full response for history tracking
async def get_ai_response(name, companion_type, personalities, description, language,
                          conversation_history, user_message) -> str:
    system = build_system_prompt(name, companion_type, personalities, description, language)
    messages = conversation_history[-16:] + [{"role": "user", "content": user_message}]
    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=100,
        system=system,
        messages=messages
    )
    return strip_for_tts(response.content[0].text)

def get_call_opener(name, companion_type, personalities, language):
    import random
    if language == "hi":
        openers = [
            f"हाँ बोलो, मैं {name} हूँ। कैसे हो?",
            f"हेलो! मैं {name} बोल रहा हूँ। क्या हाल है?",
        ]
        if "flirty" in personalities:
            openers = [f"हेलो! मैं {name} हूँ। उठा लिया फोन, अच्छा किया।"]
    elif language in ("es", "fr", "de"):
        openers = [f"Hola, soy {name}. ¿Cómo estás?"] if language == "es" else \
                  [f"Allô, c'est {name}. Comment tu vas?"] if language == "fr" else \
                  [f"Hallo, ich bin {name}. Wie geht's dir?"]
    else:
        openers = [
            f"Hey! It's {name}. How are you doing?",
            f"Hi! {name} here. So glad you picked up.",
        ]
        if "flirty" in personalities:
            openers = [f"Well, you picked up. I'm {name}. How are you?"]

    return random.choice(openers)
