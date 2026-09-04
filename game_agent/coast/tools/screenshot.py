import os
import subprocess
import mss


def _get_flash_window_bounds():
    """Get the Flash window's position and size via xdotool.
    Returns (x, y, width, height) or None."""
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", "Flash", "getwindowgeometry", "--shell", "%1"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
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
            vals = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = int(v.strip())
            return (vals.get("X", 0), vals.get("Y", 0),
                    vals.get("WIDTH", 0), vals.get("HEIGHT", 0))
    except Exception:
        pass
    return None


def get_screenshot_dir(base_dir, reasoning_model, gui_agent, game_name):
    """Creates a directory based on game/model/agent."""
    directory = os.path.join(base_dir, gui_agent, reasoning_model, game_name)
    os.makedirs(directory, exist_ok=True)
    return directory

def get_next_screenshot_filename(directory):
    """Generates the next sequential screenshot filename in the given directory."""
    existing_files = [
        f for f in os.listdir(directory)
        if f.startswith("flash_screenshot_") and f.endswith(".png")
    ]

    numbers = []
    for filename in existing_files:
        try:
            num_str = filename.replace("flash_screenshot_", "").replace(".png", "")
            numbers.append(int(num_str))
        except ValueError:
            continue

    next_num = max(numbers, default=0) + 1
    return f"flash_screenshot_{next_num:04d}.png"

def capture_flash_screenshot(game_name, gui_model, reasoning_model, time=None):
    """
    Captures the entire screen (or just the Flash game window if detected)
    and saves it to a folder based on GUI agent / model.
    """
    if time not in (None, "", "after", "final"):
        raise ValueError("Invalid value for 'time'. Use 'after', 'final', or leave it empty.")

    if time == "after":
        base_dir = "screenshots_after"
    elif time == "final":
        base_dir = "screenshots_final"
    else:
        base_dir = "screenshots"

    directory = get_screenshot_dir(base_dir, gui_model, reasoning_model, game_name)
    filename = get_next_screenshot_filename(directory)
    screenshot_path = os.path.join(directory, filename)

    from PIL import Image
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    crop = _get_flash_window_bounds()
    if crop:
        x, y, w, h = crop
        img = img.crop((x, y, x + w, y + h))
        print(f"[INFO] Cropped screenshot to game window: {x},{y} {w}x{h}")

    img.save(screenshot_path)

    print(f"[INFO] Screenshot saved to: {screenshot_path}")
    return screenshot_path