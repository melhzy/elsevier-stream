"""elsevier-stream – literature searches with Elsevier's Scopus and ScienceDirect APIs."""

__version__ = "0.1.0"

from .client import Client, ElsevierError, NoApiKey, NotEntitled, NotFound, QuotaExceeded
from .corpus import list_articles, most_cited
from .download import DownloadStats, download
from .export import export_citations
from .sciencedirect import full_text, search_sciencedirect
from .scopus import fetch_record, search_scopus
from .assistants import init_folder

__all__ = [
    "__version__",
    "Client",
    "ElsevierError",
    "NoApiKey",
    "NotEntitled",
    "NotFound",
    "QuotaExceeded",
    "DownloadStats",
    "download",
    "export_citations",
    "fetch_record",
    "full_text",
    "init_folder",
    "list_articles",
    "most_cited",
    "search_sciencedirect",
    "search_scopus",
]
