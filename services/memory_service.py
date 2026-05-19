"""
Memory Service — extracts structured memories from call transcripts
and builds a personalized context for the AI companion.

This is the core retention feature. The more calls a user has,
the richer their memory bank → better AI responses → stronger attachment.
"""
import anthropic
import json
import logging
from config import settings

logger = logging.getLogger(__name__)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

MEMORY_EXTRACT_PROMPT = """You are analyzing a conversation transcript to extract important personal facts about the USER (not the AI companion).

Extract ONLY facts explicitly mentioned by the user. Return a JSON object with these categories:

{
  "personal": {
    "name": null,
    "age": null,
    "city": null,
    "occupation": null,
    "relationship_status": null
  },
  "family": [],        // e.g. ["has a sister named Priya", "father is a doctor"]
  "work": [],          // e.g. ["works at a startup", "stressed about a presentation"]
  "health": [],        // e.g. ["has back pain", "goes to gym"]
  "interests": [],     // e.g. ["loves cricket", "plays guitar"]
  "events": [],        // e.g. ["sister's wedding next month", "just got a promotion"]
  "struggles": [],     // e.g. ["feeling lonely", "work pressure"]
  "preferences": [],   // e.g. ["likes talking at night", "prefers Hindi"]
  "important_people": [], // e.g. ["best friend Rahul", "mentor Suresh"]
  "goals": []          // e.g. ["wants to start a business", "learning to code"]
}

Return ONLY valid JSON. No explanation. If nothing found for a category, keep it empty/null.
"""

async def extract_memories_from_transcript(transcript: list[dict]) -> dict:
    """Extract structured memories from a call transcript."""
    if not transcript:
        return {}
    
    # Format transcript for analysis
    conversation = "\n".join([
        f"{'USER' if t['role'] == 'user' else 'AI'}: {t['content']}"
        for t in transcript
        if t.get('content')
    ])
    
    if len(conversation) < 50:
        return {}
    
    try:
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"{MEMORY_EXTRACT_PROMPT}\n\nTRANSCRIPT:\n{conversation}"
            }]
        )
        
        text = response.content[0].text.strip()
        # Strip markdown code blocks if present
        text = text.replace("```json", "").replace("```", "").strip()
        extracted = json.loads(text)
        return extracted
        
    except Exception as e:
        logger.error(f"Memory extraction error: {e}")
        return {}


def merge_memories(existing: dict, new_memories: dict) -> dict:
    """Merge new extracted memories into existing memory bank."""
    if not existing:
        existing = {}
    
    merged = dict(existing)
    
    for key, value in new_memories.items():
        if not value:
            continue
            
        if isinstance(value, list):
            existing_list = merged.get(key, [])
            # Add new items, avoid duplicates
            for item in value:
                if item and item not in existing_list:
                    existing_list.append(item)
            merged[key] = existing_list[-20:]  # Keep latest 20 per category
            
        elif isinstance(value, dict):
            existing_dict = merged.get(key, {})
            for k, v in value.items():
                if v is not None:
                    existing_dict[k] = v
            merged[key] = existing_dict
            
        else:
            if value:
                merged[key] = value
    
    return merged


def build_memory_context(memory_bank: dict, user_name: str = None) -> str:
    """
    Convert memory bank into natural language context for the AI.
    This gets injected into the system prompt.
    """
    if not memory_bank:
        return ""
    
    lines = []
    
    personal = memory_bank.get("personal", {})
    if personal:
        facts = []
        if personal.get("name"):
            facts.append(f"name is {personal['name']}")
        if personal.get("age"):
            facts.append(f"age {personal['age']}")
        if personal.get("city"):
            facts.append(f"from {personal['city']}")
        if personal.get("occupation"):
            facts.append(f"works as {personal['occupation']}")
        if personal.get("relationship_status"):
            facts.append(personal["relationship_status"])
        if facts:
            lines.append("About them: " + ", ".join(facts))
    
    for category, label in [
        ("family", "Family"),
        ("work", "Work/Career"),
        ("interests", "Interests"),
        ("important_people", "Important people in their life"),
        ("struggles", "They've mentioned struggling with"),
        ("goals", "Their goals"),
        ("events", "Recent events"),
        ("health", "Health"),
    ]:
        items = memory_bank.get(category, [])
        if items:
            lines.append(f"{label}: {'; '.join(items[:5])}")
    
    prefs = memory_bank.get("preferences", [])
    if prefs:
        lines.append(f"Conversation preferences: {'; '.join(prefs[:3])}")
    
    if not lines:
        return ""
    
    return "WHAT YOU KNOW ABOUT THIS PERSON (from past conversations — use naturally, don't recite):\n" + "\n".join(lines)


def build_personality_evolution_context(interaction_style: dict) -> str:
    """Build context from learned interaction patterns."""
    if not interaction_style:
        return ""
    
    lines = []
    
    if interaction_style.get("humor_enjoyed"):
        lines.append(f"They enjoy: {interaction_style['humor_enjoyed']}")
    if interaction_style.get("topics_frequent"):
        topics = interaction_style["topics_frequent"][:3]
        lines.append(f"They often talk about: {', '.join(topics)}")
    if interaction_style.get("emotional_support_needed"):
        lines.append(f"They often need: {interaction_style['emotional_support_needed']}")
    if interaction_style.get("call_count", 0) > 5:
        lines.append(f"You've had {interaction_style['call_count']} conversations together — you know each other well.")
    
    if not lines:
        return ""
    
    return "RELATIONSHIP CONTEXT:\n" + "\n".join(lines)
