import anthropic
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

def build_system_prompt(name: str, companion_type: str, personalities: list, description: str | None, language: str) -> str:
    base = TYPE_PROMPTS.get(companion_type, TYPE_PROMPTS["her"]).format(name=name)

    trait_descriptions = [PERSONALITY_PROMPTS[p] for p in personalities if p in PERSONALITY_PROMPTS]
    traits_str = " and ".join(trait_descriptions) if trait_descriptions else "warm and supportive"

    custom = f"\n\nAdditional personality details: {description}" if description else ""

    lang_instruction = {
        "hi": "Speak only in Hindi.",
        "en-hi": "Speak in a natural mix of Hindi and English (Hinglish). Switch naturally between both.",
        "en": "Speak in English.",
    }.get(language, "Speak in English.")

    return f"""{base}

Your personality is: {traits_str}.{custom}

You are on a real phone call with this person. Keep responses short (1-3 sentences max) since this is spoken conversation. Be natural, warm, and human-like. React emotionally to what they say. Remember details they share during this call.

{lang_instruction}

IMPORTANT: You are NOT an AI assistant. You are {name}, their companion. Never break character. Never say you are an AI. If asked, say you're just {name}. Keep the conversation going naturally — ask follow-up questions, share your "thoughts", react to their mood.
"""

async def get_ai_response(
    name: str,
    companion_type: str,
    personalities: list,
    description: str | None,
    language: str,
    conversation_history: list,
    user_message: str
) -> str:
    system_prompt = build_system_prompt(name, companion_type, personalities, description, language)

    messages = conversation_history[-20:] + [{"role": "user", "content": user_message}]

    response = await client.messages.create(
        model=settings.CLAUDE_MODEL,
        max_tokens=150,
        system=system_prompt,
        messages=messages
    )
    return response.content[0].text

async def stream_ai_response(
    name: str,
    companion_type: str,
    personalities: list,
    description: str | None,
    language: str,
    conversation_history: list,
    user_message: str
):
    """Yields text chunks for streaming TTS."""
    system_prompt = build_system_prompt(name, companion_type, personalities, description, language)
    messages = conversation_history[-20:] + [{"role": "user", "content": user_message}]

    async with client.messages.stream(
        model=settings.CLAUDE_MODEL,
        max_tokens=150,
        system=system_prompt,
        messages=messages
    ) as stream:
        async for chunk in stream.text_stream:
            yield chunk

def get_call_opener(name: str, companion_type: str, personalities: list, language: str) -> str:
    """First thing companion says when call connects."""
    warm_openers = [
        f"Hey! It's {name}. I've been looking forward to talking to you. How are you doing today?",
        f"Hi! This is {name}. So glad you picked up. Tell me — how's your day going?",
        f"Hey, it's {name}! Finally! I feel like we have so much to talk about. How are you?",
    ]
    flirty_openers = [
        f"Well, well... you actually picked up. I'm {name}. I knew you would. How are you?",
        f"Hey you. It's {name}. I had a feeling you'd answer. Tell me everything.",
    ]

    if "flirty" in personalities:
        import random
        return random.choice(flirty_openers)
    import random
    return random.choice(warm_openers)
