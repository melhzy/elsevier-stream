"""Scopus search and records, and ScienceDirect search, against a fake Elsevier."""

from conftest import abstract_record, params, reference, reference_page, scopus_entry, scopus_page

from elsevier_stream.scopus import fetch_record, parse_abstract, search_scopus
from elsevier_stream.sciencedirect import search_sciencedirect


def test_search_lists_the_newest_matches_page_by_page(fake):
    def reply(request):
        cursor = params(request)["cursor"]
        if cursor == "*":
            return scopus_page([scopus_entry(n) for n in range(25)], 30, next_cursor="page2")
        return scopus_page([scopus_entry(n) for n in range(25, 30)], 30)

    client, adapter = fake({"search/scopus": reply})
    result = search_scopus('TITLE("gut microbiota")', 27, client=client)

    assert result.total_found == 30 and len(result.entries) == 27
    first = params(adapter.requests[0])
    assert (first["sort"], first["count"], first["cursor"]) == ("-coverDate", "25", "*")
    assert params(adapter.requests[1])["count"] == "2"            # only what is still wanted
    assert result.entries[0] == {"eid": "2-s2.0-0", "doi": "10.1000/x0", "pmid": "30000000",
                                 "title": "Study 0 of gut microbiota", "journal": "Journal A", "year": "2025",
                                 "type": "Article", "first_author": "Smith J.", "cited_by": 0, "open_access": True}
    assert "30 articles in Scopus" in str(result) and "PMID 30000000" in str(result)


def test_an_empty_search_has_no_entries(fake):
    client, _ = fake({"search/scopus": scopus_page([], 0)})
    result = search_scopus("TITLE(nothing)", 10, client=client)
    assert (result.total_found, result.entries) == (0, [])
    assert str(result) == "0 articles in Scopus for: TITLE(nothing)"


def test_count_only(fake):
    client, adapter = fake({"search/scopus": scopus_page([scopus_entry(1)], 53)})
    assert search_scopus("TITLE(x)", 0, client=client).entries == []
    assert len(adapter.requests) == 1


def test_parse_abstract_evens_out_single_objects():
    for single in (False, True):
        meta = parse_abstract(abstract_record(7, single=single))
        assert meta["authors"][0] == "van der Berg, Anna"
        assert meta["keywords"][0] == "frailty" and meta["index_terms"] == ["Aged"]
    meta = parse_abstract(abstract_record(7))
    assert meta["authors"] == ["van der Berg, Anna", "Lee, K."]
    assert (meta["scopus_id"], meta["year"], meta["pages"], meta["cited_by"], meta["open_access"]) == \
        ("7", "2025", "101-110", 42, True)
    assert meta["affiliations"] == ["University C, Boston, USA"] and meta["subject_areas"] == ["Medicine (all)"]


def test_references_are_paged_by_their_start_only(fake):
    # Scopus refuses a refcount that reaches the last reference exactly, so later pages give only startref
    def reply(request):
        p = params(request)
        if p.get("view") == "FULL":
            return abstract_record(7)
        assert "refcount" not in p
        start = int(p.get("startref", 1))
        return reference_page([reference(n) for n in range(start, min(start + 40, 59))], 58)

    client, adapter = fake({"abstract/eid": reply})
    meta = fetch_record("2-s2.0-7", client)

    assert len(meta["references"]) == 58
    assert [params(r).get("startref") for r in adapter.requests[1:]] == [None, "41"]
    assert meta["references"][0] == {"eid": "2-s2.0-91", "doi": "10.2000/r1", "pmid": "20000001",
                                     "title": "Landmark 1", "journal": "Journal R", "year": "2001"}
    assert fetch_record("2-s2.0-7", client, references=False)["references"] == []


def test_sciencedirect_search_marks_open_access(fake):
    def reply(request):
        import json
        body = json.loads(request.body)
        assert request.method == "PUT" and body["filters"] == {"openAccess": True}
        return {"resultsFound": 791, "results": [{"doi": "10.1016/j.x.2026.1", "pii": "S1", "title": "A  study",
                                                  "sourceTitle": "Journal D", "publicationDate": "2026-01-02",
                                                  "openAccess": True, "uri": "https://www.sciencedirect.com/x"}]}

    client, _ = fake({"search/sciencedirect": reply})
    result = search_sciencedirect("gut microbiota", 1, open_access=True, client=client)
    assert result.total_found == 791
    assert result.entries[0]["title"] == "A study" and result.entries[0]["year"] == "2026"
    assert "[open access]" in str(result)
