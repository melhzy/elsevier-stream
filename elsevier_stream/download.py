"""Save the newest matches of a Scopus search into a research folder, one JSON file per article.

Each file, ``<output_dir>/<folder named after the search>/<EID>.json``,
holds the article's Scopus record (see :func:`~elsevier_stream.scopus.fetch_record`)
and, where the key and network are entitled to it, the full text.  Files
that exist are skipped, so downloading a search again fetches only new
articles.  Each article costs one or two requests from the key's weekly
abstract quota (the record, and its references), plus one for the full text.

Full texts are tried only for ScienceDirect articles.  After the first
refusal (403) in a run, the rest are not tried: Elsevier refuses them all
alike from a network without entitlement.
"""

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from .client import Client, ElsevierError, NotEntitled, NotFound, QuotaExceeded
from .scopus import fetch_record, search_scopus
from .sciencedirect import full_text as fetch_full_text

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]
ProgressFn = Callable[[float, int, str], None]   # (done, total, message)

DEFAULT_OUTPUT_DIR = Path("publications")
MAX_SLUG_LENGTH = 100


def folder_name(query: str) -> str:
    """A folder name for a search: its words, lower case, joined by underscores, shortened with a hash if long."""
    slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_") or "search"
    if len(slug) > MAX_SLUG_LENGTH:
        slug = slug[:MAX_SLUG_LENGTH - 9].rstrip("_") + "_" + hashlib.sha1(query.encode("utf-8")).hexdigest()[:8]
    return slug


@dataclass
class DownloadStats:
    """What a download did."""
    query: str
    total_found: int
    requested: int
    saved: int = 0
    skipped: int = 0
    full_texts: int = 0
    not_entitled: int = 0
    errors: int = 0
    stopped: Optional[str] = None      # why the download stopped early, such as a used-up quota
    duration_seconds: float = 0.0
    output_dir: Path = DEFAULT_OUTPUT_DIR
    quota: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def __str__(self) -> str:
        lines = [f"{self.total_found:,} articles in Scopus; {self.requested} requested: {self.saved} saved, "
                 f"{self.skipped} already there, {self.errors} errors.",
                 f"Full texts: {self.full_texts}" + (f"; {self.not_entitled} not available with this key and network "
                                                     "(abstract saved)" if self.not_entitled else "")]
        if self.stopped:
            lines.append(f"Stopped early: {self.stopped}")
        abstracts = self.quota.get("abstract/eid")
        if abstracts:
            lines.append(f"Weekly abstract quota left: {abstracts['remaining']:,} of {abstracts['limit']:,}")
        lines.append(f"Folder: {self.output_dir.resolve()}")
        return "\n".join(lines)


def download(
    query: str,
    max_results: int = 30,
    output_dir: Optional[PathLike] = None,
    references: bool = True,
    full_text: bool = True,
    client: Optional[Client] = None,
    progress: Optional[ProgressFn] = None,
) -> DownloadStats:
    """Save the Scopus records of the newest *max_results* matches of *query*, with full texts where entitled."""
    start = time.time()
    own = client is None
    client = client or Client()
    try:
        found = search_scopus(query, max_results, client=client)
        out_dir = Path(output_dir or DEFAULT_OUTPUT_DIR) / folder_name(query)
        stats = DownloadStats(query, found.total_found, len(found.entries), output_dir=out_dir)
        if found.entries:
            out_dir.mkdir(parents=True, exist_ok=True)
        try_full_text = full_text
        for i, entry in enumerate(found.entries, 1):
            file = out_dir / f"{entry['eid']}.json"
            if file.exists():
                stats.skipped += 1
            else:
                try:
                    meta = fetch_record(entry["eid"], client, references=references)
                except QuotaExceeded as e:
                    stats.stopped = str(e)
                    break
                except ElsevierError as e:
                    logger.warning("%s: %s", entry["eid"], e)
                    stats.errors += 1
                    continue
                text = ""
                if meta.get("pii") or (meta.get("doi") or "").startswith("10.1016/"):
                    if try_full_text:
                        try:
                            text = fetch_full_text(client, doi=meta.get("doi"), pii=meta.get("pii")) or ""
                        except NotEntitled:
                            try_full_text = False   # Elsevier refuses them all alike from this network
                            stats.not_entitled += 1
                        except (NotFound, QuotaExceeded) as e:
                            logger.info("%s: no full text: %s", entry["eid"], e)
                        except ElsevierError as e:
                            logger.warning("%s: full text failed: %s", entry["eid"], e)
                    elif full_text:
                        stats.not_entitled += 1
                record = {"source": "scopus", "eid": meta["eid"], "retrieved": date.today().isoformat(),
                          "metadata": meta, "text": text}
                file.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
                stats.saved += 1
                stats.full_texts += bool(text)
            if progress:
                progress(i, len(found.entries), f"{stats.saved} saved, {stats.skipped} already there")
        stats.quota = dict(client.quota)
        stats.duration_seconds = time.time() - start
        return stats
    finally:
        if own:
            client.close()
