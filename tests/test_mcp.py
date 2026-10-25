"""The MCP server: the protocol, the tools, progress, and the key."""

import importlib
import io
import json
import sys

from conftest import abstract_record, params, reference, reference_page, scopus_entry, scopus_page

import elsevier_stream.mcp_server as mcp
from elsevier_stream.download import download
from elsevier_stream.mcp_server import TOOLS, Server, serve
from elsevier_stream.settings import read_settings, user_settings_file

# the package exports a function named download, which hides the module of that name
DOWNLOAD_MODULE = importlib.import_module("elsevier_stream.download")


def rpc(server, method, params=None, msg_id=1):
    return server.handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})


def text(result):
    return result["result"]["content"][0]["text"]


def routes():
    def abstract(request):
        n = int(request.url.split("/abstract/eid/")[1].split("?")[0].split("-")[-1])
        if params(request)["view"] == "REF":
            return reference_page([reference(1)], 1)
        return abstract_record(n)
    return {"search/scopus": scopus_page([scopus_entry(1), scopus_entry(2)], 53), "abstract/eid": abstract}


def test_initialize_lists_tools_and_says_when_no_key_is_configured(tmp_path, monkeypatch):
    server = Server(tmp_path)
    result = rpc(server, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert result["protocolVersion"] == "2025-06-18" and result["serverInfo"]["name"] == "elsevier-stream"
    assert "Cite only articles" in result["instructions"] and "No Elsevier API key" in result["instructions"]
    monkeypatch.setenv("ELSEVIER_API_KEY", "k")
    assert "No Elsevier API key" not in rpc(server, "initialize")["result"]["instructions"]
    assert [t["name"] for t in rpc(server, "tools/list")["result"]["tools"]] == [
        "search_scopus", "search_sciencedirect", "download", "list_articles", "read_article", "most_cited",
        "export_citations"]
    assert all(t["inputSchema"]["type"] == "object" for t in TOOLS)
    assert rpc(server, "nope")["error"]["code"] == -32601
    assert rpc(server, "tools/call", {"name": "nope"})["error"]["code"] == -32602


def test_a_tool_without_a_key_explains_how_to_add_one(tmp_path):
    reply = rpc(Server(tmp_path), "tools/call", {"name": "search_scopus", "arguments": {"query": "x"}})
    assert reply["result"]["isError"] and "dev.elsevier.com" in text(reply)


def test_search_download_list_read_and_export(tmp_path, monkeypatch, fake):
    client, _ = fake(routes())
    monkeypatch.setattr("elsevier_stream.scopus.Client", lambda: client)
    monkeypatch.setattr(DOWNLOAD_MODULE, "Client", lambda: client)
    client.close = lambda: None
    server = Server(tmp_path)

    found = text(rpc(server, "tools/call", {"name": "search_scopus", "arguments": {"query": "TITLE(x)", "show": 1}}))
    assert found.startswith("53 articles in Scopus") and "2-s2.0-1" in found
    saved = text(rpc(server, "tools/call", {"name": "download", "arguments": {"query": "TITLE(x)", "max_results": 2}}))
    assert "2 saved" in saved and str(tmp_path / "publications") in saved

    listing = text(rpc(server, "tools/call", {"name": "list_articles",
                                              "arguments": {"ids": ["10.1000/x1", "missing"], "abstracts": True}}))
    assert "1 of 1 articles" in listing and "Not saved: missing" in listing and "[abstract only]" in listing
    assert "Abstract 1: butyrate rose" in listing
    reply = rpc(server, "tools/call", {"name": "read_article", "arguments": {"id": "10.1000/x1"}})
    assert reply["result"]["isError"] and "Only the abstract" in text(reply)
    assert "cited by 2" in text(rpc(server, "tools/call", {"name": "most_cited", "arguments": {}}))
    written = text(rpc(server, "tools/call", {"name": "export_citations", "arguments": {"format": "ris"}}))
    assert written.startswith("Wrote 2 citations (ris)") and (tmp_path / "citations.ris").exists()


def test_read_article_finds_paragraphs_in_a_saved_full_text(tmp_path, fake):
    client, _ = fake(routes())
    download("x", 1, output_dir=tmp_path / "publications", client=client)
    file = tmp_path / "publications" / "x" / "2-s2.0-1.json"
    record = json.loads(file.read_text(encoding="utf-8"))
    record["text"] = "Methods\nStool was frozen at -80 C.\nResults\nButyrate rose."
    file.write_text(json.dumps(record), encoding="utf-8")

    server = Server(tmp_path)
    found = text(rpc(server, "tools/call", {"name": "read_article", "arguments": {"id": "2-s2.0-1", "find": "frozen"}}))
    assert '1 paragraphs mention "frozen"' in found and "[2] Stool was frozen" in found
    whole = text(rpc(server, "tools/call", {"name": "read_article", "arguments": {"id": "30000001"}}))   # by PMID
    assert "10 words:" in whole
    reply = rpc(server, "tools/call", {"name": "read_article", "arguments": {"id": "10.9999/none"}})
    assert reply["result"]["isError"] and "not among the saved articles" in text(reply)


def test_progress_notifications_and_the_plugin_key_saved_for_the_command_line(tmp_path, monkeypatch, fake):
    client, _ = fake(routes())
    client.close = lambda: None
    monkeypatch.setattr(DOWNLOAD_MODULE, "Client", lambda: client)
    monkeypatch.setenv("ELSEVIER_STREAM_API_KEY", "plugin-key")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "download", "arguments": {"query": "x", "max_results": 2}, "_meta": {"progressToken": 7}}},
    ]
    stdout = io.BytesIO()
    serve(tmp_path, stdin=io.BytesIO(("\n".join(json.dumps(m) for m in messages) + "\nnot json\n").encode()),
          stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().decode().splitlines()]
    progress = [m["params"] for m in lines if m.get("method") == "notifications/progress"]
    assert [p["progress"] for p in progress] == [1, 2] and all(p["progressToken"] == 7 for p in progress)
    assert [m.get("id") for m in lines if "method" not in m] == [1, 2, None]
    assert read_settings(user_settings_file()) == {"api_key": "plugin-key"}


def test_console_is_hidden_only_when_it_holds_only_the_server():
    assert mcp.console_is_own(["uvx.exe", "python.exe"]) and mcp.console_is_own(["ELSEVIER-STREAM.EXE"])
    assert not mcp.console_is_own(["cmd.exe", "python.exe"]) and not mcp.console_is_own([])
    if sys.platform != "win32":
        assert mcp.console_processes() == [] and mcp.hide_own_console() is False
