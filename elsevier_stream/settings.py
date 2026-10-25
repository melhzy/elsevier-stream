"""elsevier-stream's own settings.

The user's settings live in ``~/.elsevier-stream.json``, one key per setting:
the Elsevier API key (``api_key``), which ``elsevier-stream init --api-key``
saves there, and an optional institutional token (``insttoken``) for full
texts outside the institution's network.  A ``.env`` file in the current
folder with ``ELSEVIER_API_KEY=...`` works too.

This module imports nothing from the package, so every layer can read it.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

PathLike = Union[str, Path]

SETTINGS_FILE = ".elsevier-stream.json"
API_KEY_SETTING = "api_key"
INSTTOKEN_SETTING = "insttoken"


def user_settings_file() -> Path:
    """The user's settings file, in the home folder."""
    return Path.home() / SETTINGS_FILE


def read_settings(path: PathLike) -> Dict[str, Any]:
    """The settings in *path*, or none when the file is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_setting(path: PathLike, key: str, value: Any) -> str:
    """Save ``key: value`` in the JSON file *path*, keeping its other keys; returns created, updated or kept.

    A file that is not valid JSON raises rather than being replaced.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    if path.exists() and data.get(key) == value:
        return "kept"
    action = "updated" if path.exists() else "created"
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return action


def saved_setting(name: str) -> Optional[str]:
    """A setting saved for the user, if any."""
    return read_settings(user_settings_file()).get(name) or None


def dotenv_value(name: str, folder: PathLike = ".") -> Optional[str]:
    """The value of *name* in a ``.env`` file in *folder*, if any, without surrounding quotes."""
    try:
        lines = (Path(folder) / ".env").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            return value or None
    return None
