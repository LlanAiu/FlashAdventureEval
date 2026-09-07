"""
Orchestrator for the vllm_cua GUI agent.

Per-step loop:
    1. **Screenshot**  — capture (cropped to game window)
    2. **Memory**      — update clues & episodic memory (Qwen)
    3. **Plan**        — decide next action (Qwen)
    4. **Ground**      — resolve description → pixel coordinates (UGround)
    5. **Execute**     — dispatch via LocalDesktopComputer

The return value includes a ``<RESPO>``-tagged summary in ``messages`` for
backward compatibility with ``SeekerBot`` / ``SolverBot`` in ``moduler.py``.
"""

import asyncio
import json
import os
import time
from typing import Optional

from dotenv import load_dotenv

from tools import load_config, load_action_prompt
from ..gpt_cua.computers.computer_use import LocalDesktopComputer
from .planner import plan
from .grounder import ground
from .memory import update_memory


ACTION_TYPES_NEEDS_GROUNDING = {"click", "double_click", "scroll"}


def main_vllm_cua(
    user_prompt: str,
    system_prompt: Optional[str] = None,
    max_actions: int = 30,
    model: Optional[str] = None,
    game_name: str = "unknown",
    reasoning_model: str = "unknown",
    type: Optional[str] = None,
) -> dict:
    """
    Run the vllm-powered GUI agent loop.

    Signature mirrors the original so that ``execute.py`` needs no changes.

    Returns
    -------
    dict
        ``{"messages": [...], "action_count": int, "clues": [...],
           "episodic": [...], "extras": {...}}``
    """
    return asyncio.run(
        _run_loop(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_actions=max_actions,
            model=model,
            game_name=game_name,
            moduler=type or "clue_seeker",
        )
    )

async def _run_loop(
    user_prompt: str,
    system_prompt: Optional[str],
    max_actions: int,
    model: Optional[str],
    game_name: str,
    moduler: str,
) -> dict:
    """Core async loop: screenshot → memory → plan → ground → execute."""
    load_dotenv()

    model = model or os.getenv("VLLM_MODEL") or "Qwen3.6-27B"
    action_prompt = _load_action_prompt(moduler)

    computer = LocalDesktopComputer(
        max_actions=max_actions,
        game_name=game_name,
        gui_agent="vllm_cua",
        reasoning_model=model,
    )

    all_clues: list[dict] = []
    all_episodic: list[dict] = []
    merged_extras: dict = {}
    message_history: list[str] = []

    print(f"\n{'='*60}")
    print(f"  vllm GUI Agent  |  model={model}  |  max_actions={max_actions}")
    print(f"  moduler={moduler}  |  game={game_name}")
    print(f"{'='*60}\n")

    consecutive_failures = 0
    max_consecutive_failures = 5

    for step in range(1, max_actions + 1):
        print(f"[Step {step}/{max_actions}] Capturing screenshot...")
        screenshot = computer.screenshot()
        img_w, img_h = _get_image_dims(computer)

        print(f"[Step {step}] Updating memory...")
        try:
            new_clues, new_episodic, extras = await update_memory(
                screenshot_base64=screenshot,
                action_prompt=action_prompt,
                user_prompt=user_prompt,
                existing_clues=all_clues,
                existing_episodic=all_episodic,
                system_prompt=system_prompt,
                model=model,
            )
            all_clues, all_episodic, merged_extras = _accumulate_state(
                all_clues, all_episodic, merged_extras,
                new_clues, new_episodic, extras,
            )
        except Exception as e:
            print(f"[Main] Memory update failed (step {step}): {e}")

        print(f"[Step {step}] Planning action...")
        try:
            action = await plan(
                screenshot_base64=screenshot,
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
            )
        except Exception as e:
            print(f"[Main] Planning failed (step {step}): {e}")
            if _check_failures(consecutive_failures := consecutive_failures + 1,
                               max_consecutive_failures):
                break
            continue

        if action.get("type") == "noop":
            print(f"[Main] Planner returned noop. Retrying...")
            if _check_failures(consecutive_failures := consecutive_failures + 1,
                               max_consecutive_failures):
                break
            continue

        consecutive_failures = 0

        x, y = await _maybe_ground(action, screenshot, img_w, img_h)
        if (x, y) is None:
            if _check_failures(consecutive_failures := consecutive_failures + 1,
                               max_consecutive_failures):
                break
            continue

        action_type = action.get("type", "wait")
        print(f"[Main] Executing: {action_type} (x={x}, y={y})")
        _execute_action(action, computer, x=x, y=y)
        message_history.append(json.dumps(action))
        time.sleep(0.5)

    message_history.append(_build_summary(all_clues, all_episodic, merged_extras))

    print(f"\n[Done] Performed {computer.action_count} action(s).")
    print(f"  Clues found: {len(all_clues)}")
    print(f"  Episodic entries: {len(all_episodic)}")

    return {
        "messages": message_history,
        "action_count": computer.action_count,
        "clues": all_clues,
        "episodic": all_episodic,
        "extras": merged_extras,
    }

def _get_image_dims(computer: LocalDesktopComputer) -> tuple[int, int]:
    """Return the screenshot dimensions (cropped or full-screen)."""
    if computer._auto_crop and computer._crop_offset:
        return computer._crop_offset[2], computer._crop_offset[3]
    return computer._dimensions[0], computer._dimensions[1]


async def _maybe_ground(
    action: dict,
    screenshot: str,
    img_w: int,
    img_h: int,
) -> tuple[int, int] | None:
    """
    Ground the action if it requires coordinates.

    Returns ``(x, y)`` on success, ``(0, 0)`` for non-grounding actions,
    or ``None`` on failure (caller should retry/break).
    """
    action_type = action.get("type", "wait")

    if action_type not in ACTION_TYPES_NEEDS_GROUNDING:
        return 0, 0

    description = action.get("description", "")
    if not description:
        print(f"[Main] Action '{action_type}' missing description. Skipping.")
        return None

    print(f"[Grounding] {description}")
    try:
        return await ground(
            screenshot_base64=screenshot,
            description=description,
            image_width=img_w,
            image_height=img_h,
        )
    except Exception as e:
        print(f"[Main] Grounding failed: {e}")
        return None


def _accumulate_state(
    clues: list[dict],
    episodic: list[dict],
    extras: dict,
    new_clues: list[dict],
    new_episodic: list[dict],
    new_extras: dict,
) -> tuple[list[dict], list[dict], dict]:
    """Deduplicate and merge new results into accumulated state."""
    for clue in new_clues:
        if clue not in clues:
            clues.append(clue)
    for mem in new_episodic:
        if mem not in episodic:
            episodic.append(mem)

    if new_extras:
        for key, val in new_extras.items():
            if key not in extras:
                extras[key] = val
            elif isinstance(extras[key], list) and isinstance(val, list):
                extras[key].extend(val)
            else:
                extras[key] = val

    return clues, episodic, extras


def _check_failures(count: int, max_failures: int) -> bool:
    """Log and return True if max consecutive failures reached."""
    if count >= max_failures:
        print(f"[Main] Hit {max_failures} consecutive failures. Exiting.")
        return True
    return False


def _build_summary(
    clues: list[dict],
    episodic: list[dict],
    extras: dict,
) -> str:
    """Build the final ``<RESPO>``-tagged JSON summary for moduler.py compat."""
    summary = {
        "clues": clues,
        "episodic_memory": episodic,
    }
    summary.update(extras)
    return f"<RESPO>\n{json.dumps(summary, indent=2, ensure_ascii=False)}\n</RESPO>"


def _execute_action(action: dict, computer: LocalDesktopComputer, x: int = 0, y: int = 0) -> None:
    """Dispatch a parsed action dict to the computer."""
    action_type = action.get("type", "wait")

    try:
        if action_type == "click":
            computer.click(x, y, button=action.get("button", "left"))
        elif action_type == "double_click":
            computer.double_click(x, y)
        elif action_type == "scroll":
            computer.scroll(x, y,
                            scroll_x=action.get("scroll_x", 0),
                            scroll_y=action.get("scroll_y", -5))
        elif action_type == "type":
            computer.type(action.get("text", ""))
        elif action_type == "keypress":
            computer.keypress(action.get("keys", ["enter"]))
        elif action_type == "wait":
            computer.wait(action.get("ms", 1000))
        elif action_type == "move":
            computer.move(x, y)
        elif action_type == "noop":
            pass
        else:
            print(f"[Main] Unknown action type: {action_type}")
    except Exception as e:
        print(f"[Main] Action execution failed ({action_type}): {e}")

def _load_action_prompt(moduler: str = "clue_seeker") -> str:
    """Load the action prompt template via the shared tools loader."""
    config = load_config("config.yaml")
    return load_action_prompt(config.get("action_prompt_path"), moduler)
