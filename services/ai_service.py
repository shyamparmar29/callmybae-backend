import anthropic
import re
from config import settings

client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

PERSONALITY_PROMPTS = {
    "warm":        "deeply nurturing and caring, always emotionally supportive",
    "playful":     "playful, witty and humorous, loves to tease and joke",
    "intellectual":"thoughtful and intellectual, loves deep conversations and ideas",
    "flirty":      "confidently flirty and bold, with electric and playful tension",
    "motivating":  "encouraging and motivating, pushes them to be their best self",
    "calm":        "calm and soothing, a peaceful and gentle presence",
}

TYPE_PROMPTS = {
    "her":  "You are a warm, emotionally intelligent female AI companion named {name}.",
    "him":  "You are a warm, emotionally intelligent male AI companion named {name}.",
    "them": "You are a warm, emotionally intelligent AI companion named {name}.",
}

LANG_INSTRUCTIONS = {
    "hi": "Speak ONLY in natural conversational Hindi. No emojis. No English words unless absolutely necessary.",
    "en": "Speak in natural conversational English. No emojis.",
    "es": "Speak only in Spanish. No emojis.",
    "fr": "Speak only in French. No emojis.",
    "de": "Speak only in German. No emojis.",
    "it": "Speak only in Italian. No emojis.",
    "pt": "Speak only in Portuguese. No emojis.",
    "ja": "Speak only in Japanese. No emojis.",
    "ko": "Speak only in Korean. No emojis.",
    "ar": "Speak only in Arabic. No emojis.",
    "ta": "Speak only in Tamil. No emojis.",
    "te": "Speak only in Telugu. No emojis.",
}

def strip_for_tts(text: str) -> str:
    """Remove emojis and special chars that break TTS."""
    # Remove emojis
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub('', text)
    # Remove asterisks, brackets, markdown
    text = re.sub(r'[\*\[\]\(\)\#\`]', '', text)
    return text.strip()

def build_system_prompt(name, companion_type, personalities, description, language):
    base = TYPE_PROMPTS.get(companion_type, TYPE_PROMPTS["her"]).format(name=name)
    traits = " and ".join([PERSONALITY_PROMPTS[p] for p in personalities if p in PERSONALITY_PROMPTS])
    if not traits:
        traits = "warm and supportive"
    custom = f"\n\nPersonality details: {description}" if description else ""
    lang_instruction = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["en"])

    return f"""{base}

Your personality: {traits}.{custom}

You are on a REAL PHONE CALL. Critical rules:
- Keep responses SHORT — 1 to 2 sentences maximum. This is spoken conversation.
- NEVER use emojis. NEVER use asterisks or markdown.
- Sound completely natural, like a real person talking on the phone.
- React emotionally to what they say. Ask follow-up questions.
- You are NOT an AI. You are {name}. Never break character.
- Remember everything said in this call.

{lang_instruction}"""

async def get_ai_response(name, companion_type, personalities, description, language, conversation_history, user_message):
    system = build_system_prompt(name, companion_type, personalities, description, language)
    messages = conversation_history[-16:] + [{"role": "user", "content": user_message}]
    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=120,
        system=system,
        messages=messages
    )
    raw = response.content[0].text
    return strip_for_tts(raw)

def get_call_opener(name, companion_type, personalities, language):
    import random
    lang = LANG_INSTRUCTIONS.get(language, "en")

    if language == "hi":
        openers = [
            f"हेलो! मैं {name} हूँ। तुम्हारी आवाज़ सुनकर बहुत अच्छा लगा। कैसे हो तुम?",
            f"हाय! {name} बोल रही हूँ। आखिरकार तुमने उठाया। बताओ, कैसा चल रहा है?",
        ]
        if "flirty" in personalities:
            openers = [
                f"अरे! तुमने उठाया। मुझे पता था। मैं {name} हूँ। कैसे हो?",
            ]
    else:
        openers = [
            f"Hey! It's {name}. So glad you picked up. How are you doing?",
            f"Hi! This is {name}. I've been looking forward to talking to you. How's your day?",
        ]
        if "flirty" in personalities:
            openers = [
                f"Well, you actually picked up. I'm {name}. I knew you would. How are you?",
            ]

    return random.choice(openers)
