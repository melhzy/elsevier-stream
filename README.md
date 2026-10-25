# elsevier-stream

**Literature searches with Elsevier's Scopus and ScienceDirect APIs, for researchers and their AI assistants.** elsevier-stream sizes a search in Scopus, which indexes the journals of every major publisher, saves each matching article's Scopus record into your research folder (abstract, authors, affiliations, keywords, index terms, references and citation count), reads the records back compactly, finds the works the field cites most, and exports citations for Zotero, EndNote or Mendeley. It gives Claude Code, Codex and Gemini CLI the same abilities as MCP tools, so you can ask a research question in plain language. It needs only `requests`, and your Elsevier API key.

It is the sister of [pubmed-stream](https://github.com/melhzy/pubmed-stream), which works the same way with PubMed and PubMed Central. Scopus covers journals PubMed does not, such as engineering, chemistry and the social sciences, and gives citation counts; each record carries its PubMed ID when it has one, so the two combine.

## What your API key opens

Elsevier's APIs answer according to your key and where you use it. `elsevier-stream status` checks yours:

| | With any key | Needs your institution |
|---|---|---|
| Scopus search, abstracts, keywords, references, citation counts | yes | |
| ScienceDirect search, with open access marked | yes | |
| Full texts of ScienceDirect articles | | its network or VPN, or an institutional token |
| The papers that cite a paper, and citation overviews | | Elsevier's approval for the key |

Without full-text access, elsevier-stream saves the abstract and says so; where you have access, it saves the full text too.

## Quick start

```bash
pip install elsevier-stream

# Save your key once, for every folder; create one at https://dev.elsevier.com/apikey/manage
elsevier-stream init --api-key YOUR-KEY
elsevier-stream status

# Size a Scopus search and preview its newest matches, without saving anything
elsevier-stream search 'TITLE("gut microbiota") AND TITLE-ABS-KEY(frailty)'

# Save the records of up to 30 matches, then read them compactly
elsevier-stream download 'TITLE("gut microbiota") AND TITLE-ABS-KEY(frailty)' --max-results 30
elsevier-stream list publications --abstracts
elsevier-stream list publications --cited

# Export them as citations
elsevier-stream export publications -o frailty.bib
```

The key can also come from the `ELSEVIER_API_KEY` environment variable, or from a `.env` file in the folder, with the line `ELSEVIER_API_KEY=...`. An institutional token goes in `ELSEVIER_INSTTOKEN`, or `elsevier-stream init --insttoken TOKEN`.

**Scopus search syntax.** `TITLE-ABS-KEY(...)` searches titles, abstracts and keywords; `TITLE(...)`, `ABS(...)` and `KEY(...)` one of them; `PUBYEAR > 2019` limits the years; `DOCTYPE(ar)` keeps articles and `DOCTYPE(re)` reviews; combine with `AND`, `OR` and `AND NOT`. `"gut microbiota"` matches the words loosely, `{gut microbiota}` exactly, and `W/3` finds words within three of each other. `elsevier-stream search --sciencedirect` searches the full texts of Elsevier's journals for plain words instead.

**What is saved.** Each article is a JSON file, `publications/<folder named after the search>/<Scopus ID>.json`, such as `2-s2.0-85001930733.json`. Downloading a search again fetches only new articles. Articles are named by DOI, Scopus ID or PubMed ID interchangeably in `list --id` and `export --id`.

**Quotas.** Elsevier allows each key 20,000 Scopus searches and 10,000 abstract records a week. Each saved article uses one record request, and one more for its references (`--no-references` skips them). The download summary and `status` show what is left.

## With an AI assistant: Claude Code, Codex or Gemini CLI

elsevier-stream's **MCP server** gives an assistant seven MCP tools: `search_scopus`, `search_sciencedirect`, `download`, `list_articles`, `read_article`, `most_cited` and `export_citations`. Each returns compact text. The instructions that come with them make the assistant size searches before downloading, cite only papers it read in the session, say what kind of evidence each is, report its searches with their counts, and name what it could not read. Set it up in one of two ways:

| | The plugin | `elsevier-stream init` |
|---|---|---|
| Gives the tools to | Claude Code or Codex, in every folder | any of the three assistants, in one research folder |
| Needs | [uv](https://docs.astral.sh/uv/getting-started/installation/); the plugin fetches elsevier-stream itself | `pip install elsevier-stream` |
| Carries the instructions as | the skill `elsevier-search` | `AGENTS.md` in the folder, which `CLAUDE.md` and `GEMINI.md` import |
| Asks for your API key | at install (Claude Code) | in the terminal, while none is saved |

```bash
# The plugin, once
claude plugin install elsevier-stream --marketplace melhzy/elsevier-stream   # Claude Code
codex plugin marketplace add melhzy/elsevier-stream                           # Codex
codex plugin add elsevier-stream@elsevier-stream

# Or one folder
elsevier-stream init
```

Then start the assistant in your research folder and ask, for example:

> *Is the gut microbiota linked to frailty in older adults? Size a Scopus search first, save the studies, and summarize the evidence with DOIs.*

Where the plugin is installed, `init` leaves its server out of the folder, so the tools are not listed twice. Without uv, register the server you installed with pip: `claude mcp add --scope user elsevier-stream -- elsevier-stream mcp`, or the same with `codex mcp add`.

## Python

```python
from elsevier_stream import download, list_articles, most_cited, search_scopus

print(search_scopus('TITLE("gut microbiota") AND TITLE(frailty)', max_results=5))
stats = download('TITLE("gut microbiota") AND TITLE(frailty)', max_results=30)
records = list_articles("publications")
print(stats.saved, records[0]["title"], most_cited("publications", 5))
```

## Elsevier's terms

Your key is personal: keep it out of shared files and repositories (this repository ignores `.env`). Elsevier's [API service agreement](https://dev.elsevier.com/api_key_settings.html) governs what you may do with the records; keep the saved articles for your own research rather than publishing them. elsevier-stream sends your key only to `api.elsevier.com`.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

The tests run offline against a fake Elsevier. To release, bump the version in `elsevier_stream/__init__.py` and in `plugins/elsevier-stream` (both `plugin.json` files, the `elsevier-stream==X.Y.Z` in `.codex-plugin/mcp.json` and `.claude-plugin/plugin.json`, and the skill's note); `tests/test_plugin.py` names any copy left behind. Upload to PyPI before pushing the version bump: the plugin runs the release it names.

## License

MIT
