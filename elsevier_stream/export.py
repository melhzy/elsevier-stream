"""Export downloaded articles as citations, for Zotero, EndNote, Mendeley or LaTeX.

``export_citations`` reads the articles under a folder and writes them as
BibTeX or RIS, the two formats every reference manager imports.  Each entry
has the title, authors, journal, year, volume, issue, pages, DOI, PubMed ID,
Scopus ID, a link and the abstract.  Scopus gives author names as surname
and given names separately, so multi-word surnames come out whole.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from .corpus import list_articles, select

PathLike = Union[str, Path]

FORMATS = ("bibtex", "ris")

_BIBTEX_SPECIAL = re.compile(r"([&%$#_])")


def _meta(record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(Path(record["file"]).read_text(encoding="utf-8")).get("metadata") or {}
    except (OSError, ValueError):
        return {}


def _authors(meta: Dict[str, Any]) -> List[str]:
    """The authors, saved as "Surname, Given names"."""
    return [name for name in meta.get("authors") or [] if name]


def _title(record: Dict[str, Any]) -> str:
    title = " ".join((record.get("title") or "").split())
    return title[:-1] if title.endswith(".") and not title.endswith("..") else title


def _url(record: Dict[str, Any]) -> Optional[str]:
    if record.get("doi"):
        return f"https://doi.org/{record['doi']}"
    if record.get("eid"):
        return f"https://www.scopus.com/record/display.uri?eid={record['eid']}&origin=resultslist"
    return None


def _bibtex_value(text: Any) -> str:
    text = " ".join(str(text).split()).replace("{", "(").replace("}", ")")
    return _BIBTEX_SPECIAL.sub(r"\\\1", text)


def _bibtex_key(record: Dict[str, Any], authors: List[str], used: Dict[str, int]) -> str:
    surname = re.sub(r"\W", "", authors[0].split(",")[0]) if authors else "Anon"
    word = next((re.sub(r"\W", "", w) for w in (record.get("title") or "").split() if re.sub(r"\W", "", w)),
                "Untitled")
    key = f"{surname or 'Anon'}{record.get('year') or ''}{word}"
    used[key] = used.get(key, 0) + 1
    # A second article with the same key gets a letter: Smith2020Gut, Smith2020Guta, ...
    return key if used[key] == 1 else f"{key}{chr(ord('a') + used[key] - 2)}"


def to_bibtex(records: Iterable[Dict[str, Any]]) -> str:
    """BibTeX entries (``@article``) for *records* from :func:`list_articles`."""
    entries, used = [], {}
    for record in records:
        meta = _meta(record)
        authors = _authors(meta)
        fields = {
            "title": _title(record),
            "author": " and ".join(authors),
            "journal": record.get("journal"),
            "year": record.get("year"),
            "volume": meta.get("volume"),
            "number": meta.get("issue"),
            "pages": (meta.get("pages") or "").replace("-", "--") or None,
            "publisher": meta.get("publisher"),
            "doi": record.get("doi"),
            "pmid": record.get("pmid"),
            "eid": record.get("eid"),
            "url": _url(record),
            "abstract": record.get("abstract"),
        }
        body = ",\n".join(f"  {name} = {{{_bibtex_value(value)}}}" for name, value in fields.items() if value)
        entries.append(f"@article{{{_bibtex_key(record, authors, used)},\n{body}\n}}")
    return "\n\n".join(entries) + "\n" if entries else ""


def to_ris(records: Iterable[Dict[str, Any]]) -> str:
    """RIS records (type ``JOUR``) for *records* from :func:`list_articles`."""
    entries = []
    for record in records:
        meta = _meta(record)
        lines = ["TY  - JOUR", f"TI  - {_title(record)}"]
        lines += [f"AU  - {name}" for name in _authors(meta)]
        pages = (meta.get("pages") or "").split("-")
        for tag, value in (("JO", record.get("journal")), ("PY", record.get("year")), ("VL", meta.get("volume")),
                           ("IS", meta.get("issue")), ("SP", pages[0] or None),
                           ("EP", pages[1] if len(pages) > 1 else None), ("PB", meta.get("publisher")),
                           ("DO", record.get("doi")), ("AN", f"PMID:{record['pmid']}" if record.get("pmid") else None),
                           ("UR", _url(record)), ("AB", " ".join((record.get("abstract") or "").split()))):
            if value:
                lines.append(f"{tag}  - {value}")
        lines += [f"KW  - {k}" for k in meta.get("keywords") or []]
        if record.get("eid"):
            lines.append(f"N1  - Scopus EID: {record['eid']}")
        entries.append("\n".join(lines + ["ER  - "]))
    return "\n\n".join(entries) + "\n" if entries else ""


def export_citations(
    path: PathLike = "publications",
    fmt: str = "bibtex",
    ids: Optional[Iterable[Any]] = None,
) -> Tuple[str, int, List[str]]:
    """Citations for the articles under *path*, as BibTeX or RIS.

    *ids* chooses articles by Scopus ID, DOI or PubMed ID; without it, every
    article is exported, newest first.  Returns ``(text, count, missing)``,
    where *missing* lists the IDs not found.

    Raises:
        ValueError: *fmt* is not ``"bibtex"`` or ``"ris"``.
    """
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    records, missing = list_articles(path), []
    if ids:
        records, missing = select(records, ids)
    text = to_bibtex(records) if fmt == "bibtex" else to_ris(records)
    return text, len(records), missing
