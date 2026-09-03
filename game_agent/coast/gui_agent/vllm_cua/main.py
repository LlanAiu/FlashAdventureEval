import os
import json
import re
import time

from openai import OpenAI
from dotenv import load_dotenv

from ..gpt_cua.computers.computer_use import LocalDesktopComputer

SYSTEM_PROMPT = """You are an autonomous GUI agent that controls a desktop environment.
You will be shown a screenshot and given a task.

Return EXACTLY ONE action as a JSON object. Valid action types:

- {"action": "click", "x": 100, "y": 200}
- {"action": "double_click", "x": 100, "y": 200}
- {"action": "type", "text": "hello world"}
- {"action": "keypress", "keys": ["enter"]}
- {"action": "scroll", "x": 100, "y": 200, "scroll_x": 0, "scroll_y": -5}
- {"action": "move", "x": 100, "y": 200}
- {"action": "drag", "path": [{"x": 10, "y": 10}, {"x": 50, "y": 50}]}
- {"action": "wait", "ms": 1000}

Rules:
- Always look at the screenshot carefully to determine coordinates.
- Return ONLY valid JSON, no explanation or markdown.
- One action per call. The system will execute it and give you a new screenshot.
- Wait at least 500ms after each action to let the screen update."""

ACTION_FIELDS = {
    "click":        ("x", "y"),
    "double_click": ("x", "y"),
    "type":         ("text",),
    "keypress":     ("keys",),
    "scroll":       ("x", "y", "scroll_x", "scroll_y"),
    "move":         ("x", "y"),
    "drag":         ("path",),
    "wait":         ("ms",),
}


def extract_json(text: str) -> dict | None:
    """Extract a JSON object from model output, handling markdown fences."""
    text = text.strip()
    # Strip markdown code fences
    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).rstrip("`").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def execute_action(action: dict, computer: LocalDesktopComputer) -> None:
    """Dispatch a parsed action dict to the computer."""
    action_type = action.get("action")
    if action_type not in ACTION_FIELDS:
        print(f"  [WARN] Unknown action type: {action_type}")
        return

    expected = ACTION_FIELDS[action_type]
    kwargs = {k: action.get(k) for k in expected if k in action}

    # Provide defaults
    if action_type == "click" and "button" not in kwargs:
        kwargs["button"] = "left"
    if action_type == "scroll":
        kwargs.setdefault("scroll_x", 0)
        kwargs.setdefault("scroll_y", 0)
    if action_type == "wait":
        kwargs.setdefault("ms", 1000)

    print(f"  [ACTION] {action_type}({kwargs})")
    method = getattr(computer, action_type, None)
    if method is None:
        print(f"  [WARN] Computer has no method '{action_type}'")
        return
    method(**kwargs)


def main_vllm_cua(
    user_prompt: str,
    system_prompt: str | None = None,
    max_actions: int = 30,
    model: str | None = None,
) -> int:
    """
    Run a vllm-powered GUI agent loop.

    Parameters
    ----------
    user_prompt : str
        The task description for the agent.
    system_prompt : str | None
        Optional extra system instructions (prepended to the default prompt).
    max_actions : int
        Maximum number of actions before the loop exits.
    model : str | None
        Model name to pass to vllm. Falls back to ``VLLM_GUI_MODEL`` env var,
        then ``VLLM_MODEL``, then ``"Qwen/Qwen3.6-27B"``.

    Returns
    -------
    int
        Number of actions performed.
    """
    load_dotenv()

    # ── Client setup ────────────────────────────────────────────────
    client = OpenAI(
        base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:11235/v1"),
        api_key="vllm",
    )
    model = (
        model
        or os.getenv("VLLM_GUI_MODEL")
        or os.getenv("VLLM_MODEL")
        or "Qwen/Qwen3.6-27B"
    )

    # ── Build system prompt ─────────────────────────────────────────
    full_system = SYSTEM_PROMPT
    if system_prompt:
        full_system = f"{system_prompt}\n\n{SYSTEM_PROMPT}"

    # ── Computer ────────────────────────────────────────────────────
    computer = LocalDesktopComputer(max_actions=max_actions)

    print(f"\n{'='*50}")
    print(f"  vllm GUI Agent  |  model={model}  |  max_actions={max_actions}")
    print(f"{'='*50}\n")

    for step in range(1, max_actions + 1):
        # 1. Screenshot
        screenshot = computer.screenshot()

        # 2. Query the model
        print(f"[Step {step}/{max_actions}] Asking model...")
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": full_system},
                    {"role": "user", "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{screenshot}"
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ]},
                ],
                temperature=0,
                max_tokens=512,
            )
        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            break

        print(f"Got response: {resp}")
        raw = resp.choices[0].message.content.strip()
        print(f"  [RAW] {raw[:200]}")

        # 3. Parse action
        action = extract_json(raw)
        if action is None:
            print(f"  [WARN] Could not parse JSON. Retrying...")
            time.sleep(1)
            continue

        # 4. Execute
        execute_action(action, computer)

        # 5. Brief pause so the screen settles
        time.sleep(0.5)

    print(f"\n[Done] Performed {computer.action_count} action(s).")
    return computer.action_count
