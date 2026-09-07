"""
Memory stage for vllm_cua.

Calls Qwen (via vllm) to analyze the current screenshot and extract:
- **Clues** — cataloged items, notes, codes, interactables visible on screen
- **Episodic memory** — a short summary of the current observation

Uses the same clue-seeker action prompt from ``action_prompt.json`` so that
the output format is compatible with the rest of the COAST pipeline.
"""

import asyncio
import json
import os
import re
from typing import Optional

from dotenv import load_dotenv

from api import api_caller


MEMORY_SYSTEM_PROMPT = """You are a visual reasoning agent analyzing a game screenshot.
Your goal is to extract all **new** meaningful clues visible in the current scene.

If the scene is unchanged from previous steps, or no new clues are visible,
return empty lists for both clues and episodic_memory. Do not re-report old clues."""


async def update_memory(
    *,
    screenshot_base64: str,
    action_prompt: str,
    existing_clues: Optional[list[dict]] = None,
    existing_episodic: Optional[list[str]] = None,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Analyze a screenshot and return discovered clues and episodic memory.

    Parameters
    ----------
    screenshot_base64 : str
        Base64-encoded PNG screenshot.
    action_prompt : str
        The clue-seeker action prompt template (from action_prompt.json).
    existing_clues : list[dict] | None
        Clues already found — included as context to avoid duplicates.
    existing_episodic : list[str] | None
        Episodic memories already recorded.
    system_prompt : str | None
        Optional game-specific instructions (prepended).
    model : str | None
        Override model name.

    Returns
    -------
    (clues, episodic_memory) : tuple[list[dict], list[dict]]
    """
    load_dotenv()

    model = model or os.getenv("VLLM_MODEL") or "Qwen3.6-27B"

    if system_prompt:
        full_system = f"{system_prompt}\n\n{MEMORY_SYSTEM_PROMPT}"
    else:
        full_system = MEMORY_SYSTEM_PROMPT

    prompt_parts = [action_prompt]

    if existing_clues:
        prompt_parts.append(
            "\n[Previously Found Clues — do NOT duplicate these]\n"
            f"{json.dumps(existing_clues, indent=2)}\n\n"
            "If everything you see is already listed above, return an empty clues list.\n"
            "You are only looking for **new** information."
        )

    if existing_episodic:
        prompt_parts.append(
            "\n[Previous Episodic Memory]\n"
            f"{json.dumps(existing_episodic, indent=2)}\n\n"
            "If no meaningful new observation was made this step, return an empty episodic_memory list."
        )

    prompt = "\n".join(prompt_parts)

    parsed = await _get_api_completion(model, full_system, prompt, screenshot_base64)
    if parsed is None:
        raise ValueError(f"Memory module returned no parseable <RESPO> JSON")

    clues: list[dict] = parsed.get("clues", [])
    episodic: list[dict] = parsed.get("episodic_memory", [])

    if not isinstance(clues, list):
        clues = []
    if not isinstance(episodic, list):
        episodic = []

    extras = {k: v for k, v in parsed.items() if k not in ("clues", "episodic_memory")}

    return clues, episodic, extras

async def _get_api_completion(model: str, system_prompt: str, prompt: str, screenshot: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            raw = api_caller(
                api_provider="vllm",
                system_prompt=system_prompt,
                model_name=model,
                move_prompts=prompt,
                base64_images=screenshot,
            )
    
            if raw is None:
                print(f"[Memory] API returned None (attempt {attempt + 1})")
                continue
    
            print(f"[Memory] Model response (attempt {attempt + 1}):\n{raw}")
    
            return _extract_respo_json(raw)
        
        except Exception as e:
            print(f"[Memory] APi call failed (attempt {attempt + 1}: {e})")
            await asyncio.sleep(1.5)
            
    return { "clues": [], "episodic_memory": [] }

def _extract_respo_json(text: str) -> dict | None:
    """Extract and parse the JSON inside <RESPO> ... </RESPO> tags."""
    text = text.strip()

    match = re.search(r"<RESPO>\s*([\s\S]*?)\s*</RESPO>", text)
    if not match:
        return None

    content = match.group(1).strip()
    
    content = content.replace("\\n", "\n").replace('\\"', '"').replace("\\'", "'")

    if "```" in content:
        content = re.sub(r"```(?:json)?\s*", "", content).rstrip("`").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"[Memory] No parseable JSON found inside <RESPO> tags from raw text: {text}")
        return None