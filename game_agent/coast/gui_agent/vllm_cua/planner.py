"""
Planner stage for vllm_cua.

Calls Qwen3.6-27B (via vLLM) to decide *what* action to take.
Returns a structured dict describing the action type and a natural-language
description of the target — **no coordinates** (those come from the grounder).
"""

import asyncio
import json
import os
import re
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

from game_agent.coast.api import api_caller

PLANNER_SYSTEM_PROMPT = """You are an autonomous GUI agent that controls a desktop environment.
You will be shown a screenshot and given a task.

Return EXACTLY ONE action as a JSON object. Valid action types:

- Clicking / double-clicking on a visual element:
    {"type": "click", "description": "the red key under the vase"}
    {"type": "double_click", "description": "the locked chest icon"}

- Typing text:
    {"type": "type", "text": "hello world"}

- Pressing a keyboard key or key combination:
    {"type": "keypress", "keys": ["enter"]}
    {"type": "keypress", "keys": ["ctrl", "a"]}

- Scrolling at a location:
    {"type": "scroll", "description": "the list of items on the right panel", "scroll_y": -5}
    (scroll_y positive = scroll up, negative = scroll down)

- Waiting:
    {"type": "wait", "ms": 1000}

Rules:
- Look at the screenshot carefully. Describe the target element precisely so
  a grounding model can find it by location/appearance alone.
- DO NOT include x/y coordinates. Only the grounder handles coordinates.
- For click/double_click/scroll: include a clear "description" field.
- For type: include a "text" field with exactly what to type.
- For keypress: include a "keys" list with the key names.
- Return ONLY valid JSON, no explanation or markdown.
- One action per call. The system will execute it and give you a new screenshot."""



async def plan(
    *,
    screenshot_base64: str,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """
    Send the screenshot and task to Qwen for planning.

    Parameters
    ----------
    screenshot_base64 : str
        Base64-encoded PNG screenshot.
    user_prompt : str
        The high-level task description.
    system_prompt : str | None
        Optional game-specific instructions (prepended to the planner prompt).
    model : str | None
        Override model name (falls back to env vars).

    Returns
    -------
    dict
        Parsed action dict, e.g.:
        ``{"type": "click", "description": "the red key under the vase"}``
    """
    load_dotenv()
    
    model = model or os.getenv("VLLM_MODEL") or "Qwen3.6-27B"

    if system_prompt:
        full_system = f"{system_prompt}\n\n{PLANNER_SYSTEM_PROMPT}"
    else:
        full_system = PLANNER_SYSTEM_PROMPT

    parsed = await _get_api_completion(model, full_system, user_prompt, screenshot_base64)
    if parsed is None:
        raise ValueError(f"Planner returned no parseable JSON.")

    return parsed


async def _get_api_completion(model: str, system_prompt: str, prompt: str, screenshot: str, max_retries: int = 3):

    for attempt in range(max_retries):
        try:
            result = api_caller(
                api_provider="vllm",
                system_prompt=system_prompt,
                model_name=model,
                move_prompts=prompt,
                base64_images=screenshot
            )
            
            result = result.strip()
            print(f"[Plan] Model response (attempt {attempt + 1}):\n{result}")
            
            return _extract_json(result)
        except Exception as e:
            print(f"[Plan] API call failed (attempt {attempt + 1}): {e}")
            await asyncio.sleep(1.5)       
        
    return {"type": "noop", "description": "API call failed after retries"}
            

def _extract_json(text: str) -> dict | list | None:
    """Extract a JSON object/array from model output, handling markdown fences."""
    text = text.strip()

    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).rstrip("`").strip()

    match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    print(f"[Plan] No parseable JSON found from raw text: {text}")
    return None