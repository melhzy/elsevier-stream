"""The HTTP client for Elsevier's APIs: the key, rate limits, quotas and errors.

Every request carries the researcher's API key in the ``X-ELS-APIKey``
header, and an institutional token (``X-ELS-Insttoken``) when one is
configured.  Elsevier allows about nine requests a second per API and a
weekly quota per key: 20,000 Scopus searches, 10,000 abstract records.
The client paces requests, retries those that fail for a moment, and turns
Elsevier's refusals into errors that say what to do.

The key comes from, in order: an explicit argument, ``ELSEVIER_API_KEY``,
the key the Claude Code plugin passes (``ELSEVIER_STREAM_API_KEY``), the
user's ``~/.elsevier-stream.json``, and a ``.env`` file in the current folder.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from . import __version__
from .settings import API_KEY_SETTING, INSTTOKEN_SETTING, dotenv_value, saved_setting, user_settings_file

logger = logging.getLogger(__name__)

API_BASE = "https://api.elsevier.com/content"
API_KEY_ENV = "ELSEVIER_API_KEY"
# The Claude Code plugin passes the key the user gave it under its own name, so that it never
# overrides the user's variable; it is empty when the user gave none
PLUGIN_API_KEY_ENV = "ELSEVIER_STREAM_API_KEY"
INSTTOKEN_ENV = "ELSEVIER_INSTTOKEN"
KEY_PAGE = "https://dev.elsevier.com/apikey/manage"

MIN_INTERVAL = 0.12   # seconds between requests: Elsevier allows about 9 a second per API
MAX_RETRIES = 3
RETRY_DELAY = 2.0     # seconds, times the attempt number
TIMEOUT = 60          # seconds

NO_KEY_MESSAGE = (f"No Elsevier API key is configured. Create one at {KEY_PAGE}, then save it with "
                  "'elsevier-stream init --api-key YOUR-KEY', or set ELSEVIER_API_KEY.")


class ElsevierError(Exception):
    """Elsevier refused or failed a request; the message says why, with the API key removed."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class NoApiKey(ElsevierError):
    """No API key is configured."""


class NotEntitled(ElsevierError):
    """The key, the network or the institutional token does not give access to this resource (403)."""


class NotFound(ElsevierError):
    """Elsevier has no such record (404)."""


class QuotaExceeded(ElsevierError):
    """The key's weekly quota for an API is used up."""


def configured_api_key(folder: str = ".") -> Optional[str]:
    """The Elsevier API key from the environment, the user's settings or a ``.env`` file; None when there is none."""
    return (os.getenv(API_KEY_ENV) or os.getenv(PLUGIN_API_KEY_ENV) or saved_setting(API_KEY_SETTING)
            or dotenv_value(API_KEY_ENV, folder))


def configured_insttoken() -> Optional[str]:
    """The institutional token from the environment or the user's settings, if any."""
    return os.getenv(INSTTOKEN_ENV) or saved_setting(INSTTOKEN_SETTING) or dotenv_value(INSTTOKEN_ENV)


def api_key_status(folder: str = ".") -> str:
    """One line on the API key in use: its last characters and where it comes from, or that there is none."""
    sources = ((API_KEY_ENV, os.getenv(API_KEY_ENV)), ("the plugin", os.getenv(PLUGIN_API_KEY_ENV)),
               (str(user_settings_file()), saved_setting(API_KEY_SETTING)),
               (".env", dotenv_value(API_KEY_ENV, folder)))
    for source, key in sources:
        if key:
            return f"on (…{key[-4:]}, from {source})"
    return f"off: create a key at {KEY_PAGE} and run elsevier-stream init --api-key YOUR-KEY"


def _status_text(resp: requests.Response) -> str:
    """Elsevier's explanation of a failed request, from its header or its JSON body."""
    status = resp.headers.get("X-ELS-Status")
    if status:
        return status
    try:
        error = resp.json().get("service-error", {}).get("status", {})
        return f"{error.get('statusCode', '')} - {error.get('statusText', '')}".strip(" -")
    except ValueError:
        return resp.text[:200]


class Client:
    """A session for Elsevier's APIs, shared by the functions of this package."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        insttoken: Optional[str] = None,
        session: Optional[requests.Session] = None,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        self.api_key = api_key or configured_api_key()
        if not self.api_key:
            raise NoApiKey(NO_KEY_MESSAGE)
        self.insttoken = insttoken or configured_insttoken()
        self.session = session or requests.Session()
        self.min_interval = max(0.0, min_interval)
        self.quota: Dict[str, Dict[str, Any]] = {}   # per API: remaining requests and when the quota resets
        self._lock = threading.Lock()
        self._last = 0.0

    def _wait(self) -> None:
        with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()

    def _redact(self, text: str) -> str:
        text = text.replace(self.api_key, "***")
        return text.replace(self.insttoken, "***") if self.insttoken else text

    def _note_quota(self, api: str, resp: requests.Response) -> None:
        remaining, reset = resp.headers.get("X-RateLimit-Remaining"), resp.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            entry = {"remaining": int(remaining), "limit": int(resp.headers.get("X-RateLimit-Limit", 0) or 0)}
            if reset and reset.isdigit():
                entry["resets"] = datetime.fromtimestamp(int(reset), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            self.quota[api] = entry

    def request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
                json_body: Optional[Dict[str, Any]] = None, accept: str = "application/json") -> requests.Response:
        """Call ``API_BASE/path``, retrying failures of the moment; raises an :class:`ElsevierError` subclass."""
        headers = {"X-ELS-APIKey": self.api_key, "Accept": accept, "User-Agent": f"elsevier-stream/{__version__}"}
        if self.insttoken:
            headers["X-ELS-Insttoken"] = self.insttoken
        api = "/".join(path.split("/")[:2])   # the quota's API: search/scopus, abstract/eid, article/doi, ...
        error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            self._wait()
            try:
                resp = self.session.request(method, f"{API_BASE}/{path}", params=params, json=json_body,
                                            headers=headers, timeout=TIMEOUT)
            except requests.RequestException as e:
                error = self._redact(str(e))
            else:
                self._note_quota(api, resp)
                status = resp.status_code
                if status < 400:
                    return resp
                text = self._redact(_status_text(resp))
                if status == 429 and self.quota.get(api, {}).get("remaining") == 0:
                    resets = self.quota[api].get("resets", "next week")
                    raise QuotaExceeded(f"The weekly quota of this API key for {api} is used up; it resets {resets}",
                                        status)
                if status == 401:
                    raise ElsevierError(f"Elsevier rejected the API key ({text}). Check it at {KEY_PAGE} and save it "
                                        "again with 'elsevier-stream init --api-key'", status)
                if status == 403:
                    raise NotEntitled(f"Not available with this key and network ({text})", status)
                if status == 404:
                    raise NotFound(f"Not found ({text})", status)
                if status < 500 and status != 429:
                    raise ElsevierError(f"Elsevier refused the request ({text})", status)
                error = f"HTTP {status}: {text}"
            if attempt < MAX_RETRIES:
                logger.warning("%s attempt %d/%d failed: %s", path, attempt, MAX_RETRIES, error)
                time.sleep(RETRY_DELAY * attempt)
        raise ElsevierError(f"{path} failed after {MAX_RETRIES} attempts: {error}")

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.request("GET", path, params=params).json()

    def close(self) -> None:
        self.session.close()
