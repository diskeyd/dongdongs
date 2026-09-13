from dongdongs.pdf.tables import extract_document


def _rows(result):
    return [(t["section"], r["label"], r["unit"], r["value"]) for t in result["tables"] for r in t["rows"]]


def test_golden_page_matches_expected_values(fixture_pdf, keri, expected):
    e = expected["tables"]
    result = extract_document(fixture_pdf, keri["tables"]["known_sections"], pages=[e["golden_page"]])
    assert _rows(result) == [tuple(row) for row in e["golden_rows"]]


def test_subscripts_are_flagged_with_markup(fixture_pdf, keri, expected):
    e = expected["tables"]
    result = extract_document(fixture_pdf, keri["tables"]["known_sections"], pages=[e["golden_page"]])
    table = next(t for t in result["tables"] if t["section"] == e["subscript_section"])
    assert [r["label_markup"] for r in table["rows"]] == e["subscript_markup"]
    assert all("label_has_sub_or_superscript" in r["flags"] for r in table["rows"])


def test_evidence_is_recorded(fixture_pdf, keri, expected):
    e = expected["tables"]
    result = extract_document(fixture_pdf, keri["tables"]["known_sections"], pages=[e["golden_page"]])
    source = result["tables"][0]["source"]
    assert source["pdf_page"] == e["golden_page"] and source["printed_page"] == e["printed_page"]
    assert all(len(c["bbox"]) == 4 for t in result["tables"] for r in t["rows"] for c in r["cells"])


def test_all_table_pages_are_found(fixture_pdf, keri, expected):
    e = expected["tables"]
    result = extract_document(fixture_pdf, keri["tables"]["known_sections"])
    assert result["pages_scanned"] == e["table_pages"]
    tables = [t for t in result["tables"] if t["section"] == e["supply_section"]]
    assert len(tables) == e["supply_tables"] and all(len(t["rows"]) == e["supply_rows"] for t in tables)
    assert not [r for t in result["tables"] for r in t["rows"] if "irregular_row" in r["flags"]]


def test_cleaning_does_not_change_extracted_text(fixture_pdf, cleaned, keri):
    before = extract_document(fixture_pdf, keri["tables"]["known_sections"])
    after = extract_document(cleaned[0], keri["tables"]["known_sections"])
    assert _rows(before) == _rows(after)
