"""The Claude Code and Codex plugin in plugins/elsevier-stream, its marketplaces, and the texts that must agree."""

import json
import re
from pathlib import Path

from elsevier_stream import __version__
from elsevier_stream.assistants import instructions
from elsevier_stream.mcp_server import INSTRUCTIONS, TOOLS

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "elsevier-stream"
RELEASE = f"elsevier-stream=={__version__}"
NUMBERS = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_the_manifests_name_the_package_version():
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        data = load(PLUGIN / manifest)
        assert data["name"] == "elsevier-stream" and data["version"] == __version__, manifest


def test_the_plugin_runs_the_release_of_its_own_version():
    codex = load(PLUGIN / ".codex-plugin" / "plugin.json")
    assert codex["mcpServers"] == "./.codex-plugin/mcp.json" and codex["skills"] == "./skills/"
    server = load(PLUGIN / ".codex-plugin" / "mcp.json")["mcpServers"]["elsevier-stream"]
    assert server["args"] == ["--from", RELEASE, "elsevier-stream", "mcp"]
    assert (server["startup_timeout_sec"], server["tool_timeout_sec"]) == (60, 600)
    assert not (PLUGIN / ".mcp.json").exists()   # Claude Code reads the server inline, so one server starts
    claude = load(PLUGIN / ".claude-plugin" / "plugin.json")
    inline = claude["mcpServers"]["elsevier-stream"]
    timeouts = {"startup_timeout_sec", "tool_timeout_sec"}
    assert {k: v for k, v in inline.items() if k != "env"} == {k: v for k, v in server.items() if k not in timeouts}
    assert inline["env"] == {"ELSEVIER_STREAM_API_KEY": "${user_config.elsevier_api_key}"}
    option = claude["userConfig"]["elsevier_api_key"]
    # Cowork ignores a server that references an option without a default; an empty key means none
    assert option["sensitive"] is True and option["default"] == "" and not option.get("required")


def test_the_skill_is_the_folder_instructions_under_a_plugin_note():
    skill = (PLUGIN / "skills" / "elsevier-search" / "SKILL.md").read_text(encoding="utf-8")
    assert re.match(r"---\nname: elsevier-search\ndescription: .+\n---\n", skill)
    assert f"elsevier-stream {__version__} through `uvx`" in skill and f'uvx --from "{RELEASE}"' in skill
    # Edit elsevier_stream/data/AGENTS.md, then copy it below the skill's header and note
    assert skill.endswith(instructions())


def test_the_instructions_name_every_tool():
    for tool in TOOLS:
        assert f"`{tool['name']}`" in instructions(), f"AGENTS.md does not name {tool['name']}"
        assert tool["name"] in INSTRUCTIONS, f"the server's instructions do not name {tool['name']}"
    count = f"{NUMBERS[len(TOOLS)]} MCP tools"
    assert count[0].upper() + count[1:] in read("plugins/elsevier-stream/README.md") and count in read("README.md")


def test_the_marketplaces_point_at_the_plugin():
    claude = load(ROOT / ".claude-plugin" / "marketplace.json")["plugins"]
    codex = load(ROOT / ".agents" / "plugins" / "marketplace.json")["plugins"]
    assert [(p["name"], p["source"]) for p in claude] == [("elsevier-stream", "./plugins/elsevier-stream")]
    assert [(p["name"], p["source"]["path"]) for p in codex] == [("elsevier-stream", "./plugins/elsevier-stream")]


def test_claude_mcp_add_is_for_every_folder():
    # without --scope user, Claude Code loads the server only in the folder where it was added
    for path in ("README.md", "elsevier_stream/cli.py", "elsevier_stream/mcp_server.py"):
        for line in read(path).splitlines():
            if "claude mcp add" in line:
                assert "claude mcp add --scope user" in line, f"{path}: {line.strip()}"


def test_the_key_never_reaches_git():
    ignored = read(".gitignore").splitlines()
    assert ".env" in ignored and "publications/" in ignored
