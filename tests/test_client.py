"""The key, retries, quotas and Elsevier's refusals."""

import pytest
import requests

from elsevier_stream.client import (Client, ElsevierError, NoApiKey, NotEntitled, QuotaExceeded, api_key_status,
                                    configured_api_key)
from elsevier_stream.settings import set_setting, user_settings_file


def test_the_key_comes_from_the_environment_the_plugin_the_settings_then_dotenv(home, monkeypatch, tmp_path):
    assert configured_api_key() is None
    (tmp_path / ".env").write_text('export ELSEVIER_API_KEY="from-dotenv"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert configured_api_key() == "from-dotenv" and api_key_status().endswith("from .env)")
    set_setting(user_settings_file(), "api_key", "from-settings")
    assert configured_api_key() == "from-settings"
    monkeypatch.setenv("ELSEVIER_STREAM_API_KEY", "")              # the plugin's option, left empty
    assert configured_api_key() == "from-settings"
    monkeypatch.setenv("ELSEVIER_STREAM_API_KEY", "from-plugin")
    assert configured_api_key() == "from-plugin"
    monkeypatch.setenv("ELSEVIER_API_KEY", "from-environment-1234")
    assert configured_api_key() == "from-environment-1234"
    assert api_key_status() == "on (…1234, from ELSEVIER_API_KEY)"


def test_no_key_says_where_to_get_one():
    with pytest.raises(NoApiKey, match="dev.elsevier.com"):
        Client()
    assert api_key_status().startswith("off")


def test_headers_quota_and_a_retry(fake):
    calls = []

    def reply(request):
        calls.append(request)
        if len(calls) == 1:
            return 503, "busy"
        return 200, {"ok": True}, {"X-RateLimit-Remaining": "19990", "X-RateLimit-Limit": "20000",
                                   "X-RateLimit-Reset": "1793499428"}

    client, _ = fake({"search/scopus": reply}, insttoken="token-1")
    assert client.get_json("search/scopus", {"query": "x"}) == {"ok": True}
    assert len(calls) == 2
    assert calls[1].headers["X-ELS-APIKey"] == "test-key" and calls[1].headers["X-ELS-Insttoken"] == "token-1"
    assert client.quota["search/scopus"]["remaining"] == 19990 and "resets" in client.quota["search/scopus"]


def test_refusals_become_errors_that_say_what_to_do(fake):
    not_entitled = (403, {"service-error": {"status": {"statusCode": "AUTHENTICATION_ERROR"}}},
                    {"X-ELS-Status": "AUTHENTICATION_ERROR - Requestor configuration settings insufficient"})
    client, _ = fake({"article": not_entitled, "abstract": (401, "", {"X-ELS-Status": "Invalid API Key"}),
                      "search/scopus": (429, "", {"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "20000"}),
                      "bad": (400, "", {"X-ELS-Status": "INVALID_INPUT - syntax error"})})
    with pytest.raises(NotEntitled, match="Requestor configuration"):
        client.request("GET", "article/doi/10.1016/x")
    with pytest.raises(ElsevierError, match="rejected the API key") as e:
        client.request("GET", "abstract/eid/1")
    assert e.value.status == 401 and "test-key" not in str(e.value)
    with pytest.raises(QuotaExceeded, match="weekly quota"):
        client.request("GET", "search/scopus")
    with pytest.raises(ElsevierError, match="syntax error"):
        client.request("GET", "search/bad")


def test_network_errors_hide_the_key(fake):
    client, _ = fake({}, error=requests.ConnectionError("failed for https://x?apiKey=test-key"))
    with pytest.raises(ElsevierError) as e:
        client.request("GET", "search/scopus")
    assert "test-key" not in str(e.value) and "***" in str(e.value)
