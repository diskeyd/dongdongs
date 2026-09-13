"""Report ledger: which test sections of one HWP report are already filled.

One report is filled from several test reports that arrive at different times.
Each job fills only the sections of its own test report. When
``verify --stage hwp`` passes, the ledger records those sections and the newest
processed HWP, so the next job can continue from that file instead of the
original. A section is ``done`` only when nothing of it is left to decide or
failed; otherwise it is ``partial`` (or ``blocked`` when something could not be
placed at all). Kept in ``work/_reports/<report>.json`` on this PC only; it is not
part of the error-report zip.
"""

from __future__ import annotations

import re
from pathlib import Path

from .environment import now_kst
from .job import Job, read_json, report_stem, sha256_file, write_json

LEDGER_DIR = "_reports"
DONE_STATUSES = ("applied", "skipped_no_op")


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip() or "report"


def ledger_path(work_root: Path, hwp: Path) -> Path:
    return Path(work_root) / LEDGER_DIR / f"{_safe(report_stem(Path(hwp)))}.json"


def load_ledger(path: Path) -> dict | None:
    path = Path(path)
    return read_json(path) if path.is_file() else None


def list_ledgers(work_root: Path) -> list[tuple[Path, dict]]:
    folder = Path(work_root) / LEDGER_DIR
    if not folder.is_dir():
        return []
    return [(path, read_json(path)) for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)]


def usable_latest(ledger: dict | None, work_root: Path) -> Path | None:
    """The newest processed HWP of the report, if it still exists unchanged."""
    latest = (ledger or {}).get("latest") or {}
    if not latest.get("processed_hwp"):
        return None
    path = Path(latest["processed_hwp"])
    path = path if path.is_absolute() else Path(work_root) / path
    if not path.is_file() or (latest.get("sha256") and sha256_file(path) != latest["sha256"]):
        return None
    return path


def parse_numbers(text: str) -> list[int] | None:
    """'2, 10-12' -> [2, 10, 11, 12] in the order given; None when the text is not numbers, commas and ranges."""
    if not re.fullmatch(r"\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*", text or ""):
        return None
    numbers: list[int] = []
    for part in text.split(","):
        start, _, end = part.partition("-")
        numbers.extend(range(int(start), int(end) + 1) if end.strip() else [int(start)])
    return numbers


def section_numbers(no) -> list[int]:
    """Report section numbers of a scope: 3 -> [3], "2,3" -> [2, 3], None -> []."""
    if isinstance(no, int):
        return [no]
    return [int(n) for n in str(no).split(",") if n.strip().isdigit()] if no else []


def update_ledger(job: Job, work_root: Path | None = None) -> tuple[Path, dict]:
    work_root = Path(work_root or job.root.parent)
    manifest = job.manifest()
    candidates = read_json(job.path("mapping_candidates.json"))
    log = read_json(job.path("apply_log.json"))
    path = ledger_path(work_root, job.hwp)
    ledger = load_ledger(path) or {"report": report_stem(job.hwp), "created_at": now_kst(), "sections": {}, "history": []}
    for section in candidates.get("hwp_sections") or []:
        ledger["sections"].setdefault(str(section["no"]), {"no": section["no"], "title": section["title"], "code": section.get("code"), "status": "pending"})
    applied = {c["id"]: c.get("apply_status") for c in log.get("changes", [])}
    approved_path = job.path("approved_changes.json")
    decisions = {c["id"]: c.get("decision") for c in read_json(approved_path).get("changes", [])} if approved_path.is_file() else {}
    touched: list[int] = []
    for scope in candidates.get("scopes") or []:
        changes = [c for c in candidates.get("changes", []) if (c.get("section") or {}).get("key") == scope["key"]]
        if not any(applied.get(c["id"]) in DONE_STATUSES for c in changes):
            continue
        # still open: an item nobody decided on (held), or an approved one that did not go in
        still_open = [
            c for c in changes
            if c.get("status") != "blocked" and not c.get("no_op")
            and (decisions.get(c["id"]) not in ("approve", "reject") or (decisions.get(c["id"]) == "approve" and applied.get(c["id"]) not in DONE_STATUSES))
        ]
        status = "partial" if still_open else "blocked" if any(c.get("status") == "blocked" for c in changes) else "done"
        for no in section_numbers(scope["no"]):
            entry = ledger["sections"].setdefault(str(no), {"no": no, "title": scope["title"], "code": scope.get("code"), "status": "pending"})
            entry.update(status=status, job=manifest["job_id"], at=now_kst())
            touched.append(no)
    processed = Path(log["processed_hwp"])
    try:
        stored = str(processed.resolve().relative_to(work_root.resolve()))
    except ValueError:
        stored = str(processed)
    ledger["latest"] = {"job": manifest["job_id"], "processed_hwp": stored, "sha256": sha256_file(processed)}
    ledger["history"].append({"job": manifest["job_id"], "at": now_kst(), "parent_job": manifest.get("parent_job"), "sections": touched})
    write_json(path, ledger)
    return path, ledger


def section_counts(ledger: dict | None) -> dict[str, int]:
    statuses = [s.get("status", "pending") for s in (ledger or {}).get("sections", {}).values()]
    return {"total": len(statuses), **{name: statuses.count(name) for name in ("done", "partial", "blocked", "pending")}}


def status_line(ledger: dict | None) -> str:
    counts = section_counts(ledger)
    partial = f" · 일부 {counts['partial']}" if counts["partial"] else ""
    return f"구역 {counts['total']}개 중 반영 {counts['done']}{partial} · 차단 {counts['blocked']} · 대기 {counts['pending']}"


def numbers_with_status(ledger: dict | None, status: str) -> list[int]:
    return sorted(s["no"] for s in (ledger or {}).get("sections", {}).values() if s.get("status") == status)


def compact_numbers(numbers) -> str:
    """[1, 8, 10, 11, 12] -> '1, 8, 10–12'."""
    values = sorted(set(int(n) for n in numbers))
    parts: list[str] = []
    start = prev = None
    for value in values + [None]:
        if value is not None and prev is not None and value == prev + 1:
            prev = value
            continue
        if start is not None:
            parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = value
    return ", ".join(parts)


__all__ = ["compact_numbers", "ledger_path", "list_ledgers", "load_ledger", "numbers_with_status", "parse_numbers", "section_counts", "section_numbers", "status_line", "update_ledger", "usable_latest"]
