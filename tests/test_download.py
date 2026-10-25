"""Saving a search into a research folder, reading it back, and exporting citations."""

import json

from conftest import abstract_record, params, reference, reference_page, scopus_entry, scopus_page

from elsevier_stream.corpus import list_articles, most_cited, select
from elsevier_stream.download import download, folder_name
from elsevier_stream.export import export_citations

LONG_TEXT = "Introduction\n" + "Butyrate rose in older adults. " * 100


def elsevier(entries, full_text=(403, "", {"X-ELS-Status": "AUTHENTICATION_ERROR"}), quota_after=None):
    """Routes for a fake Elsevier with *entries*; ScienceDirect articles (n >= 100) have a PII."""
    served = []

    def abstract(request):
        eid = request.url.split("/abstract/eid/")[1].split("?")[0]
        n = int(eid.split("-")[-1])
        if params(request)["view"] == "REF":
            return reference_page([reference(1), reference(n)], 2)
        served.append(n)
        if quota_after is not None and len(served) > quota_after:
            return 429, "", {"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "10000"}
        return abstract_record(n, doi=f"10.1016/j.{n}" if n >= 100 else None, pii=f"S{n}" if n >= 100 else None)

    return {"search/scopus": scopus_page(entries, len(entries)), "abstract/eid": abstract, "article/": full_text}


def test_download_saves_records_and_skips_them_the_next_time(fake, tmp_path):
    client, adapter = fake(elsevier([scopus_entry(1), scopus_entry(2)]))
    progress = []
    stats = download('TITLE("gut microbiota")', 2, output_dir=tmp_path, client=client,
                     progress=lambda done, total, msg: progress.append((done, total)))

    folder = tmp_path / folder_name('TITLE("gut microbiota")')
    assert folder.name == "title_gut_microbiota"
    assert (stats.saved, stats.skipped, stats.errors, stats.full_texts, stats.not_entitled) == (2, 0, 0, 0, 0)
    assert progress == [(1, 2), (2, 2)]
    saved = json.loads((folder / "2-s2.0-1.json").read_text(encoding="utf-8"))
    assert saved["source"] == "scopus" and saved["text"] == ""
    assert saved["metadata"]["abstract"].startswith("Abstract 1") and len(saved["metadata"]["references"]) == 2
    assert not any("/article/" in r.url for r in adapter.requests)   # not ScienceDirect articles: no full text tried

    again = download('TITLE("gut microbiota")', 2, output_dir=tmp_path, client=client)
    assert (again.saved, again.skipped) == (0, 2)


def test_full_texts_are_tried_until_the_first_refusal(fake, tmp_path):
    client, adapter = fake(elsevier([scopus_entry(n) for n in (100, 101, 1)]))
    stats = download("x", 3, output_dir=tmp_path, client=client)
    assert (stats.saved, stats.full_texts, stats.not_entitled) == (3, 0, 2)
    assert sum("/article/" in r.url for r in adapter.requests) == 1       # one refusal, then no more tries
    assert "not available with this key and network" in str(stats)

    client, adapter = fake(elsevier([scopus_entry(100)], full_text=LONG_TEXT))
    stats = download("y", 1, output_dir=tmp_path, client=client)
    assert stats.full_texts == 1
    article = next(r for r in adapter.requests if "/article/" in r.url)
    assert article.headers["Accept"] == "text/plain" and "/article/pii/S100" in article.url
    saved = json.loads(next((tmp_path / "y").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["text"].startswith("Introduction")


def test_a_used_up_quota_stops_the_download(fake, tmp_path):
    client, _ = fake(elsevier([scopus_entry(n) for n in (1, 2, 3)], quota_after=1))
    stats = download("x", 3, output_dir=tmp_path, client=client, references=False)
    assert stats.saved == 1 and "weekly quota" in stats.stopped


def test_reading_back_and_exporting(fake, tmp_path):
    client, _ = fake(elsevier([scopus_entry(1), scopus_entry(100)]))
    download("x", 2, output_dir=tmp_path, client=client)
    download("x", 2, output_dir=tmp_path / "other", client=client)   # the same articles under a second folder

    records = list_articles(tmp_path)
    assert len(records) == 2 and records[0]["full_text"] is False
    assert {r["eid"] for r in records} == {"2-s2.0-1", "2-s2.0-100"}
    chosen, missing = select(records, ["doi:10.1016/j.100", "1", "30000001", "nope"])
    assert {r["eid"] for r in chosen} == {"2-s2.0-1", "2-s2.0-100"} and missing == ["nope"]

    top = most_cited(tmp_path, 1)[0]
    assert (top["eid"], top["cited_by"], top["title"]) == ("2-s2.0-91", 2, "Landmark 1")

    bib, count, _ = export_citations(tmp_path, "bibtex")
    assert count == 2 and "author = {van der Berg, Anna and Lee, K.}" in bib and "pages = {101--110}" in bib
    ris, _, _ = export_citations(tmp_path, "ris", ["2-s2.0-1"])
    assert "AU  - van der Berg, Anna" in ris and "UR  - https://doi.org/10.1000/x1" in ris
    assert "N1  - Scopus EID: 2-s2.0-1" in ris and "KW  - frailty" in ris
