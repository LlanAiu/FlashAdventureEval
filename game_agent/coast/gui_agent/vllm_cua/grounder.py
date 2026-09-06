"""
Grounding stage for vllm_cua.

Calls UGround-V1-7B (via a separate vLLM instance) to convert a textual
description into precise pixel coordinates on the given screenshot.

UGround normalizes outputs to ``(x_ratio, y_ratio)`` in ``[0, 1000]``.
This module parses that output and scales it to the image dimensions.
"""

import asyncio
import os
import re
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

UGROUND_USER_PROMPT = (
    "Your task is to help the user identify the precise coordinates "
    "(x, y) of a specific area/element/object on the screen based on a description.\n"
    "Description: {description}\n"
    "Answer:"
)

async def ground(
    *,
    screenshot_base64: str,
    description: str,
    image_width: int,
    image_height: int,
    model: Optional[str] = None,
    max_retries: int = 3,
) -> tuple[int, int]:
    """
    Ground a textual description to pixel coordinates on the screenshot.

    Parameters
    ----------
    screenshot_base64 : str
        Base64-encoded PNG screenshot.
    description : str
        Natural-language description of the target element (e.g.
        "the red key under the vase").
    image_width, image_height : int
        Pixel dimensions of the screenshot (the cropped game window).
    model : str | None
        Override model name (falls back to ``UGROUND_MODEL`` env var).
    max_retries : int
        Number of API retries before giving up.

    Returns
    -------
    (x, y) : tuple of ints
        Pixel coordinates in the cropped image's space.

    Raises
    ------
    ValueError
        If grounding fails after all retries or the output is unparseable.
    """
    load_dotenv()

    base_url = os.getenv("UGROUND_BASE_URL", "http://127.0.0.1:9073/v1")
    model = model or os.getenv("UGROUND_MODEL") or "osunlp/UGround-V1-7B"

    response = await _call_uground(
        screenshot_base64,
        description,
        base_url=base_url,
        model=model,
        max_retries=max_retries,
    )

    if response is None:
        raise ValueError(f"[Ground] UGround API failed after {max_retries} retries")

    coords = _parse_coordinates(response, image_width, image_height)
    if coords is None:
        raise ValueError(
            f"[Ground] Could not parse coordinates from UGround output: {response}"
        )

    print(f"[Ground] {description} → ({coords[0]}, {coords[1]})")
    return coords

async def _call_uground(
    screenshot_base64: str,
    description: str,
    *,
    base_url: str,
    model: str,
    max_retries: int = 3,
) -> str | None:
    """
    Call the UGround model directly via its OpenAI-compatible vLLM endpoint.

    Returns the raw text response, or ``None`` on persistent failure.
    """
    client = OpenAI(base_url=base_url, api_key="vllm")
    prompt = UGROUND_USER_PROMPT.format(description=description)

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{screenshot_base64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    },
                ],
                temperature=0,
                max_tokens=64,
            )
            raw = response.choices[0].message.content
            
            if raw is None:
                print(f"[Ground] API returned None (attempt {attempt + 1})")
                continue
            
            raw = raw.strip()
            print(f"[Ground] Model response (attempt {attempt + 1}):\n{raw}")
            
            return raw
           
        except Exception as e:
            print(f"[Ground] API call failed (attempt {attempt + 1}/{max_retries}): {e}")
            await asyncio.sleep(1.5)

    return None

def _parse_coordinates(raw: str, width: int, height: int) -> tuple[int, int] | None:
    """
    Parse UGround's ``(x_ratio, y_ratio)`` output and scale to pixels.

    UGround returns values in ``[0, 1000]``.  This extracts the two
    floats and converts them:

        x_px = round(x_ratio / 1000 * width)
        y_px = round(y_ratio / 1000 * height)
    """
    match = re.search(r"[\(?\s*]?([\d]+\.?\d*)\s*,\s*([\d]+\.?\d*)[\)?\s*]", raw)
    if not match:
        return None

    x_ratio = float(match.group(1))
    y_ratio = float(match.group(2))

    x = round(x_ratio / 1000 * width)
    y = round(y_ratio / 1000 * height)

    return x, y