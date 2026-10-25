# elsevier-stream

Literature searches in Elsevier's Scopus and ScienceDirect, with every claim cited by DOI.

Ask a research question in plain language, such as *Is the gut microbiota linked to frailty? Size a Scopus search first, save the studies, and summarize the evidence with DOIs.* The assistant sizes the search in Scopus, which indexes the journals of every major publisher, saves each article's Scopus record (abstract, authors, keywords, references and citation count) in your folder, reads them compactly, finds the works the field cites most, and writes a report that cites only papers it read. It can export the papers for Zotero, EndNote or Mendeley.

**You need an Elsevier API key**, free from <https://dev.elsevier.com/apikey/manage>. Full texts come only from ScienceDirect, and only where your institution entitles you: on its network, or with an institutional token.

## Install

Inside Claude Code:

```
/plugin install elsevier-stream --marketplace melhzy/elsevier-stream
```

Or in a terminal:

```
claude plugin install elsevier-stream --marketplace melhzy/elsevier-stream
```

Claude Code asks for your API key. Codex users install from the same repository: `codex plugin marketplace add melhzy/elsevier-stream`, then `codex plugin add elsevier-stream@elsevier-stream`, and save the key with `elsevier-stream init --api-key YOUR-KEY`.

## What the plugin contains

- **Seven MCP tools**: `search_scopus`, `search_sciencedirect`, `download`, `list_articles`, `read_article`, `most_cited` and `export_citations`. Each returns compact text.
- **One skill**, `elsevier-search`, with the rules of the research: size searches first, cite only what was read, say what kind of evidence each paper is, and name what could not be read.

## What it runs, sends and saves

The plugin holds no program of its own. It starts the MCP server of the [elsevier-stream](https://pypi.org/project/elsevier-stream/) Python library with `uvx --from elsevier-stream==<version> elsevier-stream mcp`: [uv](https://docs.astral.sh/uv/getting-started/installation/) downloads that release from PyPI and runs it on your computer, so **uv must be installed**.

The server talks only to Elsevier's APIs at `api.elsevier.com`, sending your API key with each request. Each saved article uses one or two requests from your key's weekly quota. After the first request that works, the server also saves the key in `~/.elsevier-stream.json`, so the `elsevier-stream` command line can use it. Nothing is sent to the plugin's author or to any other service.

Files are saved in the folder the session starts in, under `publications/`, and a citations file where you ask for one. Elsevier's terms let you keep these records for your own research; do not share them publicly.

[Source](https://github.com/melhzy/elsevier-stream) · MIT license
