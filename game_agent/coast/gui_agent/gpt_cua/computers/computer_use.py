import os
import platform
import time
import base64
import subprocess
from typing import List, Dict, Literal
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import mss
import pyautogui
from .computer import Computer


def _get_flash_window_bounds() -> tuple[int, int, int, int] | None:
    """Get the Flash window's position and size via xdotool.
    Returns (x, y, width, height) or None if window not found."""
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", "Flash", "--onlyvisible", "getwindowgeometry", "--shell", "%1"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            # Fallback: get first window matching "Flash"
            window_search = subprocess.run(
                ["xdotool", "search", "--name", "Flash"],
                capture_output=True, text=True, timeout=5
            )
            if window_search.returncode != 0 or not window_search.stdout.strip():
                return None
            win_id = window_search.stdout.strip().split("\n")[0]
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=5
            )
        
        if result.returncode == 0:
            # Parse output like: X=200\nY=100\nWIDTH=800\nHEIGHT=600\n...
            vals = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = int(v.strip())
            return (
                vals.get("X", 0),
                vals.get("Y", 0),
                vals.get("WIDTH", 0),
                vals.get("HEIGHT", 0),
            )
    except Exception:
        pass
    return None


class LocalDesktopComputer(Computer):
    def __init__(
        self,
        max_actions: int = 3,
        auto_crop: bool = True,
        game_name: str = "unknown",
        gui_agent: str = "unknown",
        reasoning_model: str = "unknown",
    ):
        os_name = platform.system().lower()
        if "darwin" in os_name:
            self._environment = "mac"
        elif "linux" in os_name:
            self._environment = "linux"
        else:
            self._environment = "windows"
        self._dimensions = pyautogui.size()

        self._action_count = 0
        self._max_actions = max_actions
        self._countable = ["click", "double_click", "scroll", "type", "keypress", "drag"]
        self._screenshot_count = 0

        # Screenshot saving metadata
        self._game_name = game_name
        self._gui_agent = gui_agent
        self._reasoning_model = reasoning_model

        # Crop region for game window
        self._auto_crop = auto_crop and os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
        self._crop_offset: tuple[int, int, int, int] | None = None  # (x, y, w, h)
        if self._auto_crop:
            self._crop_offset = _get_flash_window_bounds()
            if self._crop_offset:
                print(f"[INFO] Game window detected at: x={self._crop_offset[0]}, y={self._crop_offset[1]}, w={self._crop_offset[2]}, h={self._crop_offset[3]}")
                print(f"[INFO] Screenshots will be cropped to game window; action coordinates will be offset.")
            else:
                print("[WARN] Could not detect game window for cropping; using full screen.")
                self._auto_crop = False

    @property
    def environment(self) -> Literal["windows", "mac", "linux"]:
        return self._environment

    @property
    def dimensions(self) -> tuple[int, int]:
        return self._dimensions

    @property
    def action_count(self) -> int:
        return self._action_count

    @property
    def max_actions(self) -> int:
        return self._max_actions

    def _maybe_count(self, action_name: str):
        if action_name in self._countable:
            self._action_count += 1
            print(f"⬆️ 액션 카운터 증가: {self._action_count}/{self._max_actions}")

    def screenshot(self) -> str:
        if os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes"):
            with mss.mss() as sct:
                screenshot = sct.grab(sct.monitors[1])  # primary display
                img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        else:
            img = pyautogui.screenshot()

        # Crop to game window if detected
        if self._auto_crop and self._crop_offset:
            x, y, w, h = self._crop_offset
            img = img.crop((x, y, x + w, y + h))
            # Re-detect in case window moved
            new_offset = _get_flash_window_bounds()
            if new_offset:
                self._crop_offset = new_offset

        if os.environ.get("DEBUG_SAVE_SCREENSHOTS", "").lower() in ("1", "true", "yes"):
            self._screenshot_count += 1
            try:
                from coast.tools.screenshot import get_screenshot_dir
                directory = get_screenshot_dir("screenshots", self._reasoning_model, self._gui_agent, self._game_name)
            except Exception:
                # Fallback to env var or default
                directory = os.environ.get("SCREENSHOT_DIR", "./screenshots")
                os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, f"flash_screenshot_{self._screenshot_count:04d}.png")
            img.save(path)
            print(f"Debug screenshot saved: {path}")

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _offset(self, x: int, y: int) -> tuple[int, int]:
        """Add crop offset back to screen-space coordinates."""
        if self._crop_offset:
            ox, oy = self._crop_offset[0], self._crop_offset[1]
            return x + ox, y + oy
        return x, y

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._maybe_count("click")
        sx, sy = self._offset(x, y)
        pyautogui.click(x=sx, y=sy, button=button)

    def double_click(self, x: int, y: int) -> None:
        self._maybe_count("double_click")
        sx, sy = self._offset(x, y)
        pyautogui.doubleClick(x=sx, y=sy)

    def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        self._maybe_count("scroll")
        sx, sy = self._offset(x, y)
        pyautogui.moveTo(sx, sy)
        pyautogui.scroll(scroll_y)

    def type(self, text: str) -> None:
        self._maybe_count("type")
        pyautogui.write(text)

    def wait(self, ms: int = 1000) -> None:
        time.sleep(ms / 1000)

    def move(self, x: int, y: int) -> None:
        sx, sy = self._offset(x, y)
        pyautogui.moveTo(sx, sy)

    def keypress(self, keys: List[str]) -> None:
        self._maybe_count("keypress")
        for key in keys:
            pyautogui.keyDown(key)
        for key in reversed(keys):
            pyautogui.keyUp(key)

    def drag(self, path: List[Dict[str, int]]) -> None:
        self._maybe_count("drag")
        if not path:
            return
        points = [self._offset(p["x"], p["y"]) for p in path]
        pyautogui.moveTo(points[0][0], points[0][1])
        pyautogui.mouseDown()
        for px, py in points[1:]:
            pyautogui.moveTo(px, py)
        pyautogui.mouseUp()

    def get_current_url(self) -> str:
        return "file://local-desktop"

    def reset_action_counter(self):
        self._action_count = 0