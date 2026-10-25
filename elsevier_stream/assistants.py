"""Set up a research folder for AI assistants.

``init_folder`` writes what Claude Code, Codex and Gemini CLI need to work
with elsevier-stream in a folder: the instructions (``AGENTS.md``, imported
by ``CLAUDE.md`` and ``GEMINI.md``) and the settings that start
elsevier-stream's MCP server (``.mcp.json`` for Claude Code,
``.codex/config.toml`` for Codex, ``.gemini/settings.json`` for Gemini CLI).
Existing files are kept, and settings are added to them rather than replaced.
Where the elsevier-stream plugin is installed, Claude Code or Codex has the
server in every folder already, so its settings get none, and lose one that
an earlier ``init`` added, or the assistant would list every tool twice.

It can also save the user's Elsevier API key and institutional token, which
belong to the person rather than the folder, in ``~/.elsevier-stream.json``.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .settings import API_KEY_SETTING, INSTTOKEN_SETTING, read_settings, set_setting, user_settings_file

PathLike = Union[str, Path]

INSTRUCTIONS_FILE = Path(__file__).parent / "data" / "AGENTS.md"
SERVER_NAME = "elsevier-stream"
PLUGIN = "elsevier-stream@"              # the plugin's id, followed by the marketplace it came from
SYNCED = PLUGIN + "synced"               # the copy Claude Code syncs from the claude.ai account
CODEX_TABLE = f"[mcp_servers.{SERVER_NAME}]"
# Claude Code loads synced plugins only in sessions signed in with the claude.ai account that fetch feature
# flags; these variables sign in another way, or stop the fetch
NO_SYNC_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
               "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")


def instructions() -> str:
    """The instructions for AI assistants, as shipped with elsevier-stream."""
    return INSTRUCTIONS_FILE.read_text(encoding="utf-8")


def server_command() -> Tuple[str, List[str]]:
    """The command that starts the MCP server, with the Python that has elsevier-stream installed."""
    return sys.executable, ["-m", "elsevier_stream", "mcp"]


def _claude_syncs_plugins(settings: List[Dict[str, Any]]) -> bool:
    """Whether Claude Code would load plugins synced from the claude.ai account, judged from the environment
    and its *settings* files: not where another credential signs in, or where ``syncClaudeAiPlugins`` is off."""
    env = dict(os.environ)
    for data in settings:
        if isinstance(data.get("env"), dict):
            env.update({name: str(value) for name, value in data["env"].items()})
    if any(env.get(name) for name in NO_SYNC_ENV) or any(data.get("apiKeyHelper") for data in settings):
        return False
    return settings[0].get("syncClaudeAiPlugins", True) is not False


def plugin_installed(assistant: str, folder: PathLike = ".") -> bool:
    """Whether the elsevier-stream plugin is enabled in Claude Code or Codex (*assistant*), for the user or *folder*.

    Claude Code merges ``enabledPlugins`` across its user, project and local
    settings one plugin id at a time, the most specific file that names an id
    deciding it.  An enabled marketplace copy counts, and wins over a copy
    synced from the claude.ai account, which counts unless ``elsevier-stream@synced``
    is off or the session would not load synced plugins.  When that cannot be
    told, the folder keeps its server: tools listed twice beat no tools.
    Codex enables a plugin with a ``[plugins."elsevier-stream@<marketplace>"]``
    table in ``config.toml``.
    """
    home, folder = Path.home(), Path(folder)
    if assistant == "claude":
        settings = [read_settings(path) for path in (home / ".claude" / "settings.json",
                                                     folder / ".claude" / "settings.json",
                                                     folder / ".claude" / "settings.local.json")]
        enabled: Dict[str, Any] = {}
        for data in settings:
            if isinstance(data.get("enabledPlugins"), dict):
                enabled.update(data["enabledPlugins"])
        ours = {name: bool(on) for name, on in enabled.items() if name.startswith(PLUGIN)}
        if any(on for name, on in ours.items() if name != SYNCED):
            return True
        synced = home / ".claude" / "plugins" / "synced"
        return (ours.get(SYNCED, True) and _claude_syncs_plugins(settings)
                and any(p.is_dir() for pattern in ("*/elsevier-stream", "*/elsevier-stream~*")
                        for p in synced.glob(pattern)))
    for path in (home / ".codex" / "config.toml", folder / ".codex" / "config.toml"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for table in re.finditer(r'^\[plugins\."elsevier-stream@[^"]*"\]\n(.*?)(?=^\[|\Z)', text, re.M | re.S):
            if re.search(r"^\s*enabled\s*=\s*true", table.group(1), re.M):
                return True
    return False


def _write_instructions(folder: Path, force: bool) -> str:
    path = folder / "AGENTS.md"
    if path.exists() and not force:
        return "kept"
    action = "updated" if path.exists() else "created"
    path.write_text(instructions(), encoding="utf-8")
    return action


def _import_instructions(path: Path) -> str:
    """CLAUDE.md and GEMINI.md import AGENTS.md with an @ line."""
    line = "@AGENTS.md"
    if not path.exists():
        path.write_text(f"{line}\n", encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    if any(row.strip() == line for row in text.splitlines()):
        return "kept"
    path.write_text(text.rstrip("\n") + f"\n\n{line}\n", encoding="utf-8")
    return "updated"


def _json_settings(path: Path, plugin: bool = False, **extra: Any) -> str:
    """Add the server to the ``mcpServers`` of a JSON settings file, as Claude Code and Gemini CLI read them.

    With the *plugin* installed, the file gets no server, and loses one an earlier ``init`` added.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None
    servers = data.setdefault("mcpServers", {})
    if plugin:
        if SERVER_NAME not in servers:
            return "plugin"
        del servers[SERVER_NAME]
    elif SERVER_NAME in servers:
        return "kept"
    else:
        command, args = server_command()
        servers[SERVER_NAME] = {"command": command, "args": args, **extra}
    action = "plugin" if plugin else "updated" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return action


def _codex_settings(folder: Path, plugin: bool = False) -> str:
    path = folder / ".codex" / "config.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    # the server's table, and any sub-table such as [mcp_servers.elsevier-stream.env], each to the next table
    tables = rf"^\[mcp_servers\.{re.escape(SERVER_NAME)}(\.[^\]]*)?\]\n(.*?)(?=^\[|\Z)"
    if plugin:
        if not re.search(tables, text, flags=re.M | re.S):
            return "plugin"
        text = re.sub(tables, "", text, flags=re.M | re.S)
        path.write_text(text.rstrip("\n") + "\n" if text.strip() else "", encoding="utf-8")
        return "plugin"
    if CODEX_TABLE in text:
        return "kept"
    command, args = server_command()
    # JSON strings are valid TOML basic strings; Codex forwards only the environment variables a server lists
    block = (f"[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(command)}\nargs = {json.dumps(args)}\n"
             'env_vars = ["ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"]\nstartup_timeout_sec = 60\ntool_timeout_sec = 600\n')
    action = "updated" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text.rstrip("\n") + "\n\n" if text.strip() else "") + block, encoding="utf-8")
    return action


def init_folder(
    folder: PathLike = ".",
    force: bool = False,
    api_key: Optional[str] = None,
    insttoken: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Prepare *folder* for Claude Code, Codex and Gemini CLI; returns ``(file, action)`` pairs.

    *force* rewrites ``AGENTS.md`` with the current instructions; the other
    files are always kept, with elsevier-stream's settings added.  Where the
    elsevier-stream plugin is installed, the settings of Claude Code or Codex
    get no server, with the action ``plugin``, because the plugin provides it
    in every folder.  *api_key* and *insttoken* are saved for the user, in the
    home folder, and that file is named by its full path.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    claude_plugin, codex_plugin = plugin_installed("claude", folder), plugin_installed("codex", folder)
    actions = [
        ("AGENTS.md", _write_instructions(folder, force)),
        ("CLAUDE.md", _import_instructions(folder / "CLAUDE.md")),
        ("GEMINI.md", _import_instructions(folder / "GEMINI.md")),
        (".mcp.json", _json_settings(folder / ".mcp.json", plugin=claude_plugin)),
        (".codex/config.toml", _codex_settings(folder, plugin=codex_plugin)),
        # Gemini CLI's timeout is in milliseconds; downloads can take minutes
        (".gemini/settings.json", _json_settings(folder / ".gemini" / "settings.json", timeout=600000)),
    ]
    for name, value in ((API_KEY_SETTING, api_key), (INSTTOKEN_SETTING, insttoken)):
        if value:
            actions.append((str(user_settings_file()), set_setting(user_settings_file(), name, value)))
    return actions
