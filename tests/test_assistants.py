"""init: the folder's files, the plugin, and the key; and the command line around them."""

import json

import pytest

from elsevier_stream import cli
from elsevier_stream.assistants import init_folder, instructions, plugin_installed
from elsevier_stream.settings import read_settings, user_settings_file


def test_init_writes_and_merges(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My notes\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")

    actions = dict(init_folder(tmp_path))

    assert actions == {"AGENTS.md": "created", "CLAUDE.md": "updated", "GEMINI.md": "created",
                       ".mcp.json": "updated", ".codex/config.toml": "created", ".gemini/settings.json": "created"}
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == instructions()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# My notes\n\n@AGENTS.md\n"
    servers = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert set(servers) == {"other", "elsevier-stream"} and servers["elsevier-stream"]["args"][-2:] == [
        "elsevier_stream", "mcp"]
    codex = (tmp_path / ".codex" / "config.toml").read_text()
    assert 'env_vars = ["ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"]' in codex and "tool_timeout_sec = 600" in codex
    assert set(dict(init_folder(tmp_path)).values()) == {"kept"}


def test_init_leaves_the_server_to_the_plugin(tmp_path, home, monkeypatch):
    folder = tmp_path / "study"
    init_folder(folder)
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"elsevier-stream@elsevier-stream": True}}))
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text('[plugins."elsevier-stream@elsevier-stream"]\nenabled = true\n')

    actions = dict(init_folder(folder))
    assert actions[".mcp.json"] == "plugin" and actions[".codex/config.toml"] == "plugin"
    assert actions[".gemini/settings.json"] == "kept"             # Gemini CLI has no plugin
    assert json.loads((folder / ".mcp.json").read_text())["mcpServers"] == {}
    assert (folder / ".codex" / "config.toml").read_text() == ""

    # a synced copy counts where Claude Code loads it, not where another credential signs in
    (home / ".claude" / "settings.json").write_text("{}")
    assert not plugin_installed("claude", folder)
    (home / ".claude" / "plugins" / "synced" / "acct" / "elsevier-stream").mkdir(parents=True)
    assert plugin_installed("claude", folder)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    assert not plugin_installed("claude", folder)


def test_init_saves_the_key_and_the_token_for_the_user(tmp_path, home):
    file = home / ".elsevier-stream.json"
    actions = init_folder(tmp_path, api_key="k-1", insttoken="t-1")
    assert (str(file), "created") in actions and (str(file), "updated") in actions
    assert read_settings(user_settings_file()) == {"api_key": "k-1", "insttoken": "t-1"}


def test_cli_init_checks_the_key_before_saving_it(tmp_path, home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_api_key", lambda key: {"good": "ok", "bad": "invalid"}[key])
    assert cli.main(["init", str(tmp_path), "--api-key", "bad"]) == 1
    assert "rejected" in capsys.readouterr().err and not (home / ".elsevier-stream.json").exists()
    assert cli.main(["init", str(tmp_path), "--api-key", "good"]) == 0
    out = capsys.readouterr().out
    assert "Elsevier accepted the key." in out and "Elsevier API key: on (…good" in out


def test_cli_without_a_key_says_where_to_get_one(capsys):
    assert cli.main(["search", "TITLE(x)"]) == 2
    assert "dev.elsevier.com" in capsys.readouterr().err
    assert cli.main(["list", "missing-folder"]) == 1


def test_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert capsys.readouterr().out.startswith("elsevier-stream 0.")
