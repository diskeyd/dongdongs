"""Work directory for one test-report PDF.

::

    work/<job-id>/
      manifest.json  environment.json
      pdf_inspection.json  watermark_report.json  verification_clean.json
      extracted_values.json  sections.json  regions.json  hwp_inventory.json
      mapping_candidates.json  approved_changes.json  apply_log.json  verification_hwp.json
      cleaned_pdf/  images/  previews/  logs/  result/
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .environment import KST, now_kst

SUBDIRS = ("cleaned_pdf", "images", "previews", "logs", "result")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _describe(path: Path) -> dict:
    return {"path": str(path), "name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def report_stem(path: Path) -> str:
    """Name of the report behind a file: ``보고서.processed.processed.hwp`` -> ``보고서``."""
    stem = Path(path).stem
    while True:
        trimmed = re.sub(r"\.(processed|before)$", "", stem)
        if trimmed == stem:
            return stem
        stem = trimmed


@dataclass(frozen=True)
class Job:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def manifest(self) -> dict:
        return read_json(self.manifest_path)

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @property
    def pdf(self) -> Path:
        return Path(self.manifest()["inputs"]["pdf"]["path"])

    @property
    def hwp(self) -> Path | None:
        entry = self.manifest()["inputs"].get("hwp")
        return Path(entry["path"]) if entry else None

    @property
    def cleaned_pdf(self) -> Path:
        return self.path("cleaned_pdf", f"{self.pdf.stem}.cleaned.pdf")

    def update(self, **fields) -> None:
        manifest = self.manifest()
        manifest.update(fields)
        write_json(self.manifest_path, manifest)

    def record_step(self, step: str, **info) -> None:
        manifest = self.manifest()
        manifest.setdefault("steps", []).append({"step": step, "at": now_kst(), **info})
        write_json(self.manifest_path, manifest)


def create_job(work_root: Path, pdf: Path, hwp: Path | None = None, job_id: str | None = None, parent_job: str | None = None) -> Job:
    # messages name only the file type: they reach logs and the error-report zip
    pdf = pdf.resolve()
    if not pdf.is_file():
        raise FileNotFoundError(f"PDF 파일을 찾지 못했습니다 (<file{pdf.suffix.lower()}>)")
    if hwp is not None:
        hwp = hwp.resolve()
        if not hwp.is_file():
            raise FileNotFoundError(f"HWP 파일을 찾지 못했습니다 (<file{hwp.suffix.lower()}>)")
    # the default name is only the time: a name made from the PDF would carry the customer's file name
    job_id = job_id or f"{dt.datetime.now(KST):%Y%m%d-%H%M%S}"
    root = (work_root / job_id).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"job directory is not empty: {root}")
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    inputs = {"pdf": _describe(pdf)}
    if hwp is not None:
        inputs["hwp"] = _describe(hwp)
        # a report is filled over several jobs; a later job starts from the previous job's result
        inputs["hwp"]["role"] = f"processed_of:{parent_job}" if parent_job else "original"
    write_json(
        root / "manifest.json",
        {"job_id": job_id, "created_at": now_kst(), "inputs": inputs, "institution": None, "parent_job": parent_job, "steps": []},
    )
    return Job(root)


def open_job(path: Path) -> Job:
    job = Job(path.resolve())
    if not job.manifest_path.is_file():
        raise FileNotFoundError(f"not a job directory (manifest.json missing): {job.root}")
    return job
