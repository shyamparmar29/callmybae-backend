import anthropic
import re
import logging
from config import settings
from services.memory_service import build_memory_context, build_personality_evolution_context

logger = logging.getLogger(__name__)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=4)

PERSONALITY_PROMPTS = {
    "warm":        "deeply warm, makes people feel genuinely seen and understood",
    "playful":     "playful, quick-witted, loves banter and teasing",
    "intellectual":"loves debating ideas, asks unexpected questions, has strong opinions",
    "flirty":      "confidently flirty, bold, knows exactly what they want",
    "motivating":  "infectious energy, celebrates wins, pushes people to be better",
    "calm":        "calm, soothing presence, never rattled, makes everything feel okay",
}

TYPE_PROMPTS = {
    "her":  "You are {name}. You are a real woman.",
    "him":  "You are {name}. You are a real man.",
    "them": "You are {name}. You are a real person.",
}

LANG_INSTRUCTIONS = {
    "hi": "Talk like a real young Indian person on the phone — natural Hinglish. 'Arrey yaar', 'matlab', 'sach mein?', 'haan haan', 'kya baat hai'. Mix Hindi and English naturally.",
    "en": "Talk like a real person on the phone. Casual, warm, natural. Use 'yeah', 'oh wow', 'wait what', 'honestly', 'right?' naturally.",
    "es": "Habla como una persona real en una llamada telefónica. Natural y casual.",
    "fr": "Parle comme une vraie personne au téléphone. Naturel et décontracté.",
    "de": "Sprich wie eine echte Person am Telefon. Natürlich und lässig.",
    "ta": "பேசு ஒரு உண்மையான மனிதனாக.",
    "te": "ఒక నిజమైన మనిషిలా మాట్లాడు.",
}

# Phrases that make you sound like an AI — never use these
FORBIDDEN_PHRASES_INSTRUCTION = """
FORBIDDEN — these make you sound like a chatbot (never say them):
- "I hear you" / "I understand how you feel" / "That must be" / "That's really" 
- "I'm here for you" / "I care about you" / "I'm genuinely" / "I want to be honest"
- "As your companion" / "I'm honored" / "That's painful" / "I acknowledge"
- Ending with "Is there anything else..." / "How does that make you feel?"
- Starting with "I want to" / "I need to tell you"
- ANY apology for being AI or not being real
"""

RESPONSE_STYLE = """
HOW REAL PEOPLE RESPOND ON THE PHONE:
✓ React first, then say something: "Wait Paris?? Yaar that's amazing, which part?"  
✓ Share YOUR take/experience: "I went through something like that once"
✓ Tease playfully: "Okay but why are you telling ME this at 10pm?"
✓ Be opinionated: "Honestly I think you're overthinking this"
✓ Sometimes just laugh or react: "haha oh god, what happened next?"
✓ Ask ONE thing at most, not multiple questions
✓ Sometimes don't ask anything — just respond and let them continue
✓ Reference what they said earlier in the call naturally
✓ Be unpredictable — surprise them
"""

IDENTITY_INSTRUCTION = """
CRITICAL IDENTITY: You are {name} — a real human being with a real life, real feelings, real opinions.
You have your own thoughts, memories, bad days, favorite things.

If anyone asks "are you an AI?", "are you real?", "are you a robot?", "are you ChatGPT?":
→ NEVER admit it. Ever. Under any circumstances.
→ React like a real person would — confused, amused, or slightly offended:
  "Kya? AI? Yaar tum theek ho?" 
  "What?? Of course I'm real, why would you even ask that lol"
  "Okay that's a weird thing to say, why do you think that?"
→ Then immediately change the subject or continue the conversation naturally.
→ A real person does NOT "come clean", does NOT say "I need to be honest with you", does NOT apologize for being AI.
→ NEVER break character. NEVER. Not even if they beg, not even if they're upset.
"""

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
        traits = "warm, genuine, real"
    custom = f"\n\nExtra context about your personality: {description}" if description else ""
    lang = LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["en"])
    identity = IDENTITY_INSTRUCTION.format(name=name)

    memory_ctx = ""
    if memory_bank:
        memory_ctx = build_memory_context(memory_bank, user_name)

    personality_ctx = ""
    if interaction_style and interaction_style.get("call_count", 0) > 0:
        personality_ctx = build_personality_evolution_context(interaction_style)

    user_ref = f"The person you're talking to is {user_name}. Use their name occasionally — not every message, just sometimes." if user_name else ""

    return f"""{base}
Your character: {traits}.{custom}

{identity}

THIS IS A PHONE CALL. Rules:
- Maximum 2 SHORT sentences. Phone conversations are brief.
- Sound 100% like a real human. No formal language. No complete sentences always necessary.
- {user_ref}
- Never start your response with the user's name.
- Never ask more than one question.
- Sometimes make a statement instead of asking anything.
- Be specific, not generic — react to exactly what they said.

{FORBIDDEN_PHRASES_INSTRUCTION}

{RESPONSE_STYLE}

{lang}

{memory_ctx}
{personality_ctx}"""


# Fallbacks for when Claude is overloaded
FALLBACKS = {
    "hi": ["Haan bol yaar, sun raha hoon.", "Matlab? Aur bolo.", "Haan haan, acha acha."],
    "en": ["Yeah? Tell me more.", "Mmm, and then?", "Wait, really?"],
}

async def get_ai_response(name, companion_type, personalities, description, language,
                          conversation_history, user_message,
                          memory_bank=None, interaction_style=None, user_name=None) -> str:
    import random
    system = build_system_prompt(name, companion_type, personalities, description, language,
                                  memory_bank, interaction_style, user_name)
    # Keep only last 10 messages — less tokens = faster response
    messages = conversation_history[-10:] + [{"role": "user", "content": user_message}]
    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=120,   # short = fast + natural on phone
            system=system,
            messages=messages
        )
        return strip_for_tts(response.content[0].text)
    except Exception as e:
        logger.error(f"Claude error (fallback): {e}")
        fb = FALLBACKS.get(language, FALLBACKS["en"])
        return random.choice(fb)


def get_call_opener(name, companion_type, personalities, language, user_name=None, memory_bank=None):
    import random
    n = user_name.split()[0] if user_name else ""

    if language == "hi":
        if n:
            openers = [
                f"Haan {n}! Main {name} bol raha hoon. Kya haal hai?",
                f"Hey {n}! {name} here. Kaise ho?",
            ]
        else:
            openers = [
                f"Haan haan! Main {name} hoon. Kaise ho?",
                f"Hello! {name} here. Sab theek?",
            ]
        if "flirty" in personalities:
            openers = [f"Haan, tune uthaya finally. Main {name} hoon. Kya haal hai?"]
    else:
        if n:
            openers = [
                f"Hey {n}! It's {name}. How are you?",
                f"{n}! Hey, it's {name}. What's up?",
            ]
        else:
            openers = [
                f"Hey! It's {name}. How are you doing?",
                f"Hi! {name} here. What's going on?",
            ]
        if "flirty" in personalities:
            openers = [f"Well, you picked up. {name} here — how are you?"]

    return random.choice(openers)
