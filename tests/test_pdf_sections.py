def test_test_list_page_gives_every_test_range(fixture_pdf, keri, expected):
    from dongdongs.pdf.sections import read_test_index

    index = read_test_index(fixture_pdf, keri.get("sections"))
    e = expected["pdf_sections"]
    assert index["found"] and index["index_page"] == e["index_page"] and index["end_page"] == e["end_page"]
    assert [[t["code"], t["page_from"], t["page_to"]] for t in index["sections"]] == e["tests"]
