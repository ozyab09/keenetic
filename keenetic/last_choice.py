"""Stores the user's last choice in the last_choice.json file.

The file lives in the repository root (next to README.md, one level above the
package) and contains JSON:
    {"host": "<ip>", "mode": "collect|once", "port": <int>, "group": "<group_name>"}

The "group" field is the last selected DNS route group used for automatically
adding subnets. An empty string means the user explicitly declined auto-add;
in "once" mode the key is not overwritten.

Used to suggest the last choice by default in interactive prompts.
"""

import json
import os

# Keys of last_choice.json
KEY_HOST = "host"
KEY_MODE = "mode"
KEY_PORT = "port"
KEY_GROUP = "group"

# Default modes if the file is missing or corrupted
DEFAULT_MODE = "collect"
DEFAULT_PORT = 443


def _file_path() -> str:
    """Path to last_choice.json: the repository root.

    The package lives in <root>/keenetic/, so we go one level up
    from this module's directory.
    """
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(package_dir), "last_choice.json")


def load_last_choice(path: str | None = None) -> dict:
    """Reads the last choice from the file. Returns an empty dict on error."""
    file_path = path or _file_path()
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}
    # Keep only strings and numbers — valid values
    return {k: v for k, v in data.items() if isinstance(v, (str, int))}


def save_last_choice(host_ip: str, mode: str, port: int, group: str | None = None,
                     path: str | None = None) -> None:
    """Saves the last choice to the file (non-critical errors are ignored).

    group=None in "collect" mode is stored as an empty string
    (explicitly declined auto-add). In "once" mode the key is not touched.
    """
    file_path = path or _file_path()
    data = {KEY_HOST: host_ip, KEY_MODE: mode, KEY_PORT: port}
    if group is not None:
        data[KEY_GROUP] = group
    elif mode == "collect":
        data[KEY_GROUP] = ""  # "don't add automatically"
    else:
        # once mode — group is not selected, keep the previous value
        prev = load_last_choice(path)
        if KEY_GROUP in prev:
            data[KEY_GROUP] = prev[KEY_GROUP]
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[!] Failed to save {os.path.basename(file_path)}: {e}")
