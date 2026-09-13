"""Test sections of one test-report PDF.

A report usually lists its tests on one page (KERI: "시험 결과" with number,
name(code), place and start page). Each entry becomes a section running to the
page before the next test; the last test ends where the table of contents says
the drawings start. Institutions without a ``sections`` rule, or PDFs without
such a page, return ``found: False`` and the caller treats the PDF as one scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _content_end(texts: list[str], rules: dict, last_start: int, page_count: int, offset: int) -> tuple[int, str]:
    wanted = {_squash(t) for t in rules.get("end_titles", [])}
    found: list[int] = []
    for text in texts:
        lines = _lines(text)
        for i, line in enumerate(lines[:-1]):
            if _squash(line) in wanted and lines[i + 1].isdigit():
                page = int(lines[i + 1]) + offset
                if last_start < page <= page_count + 1:
                    found.append(page)
    if found:
        return min(found) - 1, "table_of_contents"
    return page_count, "document_end"


def read_test_index(pdf_path: Path, rules: dict | None) -> dict:
    rules = rules or {}
    title = rules.get("index_title")
    if not title:
        return {"found": False, "reason": "no sections rule for this institution", "sections": []}
    code_re = re.compile(rules.get("code_pattern", r"\(([A-Za-z]\w*)\)"))
    offset = int(rules.get("page_offset", 0))
    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        texts = [page.get_text() for page in doc]
    for index, text in enumerate(texts):
        if _squash(title) not in _squash(text):
            continue
        lines = _lines(text)
        entries = []
        for j, line in enumerate(lines):
            match = code_re.search(line)
            if not match:
                continue
            start = next((int(lines[k]) for k in range(j + 1, min(len(lines), j + 4)) if lines[k].isdigit()), None)
            if start is None or not 1 <= start + offset <= page_count:
                continue
            no = int(lines[j - 1]) if j and lines[j - 1].isdigit() else len(entries) + 1
            entries.append(
                {
                    "no": no,
                    "title": " ".join(line.split()),
                    "name": " ".join((line[: match.start()] + line[match.end():]).split()),
                    "code": match.group(1),
                    "page_from": start + offset,
                }
            )
        if len(entries) < int(rules.get("min_entries", 2)):
            continue
        entries.sort(key=lambda e: e["page_from"])
        end, end_source = _content_end(texts, rules, entries[-1]["page_from"], page_count, offset)
        for current, following in zip(entries, entries[1:]):
            current["page_to"] = max(current["page_from"], following["page_from"] - 1)
        entries[-1]["page_to"] = max(entries[-1]["page_from"], end)
        return {"found": True, "index_page": index + 1, "end_page": end, "end_source": end_source, "page_count": page_count, "sections": entries}
    return {"found": False, "reason": f"no page lists tests under {title!r}", "page_count": page_count, "sections": []}


__all__ = ["read_test_index"]
