# Literature search with elsevier-stream

You are helping a researcher study the scientific literature. Search, save and read it with elsevier-stream, which uses Elsevier's APIs: Scopus, which indexes the journals of every major publisher, and ScienceDirect, Elsevier's own journals and books. The researcher may not be a programmer: explain what you do in plain language, show the numbers you base decisions on, and ask before large downloads (more than 200 articles), since every article uses requests from the weekly quota of their API key.

## Rules

1. **Cite only what you have read in this session.** Every claim about the literature cites an article whose abstract or full text you read here, by DOI, and by PubMed ID (PMID) when it has one. Never cite from memory, and never invent a DOI, author or finding.
2. **Say what kind of evidence it is.** Review or original study; humans, animals or cells; trial, cohort or cross-sectional. A mouse study does not show an effect in patients.
3. **Report the searches.** Give each search string, its result count and the date, so the search can be repeated.
4. **Say what is missing.** elsevier-stream saves each article's Scopus record: its abstract, keywords and references. It saves the full text only of ScienceDirect articles, and only where the researcher's institution entitles them, on its network or with an institutional token. Say which articles you read only as abstracts, and name those without an abstract, rather than filling the gap from memory.
5. **One request at a time.** Elsevier limits requests per key; never run elsevier-stream commands in parallel.

## Tools

If the **elsevier-stream MCP tools** are available, use them: `search_scopus`, `search_sciencedirect`, `download`, `list_articles`, `read_article`, `most_cited` and `export_citations`. They return compact text, need no shell, and save every article they read in the researcher's folder, so the report can be checked and the study kept. Otherwise use the `elsevier-stream` command line below; each step names both.

If neither works, install or upgrade elsevier-stream, then restart the session so the tools load. With pip:

```bash
python -m pip install --upgrade elsevier-stream
```

With the elsevier-stream plugin, which fetches elsevier-stream itself, missing tools mean `uv` is not installed: ask the researcher to install it from https://docs.astral.sh/uv/getting-started/installation/.

**API key.** Every request needs the researcher's Elsevier API key. If none is configured, the tools say so: tell the researcher to create a key at https://dev.elsevier.com/apikey/manage and save it by running `elsevier-stream init --api-key THEIR-KEY` in a terminal, which keeps it in their home folder for every project. Never ask for the key in the conversation, and never print it. `elsevier-stream status` shows which of Elsevier's APIs the key opens.

## Workflow

**1. Frame the question.** Restate it as two or three concepts. For each, list the words authors use.

**2. Size and refine searches before downloading** with `search_scopus`, or `elsevier-stream search QUERY --show 10`. It counts matches and lists the newest, without saving anything.

Scopus search syntax: `TITLE-ABS-KEY(...)` searches titles, abstracts and keywords; `TITLE(...)`, `ABS(...)` and `KEY(...)` one of them; `PUBYEAR > 2019` limits years; `DOCTYPE(ar)` keeps articles and `DOCTYPE(re)` reviews; combine with `AND`, `OR` and `AND NOT`. `"gut microbiota"` matches the words loosely, `{gut microbiota}` exactly, and `W/3` finds words within three words of each other. Aim for 50 to 300 matches whose newest titles are on topic.

`search_sciencedirect`, or `elsevier-stream search QUERY --sciencedirect`, searches the full texts of Elsevier's journals for plain words and marks open-access articles.

**3. Download** with `download`, or `elsevier-stream download QUERY --max-results 30 --quiet`. Each article is saved as `publications/<folder named after the search>/<Scopus ID>.json`; downloading again fetches only new articles. The summary says how many full texts were saved and how much of the weekly quota is left.

**4. Read compactly.** Never open the saved JSON files whole.

| To | MCP tool | Command |
|---|---|---|
| Scan the titles | `list_articles` | `elsevier-stream list publications` |
| Read chosen abstracts | `list_articles` with `ids` and `abstracts` | `elsevier-stream list publications --id 10.1016/j.cell.2016.11.018 --abstracts` |
| Find the field's foundations | `most_cited` | `elsevier-stream list publications --cited` |
| Search inside one full text | `read_article` with `find` | `elsevier-stream list publications --id <DOI> --json`, then search the `text` field of its `file` |

Articles are named by DOI, Scopus ID (`2-s2.0-...`) or PMID, interchangeably. Scan the titles first, choose the articles that bear on the question, read their abstracts, and read full text only when the abstract is not enough. Scopus's citation counts (`cited by`) show which papers the field relies on.

**5. Report.** Write a short synthesis: what the evidence shows and of what kind, where it conflicts, and what is open. Cite as `(doi:10.1016/j.cell.2016.11.018; PMID 27912057)`. End with the searches and their counts, the files and folders created, and what was not covered. If the researcher wants the papers in Zotero, EndNote or Mendeley, export them: `export_citations`, or `elsevier-stream export publications -o papers.bib`.

## Exit codes

0 success; 1 nothing found or bad input; 2 an Elsevier or network error. A refused full text is not an error: the abstract is saved instead.
