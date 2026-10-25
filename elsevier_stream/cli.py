"""The ``elsevier-stream`` command line.

Exit codes: 0 success; 1 nothing found or bad input; 2 an Elsevier or network error.
"""

import argparse
import json
import logging
import sys
import textwrap
from pathlib import Path
from typing import List, Optional

import requests

from . import __version__

logger = logging.getLogger("elsevier_stream")


def _interactive() -> bool:
    """Whether a person is at the terminal, so a command may ask a question."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elsevier-stream",
        description="Literature searches with Elsevier's Scopus and ScienceDirect APIs: size a search, save the "
                    "articles' records into a research folder, read them compactly, export citations, and give "
                    "AI assistants the same tools over MCP.",
    )
    parser.add_argument("--version", action="version", version=f"elsevier-stream {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debugging output")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Count a Scopus or ScienceDirect search and list its newest matches",
                            description="Count a search and list its newest matches, without saving anything.")
    search.add_argument("query", help='Scopus syntax, e.g. TITLE("gut microbiota") AND TITLE-ABS-KEY(frailty)')
    search.add_argument("--show", type=int, default=10, metavar="N", help="List the N newest matches (default 10)")
    search.add_argument("--sciencedirect", action="store_true",
                        help="Search the full texts of Elsevier's journals on ScienceDirect instead, for plain words")
    search.add_argument("--open-access", action="store_true", help="With --sciencedirect: only open-access articles")
    search.add_argument("--json", action="store_true", help="Print JSON")

    dl = sub.add_parser("download", help="Save a Scopus search's newest matches into a research folder",
                        description="Save the Scopus record of each of a search's newest matches as "
                                    "<output-dir>/<search>/<Scopus ID>.json: abstract, authors, keywords, references, "
                                    "and the full text of ScienceDirect articles where the key and network are entitled.")
    dl.add_argument("query", help="Scopus search")
    dl.add_argument("--max-results", type=int, default=30, metavar="N", help="Save at most N articles (default 30)")
    dl.add_argument("--output-dir", metavar="DIR", help="Folder for the downloads (default: publications)")
    dl.add_argument("--no-references", action="store_true", help="Skip reference lists, using half the quota")
    dl.add_argument("--no-full-text", action="store_true", help="Do not try full texts")
    dl.add_argument("--quiet", action="store_true", help="Print only the summary (for scripts and AI assistants)")

    ls = sub.add_parser("list", help="List saved articles compactly",
                        description="One line per saved article, newest first.")
    ls.add_argument("path", nargs="?", default="publications", help="A download folder (default: publications)")
    ls.add_argument("--id", nargs="+", metavar="ID", help="Only these articles, by DOI, Scopus ID or PubMed ID")
    ls.add_argument("--abstracts", action="store_true", help="Print each article's abstract")
    ls.add_argument("--cited", action="store_true", help="List the works the saved articles cite most")
    ls.add_argument("--limit", type=int, metavar="N", help="List only the newest N articles")
    ls.add_argument("--json", action="store_true", help="Print JSON records")

    ex = sub.add_parser("export", help="Export saved articles as BibTeX or RIS citations")
    ex.add_argument("path", nargs="?", default="publications", help="A download folder (default: publications)")
    ex.add_argument("--format", choices=["bibtex", "ris"], help="Default: from the file name, else bibtex")
    ex.add_argument("--id", nargs="+", metavar="ID", help="Export only these articles")
    ex.add_argument("--output", "-o", metavar="FILE", help="Write to FILE instead of printing")

    init = sub.add_parser(
        "init", help="Prepare a research folder for Claude Code, Codex and Gemini CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Writes AGENTS.md (the instructions; CLAUDE.md and GEMINI.md import it), .mcp.json (Claude Code),
.codex/config.toml (Codex) and .gemini/settings.json (Gemini CLI), which start elsevier-stream's MCP
server. Existing files are kept. Where the elsevier-stream plugin is installed, Claude Code's or Codex's
settings get no server, because the plugin provides it in every folder. While no API key is configured,
init asks for one and saves it for every folder in ~/.elsevier-stream.json.""")
    init.add_argument("folder", nargs="?", default=".", help="The research folder (default: the current folder)")
    init.add_argument("--force", action="store_true", help="Rewrite AGENTS.md with the current instructions")
    init.add_argument("--api-key", metavar="KEY", help="Your Elsevier API key, saved for every folder")
    init.add_argument("--insttoken", metavar="TOKEN",
                      help="Your institution's token for full texts off its network, saved for every folder")

    sub.add_parser("status", help="Show which of Elsevier's APIs your key opens, and its quotas")

    mcp = sub.add_parser(
        "mcp", help="Run as an MCP server, so AI assistants can call elsevier-stream's tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Started by the AI assistant, not by you. Connect it in one of three ways:
  the plugin, for Claude Code or Codex in every folder (needs uv):
    claude plugin install elsevier-stream --marketplace melhzy/elsevier-stream
    codex plugin marketplace add melhzy/elsevier-stream
    codex plugin add elsevier-stream@elsevier-stream
  'elsevier-stream init', for Claude Code, Codex or Gemini CLI in one research folder
  by hand, for every folder:
    claude mcp add --scope user elsevier-stream -- elsevier-stream mcp
    codex mcp add elsevier-stream -- elsevier-stream mcp

Tools: search_scopus, search_sciencedirect, download, list_articles, read_article,
most_cited, export_citations.""")
    mcp.add_argument("--root", help="Folder that relative paths refer to (default: the current folder)")
    return parser


def _run_search(args: argparse.Namespace) -> int:
    from .sciencedirect import search_sciencedirect
    from .scopus import search_scopus

    if args.sciencedirect:
        result = search_sciencedirect(args.query, max(args.show, 0), open_access=args.open_access)
    else:
        result = search_scopus(args.query, max(args.show, 0))
    if args.json:
        print(json.dumps({"query": result.query, "total_found": result.total_found, "articles": result.entries},
                         ensure_ascii=False, indent=1))
    else:
        print(result)
    return 0 if result.total_found else 1


def _run_download(args: argparse.Namespace) -> int:
    from .download import download

    def show(done: float, total: int, message: str) -> None:
        print(f"\r{int(done)}/{total} articles: {message}", end="", file=sys.stderr, flush=True)

    stats = download(args.query, max_results=args.max_results, output_dir=args.output_dir,
                     references=not args.no_references, full_text=not args.no_full_text,
                     progress=None if args.quiet else show)
    if not args.quiet and stats.requested:
        print(file=sys.stderr)
    print(stats)
    if stats.not_entitled and not args.quiet:
        print("Full texts need your institution's network, or a token saved with 'elsevier-stream init --insttoken'.")
    if not stats.requested:
        return 1
    return 2 if stats.errors or stats.stopped else 0


def _run_list(args: argparse.Namespace) -> int:
    from .corpus import list_articles, most_cited, select
    from .mcp_server import _line

    path = Path(args.path)
    if not path.exists():
        print(f"{path} does not exist; download a search first", file=sys.stderr)
        return 1
    if args.cited:
        works = most_cited(path, args.limit or 20)
        if args.json:
            print(json.dumps(works, ensure_ascii=False, indent=1))
        for w in works if not args.json else []:
            ref = f"DOI {w['doi']}" if w.get("doi") else w.get("eid") or ""
            print(f"cited by {w['cited_by']:>3}  {ref}  {w.get('year') or 'n.d.'}  {w.get('title') or ''}")
        return 0 if works else 1
    records = list_articles(path)
    if args.id:
        records, missing = select(records, args.id)
        for m in missing:
            print(f"Not saved: {m}", file=sys.stderr)
    if args.limit:
        records = records[:args.limit]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=1))
        return 0 if records else 1
    for r in records:
        print(_line(r) + (f" [{r['words']:,} words]" if r["full_text"] else " [abstract only]"))
        if args.abstracts:
            print(textwrap.fill(r["abstract"] or "(no abstract)", width=100, initial_indent="      ",
                                subsequent_indent="      "))
    return 0 if records else 1


def _run_export(args: argparse.Namespace) -> int:
    from .export import export_citations

    fmt = args.format or ("ris" if (args.output or "").lower().endswith(".ris") else "bibtex")
    text, count, missing = export_citations(args.path, fmt, args.id)
    for m in missing:
        print(f"Not saved: {m}", file=sys.stderr)
    if not count:
        print("No articles to export", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {count} citations ({fmt}) to {args.output}")
    else:
        print(text, end="")
    return 0


def check_api_key(api_key: str) -> str:
    """Ask Scopus whether *api_key* works: ``ok``, ``invalid``, or ``unknown`` when Elsevier could not be reached."""
    from .client import Client, ElsevierError

    client = Client(api_key=api_key)
    try:
        client.get_json("search/scopus", {"query": "TITLE(microbiota)", "count": 1})
        return "ok"
    except ElsevierError as e:
        return "invalid" if e.status == 401 else "unknown"
    except requests.RequestException:
        return "unknown"
    finally:
        client.close()


def _run_init(args: argparse.Namespace) -> int:
    from .assistants import init_folder
    from .client import KEY_PAGE, api_key_status, configured_api_key

    key = args.api_key
    if key is None and not configured_api_key(args.folder) and _interactive():
        print(f"elsevier-stream needs your Elsevier API key. Create one at {KEY_PAGE}\n"
              "and paste it here; it is saved for every folder. Or press Enter to skip.")
        try:
            import getpass
            key = getpass.getpass("Elsevier API key: ").strip() or None
        except EOFError:
            key = None
        print()
    if key:
        verdict = check_api_key(key)
        if verdict == "invalid":
            print("Elsevier rejected this key, so it was not saved. Check it at " + KEY_PAGE, file=sys.stderr)
            return 1
        print("Elsevier accepted the key." if verdict == "ok" else
              "Elsevier could not be reached to check the key; it is saved anyway.")
    try:
        actions = init_folder(args.folder, force=args.force, api_key=key, insttoken=args.insttoken)
    except ValueError as e:   # a settings file that is not valid JSON
        print(f"Error: {e}. Fix or delete the file, then run init again.", file=sys.stderr)
        return 1
    for name, action in actions:
        print(f"{action:>8}  {Path(args.folder) / name}")
    if any(action == "plugin" for _, action in actions):
        print("\n  plugin: the elsevier-stream plugin gives that assistant the tools in every folder, so this "
              "file has no elsevier-stream server of its own.")
    print(f"\nElsevier API key: {api_key_status(args.folder)}")
    print("\nStart your assistant in this folder: claude, codex or gemini. Type /mcp to see elsevier-stream's tools.")
    return 0


def _run_status() -> int:
    """Try each of Elsevier's APIs with the configured key, and say which ones it opens."""
    from .client import Client, ElsevierError, NoApiKey, NotEntitled, api_key_status
    from .sciencedirect import full_text, search_sciencedirect
    from .scopus import fetch_record, search_scopus

    print(f"Elsevier API key: {api_key_status()}")
    try:
        client = Client()
    except NoApiKey:
        return 2
    rows = []

    def check(label: str, call) -> Optional[object]:
        try:
            value = call()
            rows.append((label, "yes", ""))
            return value
        except NotEntitled as e:
            rows.append((label, "no", str(e)))
        except ElsevierError as e:
            rows.append((label, "error", str(e)))
        except requests.RequestException as e:
            rows.append((label, "error", f"could not reach Elsevier: {e}"))
        return None

    try:
        found = check("Scopus search", lambda: search_scopus("TITLE(microbiota)", 1, client=client))
        if found and found.entries:
            check("Scopus abstracts and references",
                  lambda: fetch_record(found.entries[0]["eid"], client, references=True))
        oa = check("ScienceDirect search", lambda: search_sciencedirect("microbiota", 1, open_access=True,
                                                                        client=client))
        if oa and oa.entries:
            check("Full text (an open-access article)", lambda: full_text(client, doi=oa.entries[0]["doi"],
                                                                          pii=oa.entries[0]["pii"]))
        width = max(len(r[0]) for r in rows)
        for label, ok, note in rows:
            print(f"  {label:<{width}}  {ok:<5}  {note}")
        for api, q in sorted(client.quota.items()):
            print(f"  weekly quota, {api}: {q['remaining']:,} of {q['limit']:,} left" +
                  (f", resets {q['resets']}" if q.get("resets") else ""))
        if any(label.startswith("Full text") and ok == "no" for label, ok, _ in rows):
            print("Full texts need your institution's network or VPN, or an institutional token saved with "
                  "'elsevier-stream init --insttoken'.")
    finally:
        client.close()
    return 0 if rows and rows[0][1] == "yes" else 2


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S",
                        level=logging.WARNING, stream=sys.stderr)
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    elif getattr(args, "quiet", False):
        logger.setLevel(logging.ERROR)
    for stream in (sys.stdout, sys.stderr):   # accents and Greek letters on Windows pipes
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "mcp":
        from .mcp_server import serve

        logger.setLevel(logging.WARNING)
        serve(Path(args.root) if args.root else None)
        return 0
    if args.command == "init":
        return _run_init(args)
    if args.command == "list":
        return _run_list(args)
    if args.command == "export":
        return _run_export(args)

    from .client import ElsevierError, NoApiKey

    try:
        if args.command == "status":
            return _run_status()
        if args.command == "search":
            return _run_search(args)
        if args.command == "download":
            return _run_download(args)
    except NoApiKey as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except ElsevierError as e:
        print(f"Error from Elsevier: {e}", file=sys.stderr)
        return 2
    except requests.RequestException as e:
        print(f"Error: could not reach Elsevier: {e}", file=sys.stderr)
        return 2
    return 1
