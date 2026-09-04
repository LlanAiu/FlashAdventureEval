import os
import json
import re
import time

from openai import OpenAI
from dotenv import load_dotenv

from ..gpt_cua.computers.computer_use import LocalDesktopComputer

SYSTEM_PROMPT_DEFAULT = """You are an autonomous GUI agent that controls a desktop environment.
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


def extract_json(text: str) -> dict | list | None:
    """Extract a JSON object/array from model output, handling <RESPO> tags and markdown fences."""
    text = text.strip()
    
    respo_match = re.search(r"<RESPO>\s*([\s\S]*?)\s*</RESPO>", text)
    if respo_match:
        text = respo_match.group(1).strip()
    
    if "```" in text:
        text = re.sub(r"```(?:json)?\s*", "", text).rstrip("`").strip()
    
    match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
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
    game_name: str = "unknown",
    reasoning_model: str = "unknown",
) -> dict:
    """
    Run a vllm-powered GUI agent loop.

    Parameters
    ----------
    user_prompt : str
        The task description for the agent.
    system_prompt : str | None
        Optional system instructions (used directly when provided,
        otherwise falls back to ``SYSTEM_PROMPT_DEFAULT``).
    max_actions : int
        Maximum number of actions before the loop exits.
    model : str | None
        Model name to pass to vllm. Falls back to ``VLLM_GUI_MODEL`` env var,
        then ``VLLM_MODEL``, then ``"Qwen/Qwen3.6-27B"``.

    Returns
    -------
    dict
        ``{"messages": [...], "action_count": int}``
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
    # Always include the default action-instruction system prompt.
    # If the caller provides additional system context (game instructions),
    # prepend it so the model knows both the game rules and action format.
    if system_prompt:
        full_system = f"{system_prompt}\n\n{SYSTEM_PROMPT_DEFAULT}"
    else:
        full_system = SYSTEM_PROMPT_DEFAULT

    # ── Computer ────────────────────────────────────────────────────
    computer = LocalDesktopComputer(
        max_actions=max_actions,
        game_name=game_name,
        gui_agent="vllm_cua",
        reasoning_model=model,
    )

    print(f"\n{'='*50}")
    print(f"  vllm GUI Agent  |  model={model}  |  max_actions={max_actions}")
    print(f"{'='*50}\n")

    message_history: list[str] = []

    for step in range(1, max_actions + 1):
        screenshot = computer.screenshot()

        # Tell the model the actual screenshot dimensions so it stays within bounds
        dim_text = ""
        if computer._auto_crop and computer._crop_offset:
            cw, ch = computer._crop_offset[2], computer._crop_offset[3]
            dim_text = (f"\n\n[NOTE: Screenshot is cropped to the game window "
                        f"({cw}x{ch}). Top-left of the image is (0,0). "
                        f"All coordinates must be: 0 <= x <= {cw}, 0 <= y <= {ch}]")
        elif computer._dimensions:
            dw, dh = computer._dimensions
            dim_text = f"\n\n[NOTE: Screenshot dimensions are {dw}x{dh}]"

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
                        {"type": "text", "text": user_prompt + dim_text},
                    ]},
                ],
                temperature=0,
                max_tokens=int(os.getenv("VLLM_MAX_TOKENS", "4096")),
                extra_body={
                    "max_reasoning_tokens": int(os.getenv("VLLM_MAX_REASONING_TOKENS", "2048")),
                },
            )
        except Exception as e:
            print(f"[ERROR] API call failed: {e}")
            break

        choice = resp.choices[0].message
        finish = resp.choices[0].finish_reason

        raw = (choice.content or choice.reasoning or "").strip()
        message_history.append(raw)

        if finish == "length":
            print(f"  [WARN] Response truncated (hit max_tokens). Consider increasing max_tokens.")

        print(f"  [RAW] {raw}...")

        parsed = extract_json(raw)
        if parsed is None:
            print(f"  [WARN] Could not parse JSON. Retrying...")
            time.sleep(1)
            continue

        # Execute GUI action if present
        # The model may output: {"action": ...} or {"next_action": {"action": ...}}
        gui_action = None
        if isinstance(parsed, dict):
            if "action" in parsed and "x" in parsed:
                gui_action = parsed
            elif "next_action" in parsed:
                gui_action = parsed["next_action"]

        if gui_action:
            execute_action(gui_action, computer)

        time.sleep(0.5)

    print(f"\n[Done] Performed {computer.action_count} action(s).")
    return {
        "messages": message_history,
        "action_count": computer.action_count,
    }
