"""Scopus: search the literature of every major publisher, and fetch each article's record.

``search_scopus`` counts a search and lists its newest matches without
saving anything.  ``fetch_record`` returns one article's full Scopus record:
title, abstract, authors, affiliations, journal, author keywords, index
terms, subject areas, citation count and, optionally, the reference list.
Scopus returns a JSON list as a single object when it has one element;
``_as_list`` evens that out.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .client import Client

logger = logging.getLogger(__name__)

SEARCH_PAGE = 25        # the most results Scopus returns per page
MAX_REFERENCE_PAGES = 10


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(value: Any) -> Optional[str]:
    """The text of a Scopus value, which is a string or an object with the text under ``$``."""
    if isinstance(value, dict):
        value = value.get("$")
    text = " ".join(str(value).split()) if value is not None else ""
    return text or None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(value: Any) -> bool:
    return value is True or str(value).lower() in ("true", "1")


def _year(date: Any) -> Optional[str]:
    text = _text(date)
    return text[:4] if text and text[:4].isdigit() else None


def parse_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A compact record of one Scopus search result."""
    return {
        "eid": entry.get("eid"),
        "doi": entry.get("prism:doi"),
        "pmid": entry.get("pubmed-id"),
        "title": _text(entry.get("dc:title")),
        "journal": _text(entry.get("prism:publicationName")),
        "year": _year(entry.get("prism:coverDate")),
        "type": entry.get("subtypeDescription"),
        "first_author": _text(entry.get("dc:creator")),
        "cited_by": _int(entry.get("citedby-count")),
        "open_access": _flag(entry.get("openaccessFlag")),
    }


@dataclass
class ScopusSearch:
    """The size of a Scopus search and its newest matches."""
    query: str
    total_found: int
    entries: List[Dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.total_found:,} articles in Scopus for: {self.query}"]
        if self.entries:
            lines.append(f"Newest {len(self.entries)}:")
        for e in self.entries:
            ids = "  ".join(x for x in (f"DOI {e['doi']}" if e["doi"] else None,
                                        f"PMID {e['pmid']}" if e["pmid"] else None) if x)
            kind = f" [{e['type']}]" if e["type"] and e["type"] != "Article" else ""
            lines.append(f"  {e['year'] or 'n.d.'}  {e['eid']}  {ids}  {e['title'] or ''} ({e['journal'] or ''})"
                         f"{kind}  cited by {e['cited_by'] or 0}")
        return "\n".join(lines)


def search_scopus(query: str, max_results: int = 10, client: Optional[Client] = None) -> ScopusSearch:
    """Count a Scopus search and list up to *max_results* of its newest matches, without saving anything.

    *query* uses Scopus's advanced search syntax, such as
    ``TITLE-ABS-KEY("gut microbiota") AND TITLE(frailty) AND PUBYEAR > 2019``.
    """
    own = client is None
    client = client or Client()
    try:
        entries: List[Dict[str, Any]] = []
        cursor, total = "*", 0
        while True:
            count = min(SEARCH_PAGE, max(max_results - len(entries), 1))
            data = client.get_json("search/scopus", {"query": query, "count": count, "cursor": cursor,
                                                     "sort": "-coverDate"})["search-results"]
            total = _int(data.get("opensearch:totalResults")) or 0
            page = [e for e in _as_list(data.get("entry")) if e.get("eid")]   # an empty result holds an error entry
            entries.extend(parse_entry(e) for e in page)
            cursor = (data.get("cursor") or {}).get("@next")
            if not page or not cursor or len(entries) >= min(max_results, total) or max_results <= 0:
                break
        return ScopusSearch(query, total, entries[:max(max_results, 0)])
    finally:
        if own:
            client.close()


def _name(person: Dict[str, Any]) -> Optional[str]:
    """An author's name as "Surname, Given names", which keeps a multi-word surname whole."""
    preferred = person.get("preferred-name") or {}
    surname = _text(preferred.get("ce:surname") or person.get("ce:surname"))
    given = _text(preferred.get("ce:given-name") or person.get("ce:given-name")
                  or preferred.get("ce:initials") or person.get("ce:initials"))
    if surname:
        return f"{surname}, {given}" if given else surname
    return _text(person.get("ce:indexed-name"))


def parse_abstract(data: Dict[str, Any]) -> Dict[str, Any]:
    """The metadata of an article from Scopus's abstract record (``view=FULL``)."""
    record = data.get("abstracts-retrieval-response") or data
    core = record.get("coredata") or {}
    affiliations = []
    for a in _as_list(record.get("affiliation")):
        parts = [_text(a.get("affilname")), _text(a.get("affiliation-city")), _text(a.get("affiliation-country"))]
        if any(parts):
            affiliations.append(", ".join(p for p in parts if p))
    return {
        "eid": core.get("eid"),
        "scopus_id": (core.get("dc:identifier") or "").replace("SCOPUS_ID:", "") or None,
        "doi": core.get("prism:doi"),
        "pmid": core.get("pubmed-id"),
        "pii": core.get("pii"),
        "title": _text(core.get("dc:title")),
        "abstract": _text(core.get("dc:description")) or "",
        "journal": _text(core.get("prism:publicationName")),
        "year": _year(core.get("prism:coverDate")),
        "date": _text(core.get("prism:coverDate")),
        "volume": _text(core.get("prism:volume")),
        "issue": _text(core.get("prism:issueIdentifier")),
        "pages": _text(core.get("prism:pageRange")),
        "publisher": _text(core.get("dc:publisher")),
        "type": core.get("subtypeDescription"),
        "open_access": _flag(core.get("openaccessFlag")),
        "cited_by": _int(core.get("citedby-count")),
        "authors": [n for n in (_name(p) for p in _as_list((record.get("authors") or {}).get("author"))) if n],
        "affiliations": affiliations,
        "keywords": [k for k in (_text(x) for x in _as_list((record.get("authkeywords") or {}).get("author-keyword")))
                     if k],
        "index_terms": [t for t in (_text(x) for x in _as_list((record.get("idxterms") or {}).get("mainterm"))) if t],
        "subject_areas": [s for s in (_text(x) for x in _as_list((record.get("subject-areas") or {})
                                                                  .get("subject-area"))) if s],
    }


def parse_references(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The works an article cites, from Scopus's ``view=REF``: their Scopus ID, DOI, PubMed ID, title and year."""
    refs = ((data.get("abstracts-retrieval-response") or data).get("references") or {}).get("reference")
    return [{
        "eid": r.get("scopus-eid"),
        "doi": r.get("ce:doi"),
        "pmid": r.get("pubmed-id"),
        "title": _text(r.get("title")),
        "journal": _text(r.get("sourcetitle")),
        "year": _year(r.get("prism:coverDate")),
    } for r in _as_list(refs)]


def fetch_references(eid: str, client: Client) -> List[Dict[str, Any]]:
    """The reference list of one article, page by page."""
    refs: List[Dict[str, Any]] = []
    params: Dict[str, Any] = {"view": "REF"}   # the first page: Scopus's default of up to 40 references
    for _ in range(MAX_REFERENCE_PAGES):
        data = client.get_json(f"abstract/eid/{eid}", params)
        batch = parse_references(data)
        refs.extend(batch)
        total = _int(((data.get("abstracts-retrieval-response") or {}).get("references") or {})
                     .get("@total-references")) or 0
        if not batch or len(refs) >= total:
            break
        # Only the start: Scopus then returns what remains, up to its page size, but refuses a refcount
        # that reaches the last reference exactly (startref 41, refcount 18 of 58)
        params = {"view": "REF", "startref": len(refs) + 1}
    return refs


def fetch_record(eid: str, client: Client, references: bool = True) -> Dict[str, Any]:
    """One article's metadata from Scopus, with its reference list unless *references* is false."""
    meta = parse_abstract(client.get_json(f"abstract/eid/{eid}", {"view": "FULL"}))
    meta["eid"] = meta["eid"] or eid
    meta["references"] = fetch_references(eid, client) if references else []
    return meta
