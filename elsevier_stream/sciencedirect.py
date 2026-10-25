"""ScienceDirect: search Elsevier's own journals and books, and fetch full texts where entitled.

``search_sciencedirect`` searches the full texts of ScienceDirect and says
which matches are open access.  ``full_text`` returns an article's text as
plain text.  Elsevier serves full texts only to a key used from an entitled
institution's network, or with an institutional token; otherwise it raises
:class:`~elsevier_stream.client.NotEntitled`, even for open-access articles.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .client import Client

SEARCH_PAGE = 100            # the most results ScienceDirect returns per request
MIN_FULL_TEXT_CHARS = 2000   # shorter text is an abstract or a stub, not the article


@dataclass
class ScienceDirectSearch:
    """The size of a ScienceDirect search and its newest matches."""
    query: str
    total_found: int
    entries: List[Dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.total_found:,} results in ScienceDirect for: {self.query}"]
        if self.entries:
            lines.append(f"Newest {len(self.entries)}:")
        for e in self.entries:
            oa = " [open access]" if e["open_access"] else ""
            lines.append(f"  {e['year'] or 'n.d.'}  DOI {e['doi'] or '-'}  {e['title'] or ''} ({e['journal'] or ''}){oa}")
        return "\n".join(lines)


def parse_result(result: Dict[str, Any]) -> Dict[str, Any]:
    date = result.get("publicationDate") or ""
    return {
        "doi": result.get("doi"),
        "pii": result.get("pii"),
        "title": " ".join((result.get("title") or "").split()) or None,
        "journal": result.get("sourceTitle"),
        "year": date[:4] if date[:4].isdigit() else None,
        "open_access": bool(result.get("openAccess")),
        "url": result.get("uri"),
    }


def search_sciencedirect(query: str, max_results: int = 10, open_access: bool = False,
                         client: Optional[Client] = None) -> ScienceDirectSearch:
    """Count a ScienceDirect search of *query*'s words and list up to *max_results* of the newest matches.

    With *open_access*, only open-access articles are counted and listed.
    """
    own = client is None
    client = client or Client()
    try:
        entries: List[Dict[str, Any]] = []
        total = 0
        while True:
            body: Dict[str, Any] = {"qs": query, "display": {"offset": len(entries), "sortBy": "date",
                                                             "show": min(SEARCH_PAGE, max(max_results - len(entries), 1))}}
            if open_access:
                body["filters"] = {"openAccess": True}
            data = client.request("PUT", "search/sciencedirect", json_body=body).json()
            total = int(data.get("resultsFound") or 0)
            page = data.get("results") or []
            entries.extend(parse_result(r) for r in page)
            if not page or len(entries) >= min(max_results, total) or max_results <= 0:
                break
        return ScienceDirectSearch(query, total, entries[:max(max_results, 0)])
    finally:
        if own:
            client.close()


def full_text(client: Client, doi: Optional[str] = None, pii: Optional[str] = None) -> Optional[str]:
    """The article's full text as plain text, or None when Elsevier returns only a stub.

    Raises:
        NotEntitled: this key, network or token does not give access to full texts.
        NotFound: ScienceDirect has no article with that DOI or PII.
    """
    if not doi and not pii:
        raise ValueError("full_text needs a DOI or a PII")
    path = f"article/pii/{quote(pii)}" if pii else f"article/doi/{quote(doi, safe='/')}"
    text = client.request("GET", path, params={"view": "FULL"}, accept="text/plain").text.strip()
    return text if len(text) >= MIN_FULL_TEXT_CHARS else None
