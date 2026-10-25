"""elsevier-stream as an MCP server, for Claude Code, Codex and other AI assistants.

The Model Context Protocol (https://modelcontextprotocol.io) lets an AI
assistant call tools directly instead of typing shell commands.  This server
speaks it over standard input and output with no extra dependencies.  The
assistant starts it as ``elsevier-stream mcp``: through the plugin in
plugins/elsevier-stream, which runs a release with ``uvx``; through the
settings ``elsevier-stream init`` writes in a research folder; or after
registering it by hand:

    claude mcp add --scope user elsevier-stream -- elsevier-stream mcp
    codex mcp add elsevier-stream -- elsevier-stream mcp

Each tool returns compact text, so the assistant reads abstracts and counts
rather than whole records.  Relative paths are resolved against the folder
the server started in, or ``--root``.
"""

import contextlib
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

from . import __version__
from .client import (API_KEY_ENV, PLUGIN_API_KEY_ENV, ElsevierError, NoApiKey, api_key_status,
                     configured_api_key)
from .corpus import list_articles, most_cited, select, short_id
from .download import download
from .export import export_citations
from .sciencedirect import search_sciencedirect
from .scopus import search_scopus
from .settings import API_KEY_SETTING, saved_setting, set_setting, user_settings_file

logger = logging.getLogger(__name__)

ProgressFn = Callable[[float, int, str], None]

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """elsevier-stream searches Scopus, which indexes the journals of every major publisher, and
ScienceDirect, Elsevier's own journals, and saves each article's Scopus record (abstract, authors, keywords,
references, citation count) in the researcher's folder, with the full text where their institution entitles them.
It saves every article it reads, so the report can be checked and the study kept.
Work in this order: search_scopus to size and refine a search (aim for 50-300 on-topic matches; TITLE-ABS-KEY(),
TITLE(), PUBYEAR > 2019 and DOCTYPE(re) narrow it), download, list_articles to scan titles, list_articles with
ids and abstracts=true to read chosen abstracts, read_article to search inside a saved full text, and most_cited
for the works the downloads cite most. search_sciencedirect searches Elsevier's full texts for words and marks
open access. export_citations writes BibTeX or RIS for a reference manager.
Cite only articles whose abstract or text you read here, by DOI and PMID; never cite from memory. Say what kind
of evidence each is, which you read only as abstracts, and what could not be read, and report each search with
its count. Each article uses the weekly quota of the researcher's API key: ask before downloading more than 200.
Long calls report their progress; wait for them rather than calling again."""

NO_KEY_NOTE = """
No Elsevier API key is configured, so every tool will fail. Tell the researcher to create a key at
https://dev.elsevier.com/apikey/manage and save it by running `elsevier-stream init --api-key THE-KEY` in a
terminal, or with `/plugin configure elsevier-stream@elsevier-stream` in Claude Code when elsevier-stream is a
plugin. Never ask for the key in the conversation."""

PATH_PARAM = {"type": "string", "description": "Folder of downloads, relative to the project",
              "default": "publications"}
IDS_PARAM = {"type": "array", "items": {"type": "string"},
             "description": "Articles by DOI, Scopus ID (2-s2.0-...) or PubMed ID"}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "search_scopus",
        "title": "Size a Scopus search",
        "description": "Count a Scopus search and list its newest matches, without saving anything. Scopus "
                       "indexes the journals of every major publisher. Use its syntax: TITLE-ABS-KEY(...), "
                       "TITLE(...), ABS(...), PUBYEAR > 2019, DOCTYPE(ar) or DOCTYPE(re), AND, OR, AND NOT, "
                       "{exact phrase}, W/3 for nearby words.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "Scopus search, e.g. TITLE(\"gut microbiota\") AND TITLE-ABS-KEY(frailty)"},
            "show": {"type": "integer", "description": "How many of the newest matches to list (0 for the count)",
                     "default": 10, "minimum": 0, "maximum": 100},
        }, "required": ["query"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "search_sciencedirect",
        "title": "Search ScienceDirect",
        "description": "Count a search of the full texts of Elsevier's journals and books on ScienceDirect, and "
                       "list the newest matches, marking open access. Plain words; no field tags.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words to search for, e.g. gut microbiota frailty"},
            "show": {"type": "integer", "default": 10, "minimum": 0, "maximum": 100},
            "open_access": {"type": "boolean", "default": False, "description": "Only open-access articles"},
        }, "required": ["query"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "download",
        "title": "Save a search's articles",
        "description": "Save the Scopus records of a search's newest matches, one JSON file per article, into "
                       "<output_dir>/<folder named after the search>: abstract, authors, keywords, references, and "
                       "the full text of ScienceDirect articles where the key and network are entitled. Existing "
                       "files are skipped. Each article uses the key's weekly quota.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Scopus search, checked first with search_scopus"},
            "max_results": {"type": "integer", "default": 30, "minimum": 1, "maximum": 500},
            "output_dir": PATH_PARAM,
            "references": {"type": "boolean", "default": True,
                           "description": "Also save each article's reference list, which most_cited needs"},
        }, "required": ["query"]},
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "name": "list_articles",
        "title": "List saved articles",
        "description": "One line per saved article, newest first: year, DOI, PMID, title, journal, citation count, "
                       "and whether the full text was saved. With ids, only those; with abstracts, their abstracts.",
        "inputSchema": {"type": "object", "properties": {
            "path": PATH_PARAM,
            "ids": IDS_PARAM,
            "abstracts": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1},
        }},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read_article",
        "title": "Read a saved full text",
        "description": "The full text of one saved article, or with find, only the paragraphs that mention a term. "
                       "Only articles whose full text was saved; list_articles shows which.",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string", "description": "DOI, Scopus ID or PubMed ID"},
            "find": {"type": "string", "description": "Return only paragraphs containing this term"},
            "path": PATH_PARAM,
            "max_chars": {"type": "integer", "default": 6000, "minimum": 500},
        }, "required": ["id"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "most_cited",
        "title": "Most cited works",
        "description": "The works cited by the most saved articles: the field's foundations, matched by Scopus ID. "
                       "Needs the reference lists download saves.",
        "inputSchema": {"type": "object", "properties": {
            "path": PATH_PARAM,
            "n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
        }},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "export_citations",
        "title": "Export citations",
        "description": "Write the saved articles, or chosen ones, as a BibTeX or RIS file that Zotero, EndNote or "
                       "Mendeley imports. Give the researcher the file's path.",
        "inputSchema": {"type": "object", "properties": {
            "path": PATH_PARAM,
            "format": {"type": "string", "enum": ["bibtex", "ris"], "default": "bibtex"},
            "ids": IDS_PARAM,
            "file": {"type": "string", "description": "File to write, relative to the project",
                     "default": "citations.bib"},
        }},
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                        "openWorldHint": False},
    },
]


class ToolError(Exception):
    """A problem the assistant should read as the tool's result, not a protocol error."""


def _line(r: Dict[str, Any]) -> str:
    pmid = f"  PMID {r['pmid']}" if r.get("pmid") else ""
    journal = f" ({r['journal']})" if r.get("journal") else ""
    cited = f"  cited by {r['cited_by']}" if r.get("cited_by") is not None else ""
    kind = f" [{r['type']}]" if r.get("type") and r["type"] != "Article" else ""
    return f"{r.get('year') or 'n.d.'}  {short_id(r)}{pmid}  {r.get('title') or ''}{journal}{kind}{cited}"


class Server:
    """Answers MCP requests; one instance per connection."""

    def __init__(self, root: Path, stdout=None) -> None:
        self.root = root
        self.stdout = stdout                # the protocol stream, for notifications during a tool call
        self.adopted_plugin_key = False     # saved the plugin's key for the command line, or given up
        self.handlers: Dict[str, Callable[[Dict[str, Any], Optional[ProgressFn]], str]] = {
            "search_scopus": self.search_scopus,
            "search_sciencedirect": self.search_sciencedirect,
            "download": self.download,
            "list_articles": self.list_articles,
            "read_article": self.read_article,
            "most_cited": self.most_cited,
            "export_citations": self.export_citations,
        }

    def path(self, value: Optional[str]) -> Path:
        path = Path(value or "publications")
        return path if path.is_absolute() else self.root / path

    # -- tools ---------------------------------------------------------------

    def search_scopus(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        return str(search_scopus(args["query"], max_results=int(args.get("show", 10))))

    def search_sciencedirect(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        return str(search_sciencedirect(args["query"], max_results=int(args.get("show", 10)),
                                        open_access=bool(args.get("open_access"))))

    def download(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        stats = download(args["query"], max_results=int(args.get("max_results", 30)),
                         output_dir=self.path(args.get("output_dir")), references=args.get("references", True) is not False,
                         progress=progress)
        note = ("\nFull texts need the researcher's institution: its network, or an institutional token saved with "
                "'elsevier-stream init --insttoken'. The abstracts were saved." if stats.not_entitled else "")
        return str(stats) + note

    def records(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            raise ToolError(f"{path} does not exist; download a search first")
        records = list_articles(path)
        if not records:
            raise ToolError(f"No saved articles in {path}")
        return records

    def list_articles(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        path = self.path(args.get("path"))
        records = self.records(path)
        lines = []
        if args.get("ids"):
            records, missing = select(records, args["ids"])
            if missing:
                lines.append(f"Not saved: {', '.join(missing)}")
        total = len(records)
        if args.get("limit"):
            records = records[:int(args["limit"])]
        lines.insert(0, f"{len(records)} of {total} articles in {path.name}")
        for r in records:
            lines.append(_line(r) + (f" [{r['words']:,} words]" if r["full_text"] else " [abstract only]"))
            if args.get("abstracts"):
                lines.append(f"    {r['abstract'] or '(no abstract)'}")
        return "\n".join(lines)

    def read_article(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        chosen, _ = select(self.records(self.path(args.get("path"))), [args["id"]])
        if not chosen:
            raise ToolError(f"{args['id']} is not among the saved articles")
        record = chosen[0]
        if not record["full_text"]:
            raise ToolError(f"Only the abstract of {args['id']} was saved; list_articles with abstracts=true shows it")
        text = json.loads(Path(record["file"]).read_text(encoding="utf-8")).get("text") or ""
        term = (args.get("find") or "").strip()
        limit = int(args.get("max_chars", 6000))
        if term:
            hits = [f"[{i}] {p}" for i, p in enumerate(text.splitlines(), 1) if term.lower() in p.lower()]
            body = "\n".join(hits) if hits else f'No paragraph mentions "{term}".'
            note = f'{len(hits)} paragraphs mention "{term}":'
        else:
            body, note = text, f"{len(text.split()):,} words:"
        if len(body) > limit:
            body = body[:limit] + f"\n... (cut at {limit:,} characters; use find, or raise max_chars)"
        return f"{_line(record)}\n{note}\n{body}"

    def most_cited(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        path = self.path(args.get("path"))
        count = len(self.records(path))
        works = most_cited(path, int(args.get("n", 10)))
        if not works:
            raise ToolError(f"The {count} articles in {path.name} were saved without reference lists")
        lines = [f"Works cited most by the {count} articles in {path.name}:"]
        for w in works:
            ref = f"DOI {w['doi']}" if w.get("doi") else w.get("eid") or ""
            pmid = f"  PMID {w['pmid']}" if w.get("pmid") else ""
            lines.append(f"cited by {w['cited_by']}  {ref}{pmid}  {w.get('year') or 'n.d.'}  {w.get('title') or ''}")
        return "\n".join(lines)

    def export_citations(self, args: Dict[str, Any], progress: Optional[ProgressFn] = None) -> str:
        fmt = args.get("format", "bibtex")
        path = self.path(args.get("path"))
        self.records(path)   # reports a missing or empty folder
        text, count, missing = export_citations(path, fmt, args.get("ids"))
        if not count:
            raise ToolError(f"None of {', '.join(missing)} is among the saved articles")
        target = self.path(args.get("file") or ("citations.bib" if fmt == "bibtex" else "citations.ris"))
        target.write_text(text, encoding="utf-8")
        note = f" Not saved: {', '.join(missing)}." if missing else ""
        return f"Wrote {count} citations ({fmt}) to {target.resolve()}.{note}"

    # -- protocol ------------------------------------------------------------

    def call_tool(self, name: str, args: Dict[str, Any], progress_token: Any = None) -> Dict[str, Any]:
        handler = self.handlers.get(name)
        if handler is None:
            raise KeyError(name)
        try:
            with contextlib.redirect_stdout(io.StringIO()):   # stdout belongs to the protocol
                text = handler(args, self.progress_reporter(progress_token))
            self.adopt_plugin_key()
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except ToolError as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        except NoApiKey as e:
            return {"content": [{"type": "text", "text": f"Error: {e}{NO_KEY_NOTE}"}], "isError": True}
        except ElsevierError as e:
            return {"content": [{"type": "text", "text": f"Error from Elsevier: {e}"}], "isError": True}
        except requests.RequestException as e:
            return {"content": [{"type": "text", "text": f"Error: could not reach Elsevier: {e}"}], "isError": True}
        except (KeyError, TypeError, ValueError, OSError) as e:
            return {"content": [{"type": "text", "text": f"Error: {type(e).__name__}: {e}"}], "isError": True}

    def adopt_plugin_key(self) -> None:
        """After a call that worked, save the Claude Code plugin's key for the command line and ``init``,
        once, when no key is saved or set."""
        key = os.getenv(PLUGIN_API_KEY_ENV)
        if not key or self.adopted_plugin_key:
            return
        self.adopted_plugin_key = True
        if os.getenv(API_KEY_ENV) or saved_setting(API_KEY_SETTING):
            return
        try:
            set_setting(user_settings_file(), API_KEY_SETTING, key)
            logger.warning("saved the plugin's Elsevier API key in %s for the command line", user_settings_file())
        except (OSError, ValueError) as e:
            logger.warning("could not save the plugin's Elsevier API key for the command line: %s", e)

    def notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send the client a notification, which may arrive between a request and its response."""
        if self.stdout is None:
            return
        line = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False)
        self.stdout.write(line.encode("utf-8") + b"\n")
        self.stdout.flush()

    def progress_reporter(self, token: Any) -> Optional[ProgressFn]:
        """A callback that reports a long tool call's progress, when the client asked for it with a token."""
        if token is None or self.stdout is None:
            return None
        last = -1.0

        def report(done: float, total: int, message: str) -> None:
            nonlocal last
            if done <= last:   # the protocol wants progress to increase with every notification
                return
            last = done
            self.notify("notifications/progress",
                        {"progressToken": token, "progress": done, "total": total, "message": message})
        return report

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The response to one JSON-RPC message, or None for a notification."""
        method, msg_id = message.get("method"), message.get("id")
        if msg_id is None:
            return None   # notifications, such as notifications/initialized
        params = message.get("params") or {}
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                result: Dict[str, Any] = {
                    "protocolVersion": requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "elsevier-stream", "title": "elsevier-stream", "version": __version__},
                    "instructions": INSTRUCTIONS + ("" if configured_api_key(str(self.root)) else NO_KEY_NOTE),
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    token = (params.get("_meta") or {}).get("progressToken")
                    result = self.call_tool(params.get("name"), params.get("arguments") or {}, token)
                except KeyError:
                    return _error(msg_id, -32602, f"Unknown tool: {params.get('name')}")
            else:
                return _error(msg_id, -32601, f"Method not found: {method}")
        except Exception as e:   # never let one request end the session
            logger.exception("Request %s failed", method)
            return _error(msg_id, -32603, f"Internal error: {e}")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


# The programs that may be attached to a console Windows opened for the server alone: uv, the launchers, Python
OWN_CONSOLE_IMAGES = {"uv.exe", "uvx.exe", "python.exe", "pythonw.exe", "elsevier-stream.exe"}


def console_processes() -> List[str]:
    """On Windows, the image names of the processes attached to this process's console; elsewhere, or when
    there is no console, an empty list. A process that cannot be inspected is listed as ``?``."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    pids = (wintypes.DWORD * 64)()
    count = kernel32.GetConsoleProcessList(pids, 64)
    if count > 64:
        pids = (wintypes.DWORD * count)()
        count = kernel32.GetConsoleProcessList(pids, count)
    names = []
    for pid in pids[:count]:
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            names.append("?")
            continue
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            names.append(Path(buffer.value).name if ok else "?")
        finally:
            kernel32.CloseHandle(handle)
    return names


def console_is_own(names: List[str]) -> bool:
    """Whether a console holding the processes *names* can only be one Windows opened for the server."""
    return bool(names) and all(name.lower() in OWN_CONSOLE_IMAGES for name in names)


def hide_own_console() -> bool:
    """Hide the console window that Windows opens when a desktop app starts the server, and only that one.

    In a terminal the server shares the terminal's console with the shell and
    the assistant and must leave it alone, so the window is hidden only when
    every process attached to the console is uv, a launcher or Python.
    """
    if not console_is_own(console_processes()):
        return False
    import ctypes

    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if not hwnd:
        return False
    ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    return True


def serve(root: Optional[Path] = None, stdin=None, stdout=None) -> None:
    """Answer MCP messages, one JSON object per line, until standard input closes."""
    try:
        if hide_own_console():
            logger.info("hid the console window Windows opened for the server")
    except Exception as e:   # a missing API or an odd console: the window stays, the server runs
        logger.debug("could not hide the console window: %s", e)
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    server = Server(Path(root or Path.cwd()).resolve(), stdout)
    logger.warning("elsevier-stream MCP server %s: files are read and saved under %s; Elsevier API key %s",
                   __version__, server.root, api_key_status(str(server.root)))
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            responses = [_error(None, -32700, "Parse error")]
        else:
            batch = message if isinstance(message, list) else [message]
            responses = [r for r in (server.handle(m) for m in batch if isinstance(m, dict)) if r is not None]
        for response in responses:
            stdout.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
