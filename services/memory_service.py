"""
Memory Service — extracts structured memories from call transcripts
and builds a personalized context for the AI companion.

This is the core retention feature. The more calls a user has,
the richer their memory bank → better AI responses → stronger attachment.
"""
import anthropic
import json
import logging
import re
from datetime import datetime, timezone
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



# ─────────────────────────────────────────────────────────
# CHARACTER LIFE PROGRESSION
# After each call, advance the character's life - sometimes positive, sometimes negative
# ─────────────────────────────────────────────────────────

CHARACTER_LIFE_PROMPT = """You are analyzing a phone conversation between {character_name} (a fictional character with their own life) and a user.

{character_name}'s current life state:
{current_life_state}

Conversation transcript:
{transcript}

Your job: ADVANCE {character_name}'s life by one small step. Real life is messy — sometimes things get better, sometimes worse, sometimes both. Pick natural progression based on their existing storylines.

Output ONLY valid JSON with this structure:
{{
  "new_mood": "<one phrase describing their updated mood>",
  "life_event": "<one sentence describing something that happened to them since last call>",
  "is_positive": true or false,
  "storyline_updates": [
    {{"topic": "<topic>", "status": "<new status>", "details": "<updated details>"}}
  ],
  "shared_with_user": "<something they shared about themselves in this call, or empty string>"
}}

Rules:
- The life_event should feel real and natural for {character_name}
- Vary positive/negative roughly 60/40 (not always good news)
- Update at most 2 storylines
- Keep details short and human"""


async def advance_character_life(character_name: str, current_life_state: dict, transcript: list) -> dict:
    """
    After a call, advance the character's life one step.
    Returns updated life_state dict.
    """
    if not transcript:
        return current_life_state

    try:
        # Format current state
        state_str = json.dumps(current_life_state, indent=2, ensure_ascii=False)
        # Format transcript (last 20 messages max)
        tx_lines = []
        for m in transcript[-20:]:
            role = m.get("role", "")
            content = m.get("content", "")
            who = character_name if role == "assistant" else "User"
            tx_lines.append(f"{who}: {content}")
        tx_str = "\n".join(tx_lines)

        prompt = CHARACTER_LIFE_PROMPT.format(
            character_name=character_name,
            current_life_state=state_str,
            transcript=tx_str,
        )

        from config import settings
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=500,
            system="You analyze conversations and update character life states. Output ONLY valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()
        # Strip markdown if Claude added it
        result_text = re.sub(r"^```(?:json)?\s*", "", result_text)
        result_text = re.sub(r"\s*```$", "", result_text)

        update = json.loads(result_text)

        # Apply update to life state
        new_state = dict(current_life_state)

        if update.get("new_mood"):
            new_state["mood"] = update["new_mood"]

        if update.get("life_event"):
            recent = list(new_state.get("recent_events", []))
            recent.insert(0, update["life_event"])
            new_state["recent_events"] = recent[:6]  # keep last 6 events

        if update.get("storyline_updates"):
            existing = {sl.get("topic"): sl for sl in new_state.get("ongoing_storylines", []) if isinstance(sl, dict)}
            for upd in update["storyline_updates"]:
                if isinstance(upd, dict) and upd.get("topic"):
                    existing[upd["topic"]] = upd
            new_state["ongoing_storylines"] = list(existing.values())[:6]

        new_state["last_updated"] = datetime.now(timezone.utc).isoformat()
        return new_state

    except Exception as e:
        logger.error(f"advance_character_life error: {e}")
        return current_life_state


async def extract_user_memory_for_character(transcript: list, existing_memory: dict) -> dict:
    """
    Extract what THIS USER shared with THIS CHARACTER specifically.
    Returns merged memory dict.
    """
    if not transcript:
        return existing_memory

    try:
        tx_lines = []
        for m in transcript[-30:]:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user":
                tx_lines.append(f"User: {content}")
        if not tx_lines:
            return existing_memory
        tx_str = "\n".join(tx_lines)

        prompt = f"""Extract what the user shared about themselves in this conversation. Output ONLY valid JSON:

{{
  "shared_facts": ["<fact 1>", "<fact 2>"],
  "current_feelings": "<what they were feeling>",
  "mentioned_people": ["<person 1>"],
  "things_to_remember": ["<thing 1>", "<thing 2>"]
}}

Conversation:
{tx_str}

Keep each entry short. Skip if nothing notable was shared."""

        from config import settings
        response = await client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=400,
            system="You extract user information from conversations. Output ONLY valid JSON.",
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        new_data = json.loads(text)

        # Merge into existing memory
        merged = dict(existing_memory)
        for key, val in new_data.items():
            if not val:
                continue
            if isinstance(val, list):
                existing_list = merged.get(key, [])
                if not isinstance(existing_list, list):
                    existing_list = []
                # Dedup while keeping order
                seen = set(str(x).lower() for x in existing_list)
                for item in val:
                    if str(item).lower() not in seen:
                        existing_list.append(item)
                        seen.add(str(item).lower())
                merged[key] = existing_list[-15:]  # cap
            else:
                merged[key] = val

        merged["last_updated"] = datetime.now(timezone.utc).isoformat()
        return merged

    except Exception as e:
        logger.error(f"extract_user_memory_for_character error: {e}")
        return existing_memory
