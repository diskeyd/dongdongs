"""Work directory for one PDF job (handoff section 2.3).

::

    work/<job-id>/
      manifest.json  environment.json
      pdf_inspection.json  watermark_report.json  verification_clean.json
      extracted_values.json  regions.json  hwp_inventory.json
      mapping_candidates.json  approved_changes.json  apply_log.json
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


def _slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", text).strip("-")[:40] or "job"


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


def create_job(work_root: Path, pdf: Path, hwp: Path | None = None, job_id: str | None = None) -> Job:
    pdf = pdf.resolve()
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    if hwp is not None:
        hwp = hwp.resolve()
        if not hwp.is_file():
            raise FileNotFoundError(hwp)
    job_id = job_id or f"{dt.datetime.now(KST):%Y%m%d-%H%M%S}-{_slug(pdf.stem)}"
    root = (work_root / job_id).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"job directory is not empty: {root}")
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    inputs = {"pdf": _describe(pdf)}
    if hwp is not None:
        inputs["hwp"] = _describe(hwp)
    write_json(
        root / "manifest.json",
        {"job_id": job_id, "created_at": now_kst(), "inputs": inputs, "institution": None, "steps": []},
    )
    return Job(root)


def open_job(path: Path) -> Job:
    job = Job(path.resolve())
    if not job.manifest_path.is_file():
        raise FileNotFoundError(f"not a job directory (manifest.json missing): {job.root}")
    return job
