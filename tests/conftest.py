"""Shared test helpers: a fake Elsevier, and a clean home folder and working folder for every test."""

import json
from pathlib import Path
from typing import Callable, Dict, Optional, Union
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

Reply = Union[str, dict, tuple, Callable]


@pytest.fixture(autouse=True)
def home(tmp_path_factory, monkeypatch):
    """Every test runs in an empty folder with an empty home folder: never the developer's key or settings."""
    folder = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    monkeypatch.chdir(tmp_path_factory.mktemp("work"))   # a .env in the repository holds a real key
    for name in ("ELSEVIER_API_KEY", "ELSEVIER_STREAM_API_KEY", "ELSEVIER_INSTTOKEN", "ANTHROPIC_API_KEY",
                 "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                 "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("time.sleep", lambda seconds: None)   # retries do not wait
    return folder


class FakeAdapter(BaseAdapter):
    """Answers requests from *routes*: {url substring: reply}, the first match winning; others get 404.

    A reply is a JSON-able dict, a string, a ``(status, body, headers)`` tuple, or a callable that takes the
    request and returns one of those.
    """

    def __init__(self, routes: Dict[str, Reply], error: Optional[Exception] = None) -> None:
        super().__init__()
        self.routes = routes
        self.error = error
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        reply = next((r for key, r in self.routes.items() if key in request.url), None)
        if callable(reply):
            reply = reply(request)
        status, body, headers = 200, reply, {}
        if reply is None:
            status, body = 404, '{"service-error": {"status": {"statusCode": "RESOURCE_NOT_FOUND"}}}'
        elif isinstance(reply, tuple):
            status, body, headers = (reply + ({},))[:3]
        resp = requests.Response()
        resp.status_code = status
        resp._content = (json.dumps(body) if isinstance(body, (dict, list)) else str(body)).encode("utf-8")
        resp.headers.update(headers)
        resp.encoding = "utf-8"
        resp.url = request.url
        resp.request = request
        return resp


def params(request) -> Dict[str, str]:
    """The query parameters of a request, one value each."""
    return {k: v[0] for k, v in parse_qs(urlparse(request.url).query).items()}


@pytest.fixture
def fake():
    """A factory for an Elsevier client backed by a FakeAdapter; returns ``(client, adapter)``."""
    from elsevier_stream.client import Client

    def factory(routes: Dict[str, Reply], **kwargs):
        session = requests.Session()
        adapter = FakeAdapter(routes, kwargs.pop("error", None))
        session.mount("https://", adapter)
        return Client(api_key=kwargs.pop("api_key", "test-key"), session=session, min_interval=0, **kwargs), adapter
    return factory


# -- synthetic Elsevier records, shaped like the real responses --------------------------------------------

def scopus_entry(n: int, doi: Optional[str] = None, year: str = "2025") -> dict:
    return {"eid": f"2-s2.0-{n}", "dc:title": f"Study {n} of gut microbiota", "prism:doi": doi or f"10.1000/x{n}",
            "pubmed-id": str(30000000 + n), "prism:publicationName": "Journal A", "prism:coverDate": f"{year}-05-01",
            "subtypeDescription": "Article", "dc:creator": "Smith J.", "citedby-count": str(n % 7),
            "openaccessFlag": n % 2 == 0}


def scopus_page(entries, total: int, next_cursor: Optional[str] = None) -> dict:
    page = {"search-results": {"opensearch:totalResults": str(total),
                               "entry": entries or [{"@_fa": "true", "error": "Result set was empty"}]}}
    if next_cursor:
        page["search-results"]["cursor"] = {"@current": "*", "@next": next_cursor}
    return page


def abstract_record(n: int, doi: Optional[str] = None, pii: Optional[str] = None, single: bool = False) -> dict:
    """An abstract record; with *single*, lists of one element come as bare objects, as Scopus sends them."""
    authors = [{"preferred-name": {"ce:surname": "van der Berg", "ce:given-name": "Anna"}},
               {"ce:surname": "Lee", "ce:initials": "K."}]
    keywords = [{"$": "frailty"}, {"$": "microbiome"}]
    core = {"eid": f"2-s2.0-{n}", "dc:identifier": f"SCOPUS_ID:{n}", "dc:title": f"Study {n} of gut microbiota",
            "dc:description": f"Abstract {n}: butyrate rose in older adults.", "prism:doi": doi or f"10.1000/x{n}",
            "pubmed-id": str(30000000 + n), "prism:publicationName": "Journal A", "prism:coverDate": "2025-05-01",
            "prism:volume": "12", "prism:issueIdentifier": "3", "prism:pageRange": "101-110",
            "dc:publisher": "Publisher B", "subtypeDescription": "Review", "openaccessFlag": "true",
            "citedby-count": "42"}
    if pii:
        core["pii"] = pii
    return {"abstracts-retrieval-response": {
        "coredata": core,
        "authors": {"author": authors[0] if single else authors},
        "affiliation": {"affilname": "University C", "affiliation-city": "Boston", "affiliation-country": "USA"},
        "authkeywords": {"author-keyword": keywords[0] if single else keywords},
        "idxterms": {"mainterm": {"$": "Aged"}},
        "subject-areas": {"subject-area": [{"$": "Medicine (all)"}]},
    }}


def reference_page(refs, total: int) -> dict:
    return {"abstracts-retrieval-response": {"references": {"@total-references": str(total), "reference": refs}}}


def reference(n: int) -> dict:
    return {"scopus-eid": f"2-s2.0-9{n}", "ce:doi": f"10.2000/r{n}", "pubmed-id": str(20000000 + n),
            "title": f"Landmark {n}", "sourcetitle": "Journal R", "prism:coverDate": "2001-01-01", "@id": str(n)}
