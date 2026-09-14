"""
Debug crosshair overlay for vllm_cua screenshots.

When VLLM_CUA_DEBUG_CROSSHAIR=1, draws a red crosshair at the grounder's
target coordinates and overwrites the saved debug screenshot so you can
visually inspect where the grounding model pointed.
"""

import base64
import os
from io import BytesIO

from PIL import Image, ImageDraw


def is_debug_overlay_enabled() -> bool:
    """Return True if the crosshair debug overlay is enabled."""
    return os.environ.get("VLLM_CUA_DEBUG_CROSSHAIR", "").lower() in ("1", "true", "yes")


def annotate_and_overwrite(
    *,
    screenshot_base64: str,
    x: int,
    y: int,
    description: str,
    save_path: str,
) -> None:
    """
    Decode the base64 screenshot, draw a red crosshair at (x, y),
    and save it (overwriting) to *save_path*.

    Parameters
    ----------
    screenshot_base64 : str
        Base64-encoded PNG screenshot (cropped game window).
    x, y : int
        Target coordinates in the cropped-image space.
    description : str
        Human-readable target description (drawn as a small label).
    save_path : str
        File path to overwrite with the annotated screenshot.
    """
    img_data = base64.b64decode(screenshot_base64)
    img = Image.open(BytesIO(img_data))
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size

    cx = max(0, min(x, img_w - 1))
    cy = max(0, min(y, img_h - 1))

    _draw_crosshair(draw, cx, cy)

    _draw_label(draw, cx, cy, description)

    img.save(save_path, format="PNG")
    print(f"[Debug] Annotated screenshot saved: {save_path}")


def _draw_crosshair(draw: ImageDraw, x: int, y: int) -> None:
    """Draw a red circle with short cross arms."""
    color = (255, 0, 0)
    radius = 12
    arm_length = 20
    line_width = 3

    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        outline=color,
        width=line_width,
    )

    gap = radius + 1
    draw.line([(x - arm_length, y), (x - gap, y)], fill=color, width=line_width)
    draw.line([(x + gap, y), (x + arm_length, y)], fill=color, width=line_width)

    draw.line([(x, y - arm_length), (x, y - gap)], fill=color, width=line_width)
    draw.line([(x, y + gap), (x, y + arm_length)], fill=color, width=line_width)


def _draw_label(
    draw: ImageDraw,
    x: int,
    y: int,
    text: str,
) -> None:
    """Draw a red background label with white text above the crosshair."""
    bg_color = (200, 0, 0)
    text_color = (255, 255, 255)
    padding = 3
    CIRCLE_RADIUS = 12

    label_x = x + CIRCLE_RADIUS + 5
    label_y = y - 35

    label_x = max(0, label_x)
    label_y = max(0, label_y)

    bbox = draw.textbbox((label_x, label_y), text)

    draw.rounded_rectangle(
        [
            bbox[0] - padding,
            bbox[1] - padding,
            bbox[2] + padding,
            bbox[3] + padding,
        ],
        fill=bg_color,
        radius=3,
    )

    draw.text((label_x, label_y), text, fill=text_color)
