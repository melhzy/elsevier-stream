"""Read downloaded articles back as compact records.

To scan a corpus, a person or an AI assistant needs only each article's
identifiers, title, journal, year and abstract: ``list_articles`` returns
those, one record per article, however many searches found it.
``most_cited`` finds the works the corpus cites most, its foundations.
"""

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Tuple, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def _articles(path: PathLike) -> Iterator[Tuple[Path, Dict[str, Any], List[str]]]:
    """Each downloaded article under *path* once, with the folders it is in."""
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.rglob("*.json"))
    seen: Dict[str, Tuple[Path, Dict[str, Any], List[str]]] = {}
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("Skipping %s: %s", file, e)
            continue
        if not isinstance(data, dict) or data.get("source") != "scopus":
            continue   # other JSON files, such as an export or settings
        key = data.get("eid") or file.stem
        if key in seen:
            if file.parent.name not in seen[key][2]:
                seen[key][2].append(file.parent.name)
        else:
            seen[key] = (file, data, [file.parent.name])
    return iter(seen.values())


def list_articles(path: PathLike) -> List[Dict[str, Any]]:
    """Compact records of the articles downloaded under *path*, newest first.

    *path* is one article file or a folder, searched recursively.  Each
    record has ``eid``, ``doi``, ``pmid``, ``year``, ``journal``, ``title``,
    ``first_author``, ``abstract``, ``type``, ``cited_by``, ``open_access``,
    ``full_text`` (whether the full text was saved), ``words`` (its length),
    ``file`` and ``folders``.  An article in several folders appears once.
    """
    records = []
    for file, data, folders in _articles(path):
        meta = data.get("metadata") or {}
        authors = meta.get("authors") or []
        text = data.get("text") or ""
        records.append({
            "eid": data.get("eid") or meta.get("eid"),
            "doi": meta.get("doi"),
            "pmid": meta.get("pmid"),
            "year": meta.get("year"),
            "journal": meta.get("journal"),
            "title": meta.get("title"),
            "first_author": authors[0] if authors else None,
            "abstract": meta.get("abstract") or "",
            "type": meta.get("type"),
            "cited_by": meta.get("cited_by"),
            "open_access": bool(meta.get("open_access")),
            "full_text": bool(text),
            "words": len(text.split()),
            "file": str(file),
            "folders": folders,
        })
    return sorted(records, key=lambda r: (str(r["year"] or ""), r["eid"] or ""), reverse=True)


def _keys(record: Dict[str, Any]) -> List[str]:
    keys = [str(record.get(k) or "").lower() for k in ("eid", "doi", "pmid")]
    eid = record.get("eid") or ""
    if eid.startswith("2-s2.0-"):
        keys.append(eid[len("2-s2.0-"):])   # the bare Scopus ID
    return [k for k in keys if k]


def select(records: List[Dict[str, Any]], ids: Iterable[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The records with the given Scopus IDs (EIDs), DOIs or PubMed IDs, and the IDs not found among them."""
    wanted = [str(i).strip() for i in ids if str(i).strip()]
    chosen, missing = [], []
    for want in wanted:
        match = [r for r in records if want.lower().removeprefix("doi:") in _keys(r)]
        if match:
            chosen.extend(r for r in match if r not in chosen)
        else:
            missing.append(want)
    return chosen, missing


def short_id(record: Dict[str, Any]) -> str:
    """How listings name an article: its DOI, or its Scopus ID when it has none."""
    return f"DOI {record['doi']}" if record.get("doi") else str(record.get("eid") or "")


def most_cited(path: PathLike, n: int = 10) -> List[Dict[str, Any]]:
    """The *n* works cited by the most articles downloaded under *path*.

    Each record has ``eid``, ``doi``, ``pmid``, ``title``, ``journal``, ``year``
    and ``cited_by``, the number of downloaded articles that cite it.
    References are matched by Scopus ID, or by DOI when they have none.
    """
    counts: Counter = Counter()
    details: Dict[str, Dict[str, Any]] = {}
    for _, data, _ in _articles(path):
        cited: Dict[str, None] = {}   # ordered, so ties keep the order works are first cited
        for ref in (data.get("metadata") or {}).get("references") or []:
            key = ref.get("eid") or (ref.get("doi") or "").lower()
            if not key:
                continue
            cited[key] = None
            known = details.setdefault(key, {k: ref.get(k) for k in ("eid", "doi", "pmid", "title", "journal", "year")})
            for k, v in ref.items():
                known[k] = known.get(k) or v
        counts.update(cited.keys())
    return [{**details[key], "cited_by": count} for key, count in counts.most_common(n)]
