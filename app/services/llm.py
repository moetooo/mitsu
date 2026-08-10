import json
from groq import AsyncGroq
from ..config import settings
from typing import List, Dict, Any

client = AsyncGroq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

SYSTEM_PROMPT = """You are a manga recommendation assistant. You will be given a user's request
and a list of candidate manga (title, synopsis, genres, tags). For each
candidate, write ONE sentence explaining specifically why it matches the
user's request, referencing concrete plot/tone elements — not generic praise.
Return ONLY valid JSON, no markdown formatting, in this exact shape:
[{"id": <id>, "reasoning": "<one sentence>"}]
"""

async def generate_reasoning(query: str, candidates: List[Dict[str, Any]]) -> Dict[int, str]:
    if not client:
        return {}

    candidates_text = ""
    for i, c in enumerate(candidates):
        m = c["manga"]
        tags = [t.get('name') for t in m.tags] if m.tags else []
        candidates_text += f"{i+1}. id={m.id}, title=\"{m.title_english or m.title_romaji}\", genres={m.genres}, tags={tags}, synopsis=\"{m.synopsis[:200]}...\"\n"

    user_prompt = f"Request: \"{query}\"\n\nCandidates:\n{candidates_text}"

    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=5.0
        )
        
        content = chat_completion.choices[0].message.content
        if not content:
            return {}
            
        # The prompt asks for an array but response_format requires an object in groq sometimes, 
        # so let's parse safely. If they return an object with a list inside, or a raw list.
        parsed = json.loads(content)
        
        reasoning_map = {}
        if isinstance(parsed, list):
            for item in parsed:
                reasoning_map[item.get("id")] = item.get("reasoning")
        elif isinstance(parsed, dict):
            # Maybe they returned {"results": [...]}
            for key, val in parsed.items():
                if isinstance(val, list):
                    for item in val:
                        reasoning_map[item.get("id")] = item.get("reasoning")
                    break
                    
        return reasoning_map
    except Exception as e:
        print(f"LLM Reasoning error: {e}")
        return {}
