"""Run logs, the ``dongdongs.env`` file and the error-report zip.

Nothing here touches the report PDF or HWP. The report zip is built from an
allow-list of small JSON and log files, and every input file name is replaced
by a placeholder so the zip can be attached to a public issue.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import platform
import re
import sys
import traceback
import zipfile
from pathlib import Path

from . import __version__
from .environment import now_kst

ENV_FILE = "dongdongs.env"
REPORT_DIR = "reports"
SECRET_KEYS = ("GEMINI_API_KEY",)

# files copied into the default report zip (job root, relative names)
REPORT_JSON = ("manifest.json", "environment.json", "watermark_report.json", "verification_clean.json", "verification_hwp.json")
# files that hold report values; only with --full
FULL_ONLY_JSON = ("extracted_values.json", "regions.json", "hwp_inventory.json", "mapping_candidates.json", "approved_changes.json", "apply_log.json", "pdf_inspection.json")
DATA_SUFFIXES = {".pdf", ".hwp", ".hwpx", ".png", ".jpg", ".jpeg", ".xml", ".bmp", ".gif", ".tif", ".tiff"}


# ------------------------------------------------------------------ project
def project_root(start: Path | None = None) -> Path:
    """Folder that holds pyproject.toml: the unzipped download or the checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return (start or Path.cwd()).resolve()


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


def load_env_file(path: Path | None = None) -> list[str]:
    """Fill os.environ from dongdongs.env; existing variables win. Returns the keys set."""
    candidates = [path] if path else [Path.cwd() / ENV_FILE, project_root() / ENV_FILE]
    for candidate in candidates:
        if candidate and candidate.is_file():
            loaded = []
            for key, value in parse_env_text(candidate.read_text(encoding="utf-8-sig")).items():
                if value and not os.environ.get(key):
                    os.environ[key] = value
                    loaded.append(key)
            return loaded
    return []


# ---------------------------------------------------------------- run logs
class RunLog:
    """Tee stdout/stderr into logs/run-<time>-<command>.log."""

    def __init__(self, directory: Path, command: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = directory / f"run-{stamp}-{command}.log"
        self._file = self.path.open("a", encoding="utf-8")
        self._file.write(f"# dongdongs {__version__} · {now_kst()} · {command}\n# argv: {' '.join(_scrub_argv(sys.argv[1:]))}\n")
        self._streams: list[tuple[str, object]] = []

    def start(self) -> None:
        for name in ("stdout", "stderr"):
            original = getattr(sys, name)
            self._streams.append((name, original))
            setattr(sys, name, _Tee(original, self._file))

    def write_exception(self, exc: BaseException) -> None:
        self._file.write("\n# traceback\n")
        self._file.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        self._file.flush()

    def stop(self) -> None:
        for name, original in self._streams:
            setattr(sys, name, original)
        self._streams.clear()
        self._file.close()


class _Tee(io.TextIOBase):
    def __init__(self, primary, secondary) -> None:
        self.primary, self.secondary = primary, secondary

    def write(self, text: str) -> int:
        self.primary.write(text)
        self.secondary.write(text)
        return len(text)

    def flush(self) -> None:
        self.primary.flush()
        self.secondary.flush()

    @property
    def encoding(self):
        return getattr(self.primary, "encoding", "utf-8")

    def isatty(self) -> bool:
        return bool(getattr(self.primary, "isatty", lambda: False)())

    def fileno(self) -> int:
        return self.primary.fileno()


def _scrub_argv(argv: list[str]) -> list[str]:
    """Keep flags and plain words; any path-like argument becomes <file.ext> so no file name is logged."""
    out = []
    for a in argv:
        if "/" in a or "\\" in a or Path(a).suffix.lower() in DATA_SUFFIXES:
            out.append(f"<file{Path(a).suffix.lower()}>")
        else:
            out.append(a)
    return out


def log_directory(job_root: Path | None) -> Path:
    return (job_root / "logs") if job_root is not None else project_root() / "logs"


# ------------------------------------------------------------------ report
def _placeholders(manifest: dict | None) -> dict[str, str]:
    names: dict[str, str] = {}
    if not manifest:
        return names
    for kind, entry in manifest.get("inputs", {}).items():
        name = entry.get("name") or Path(entry.get("path", "")).name
        if name:
            names[name] = f"<{kind}>"
            stem = Path(name).stem
            if len(stem) > 3:
                names[stem] = f"<{kind}-name>"
        path = entry.get("path")
        if path:
            names[path] = f"<{kind}-path>"
    return dict(sorted(names.items(), key=lambda kv: -len(kv[0])))


def redact_text(text: str, names: dict[str, str]) -> str:
    for name, placeholder in names.items():
        text = text.replace(name, placeholder)
    home = str(Path.home())
    if home:
        text = text.replace(home, "~")
    for key in SECRET_KEYS:
        text = re.sub(rf"({key}\s*=\s*)\S+", r"\1<redacted>", text)
    return text


def redact_json(data, names: dict[str, str]):
    if isinstance(data, dict):
        return {k: redact_json(v, names) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_json(v, names) for v in data]
    if isinstance(data, str):
        return redact_text(data, names)
    return data


def latest_job(work_root: Path) -> Path | None:
    jobs = [p for p in work_root.glob("*/manifest.json")]
    if not jobs:
        return None
    return max(jobs, key=lambda p: p.stat().st_mtime).parent


def report_summary(job_root: Path | None, manifest: dict | None, full: bool) -> str:
    lines = [
        f"dongdongs {__version__}",
        f"만든 시각: {now_kst()}",
        f"OS: {platform.system()} {platform.release()} · Python {platform.python_version()}",
        f"포함 범위: {'전체(값 포함) — 공개 이슈에 올리지 말 것' if full else '기본(로그·환경·단계 기록만)'}",
        "",
    ]
    if job_root is None:
        lines.append("작업 폴더: 없음 (설치 또는 init 전에 난 오류)")
        return "\n".join(lines) + "\n"
    lines.append(f"작업: {manifest.get('job_id') if manifest else job_root.name}")
    lines.append(f"기관: {manifest.get('institution') if manifest else '?'}")
    lines.append("")
    lines.append("단계 기록:")
    for step in (manifest or {}).get("steps", []):
        extra = {k: v for k, v in step.items() if k not in ("step", "at")}
        lines.append(f"  - {step.get('at', '')} {step.get('step', '')} {json.dumps(extra, ensure_ascii=False) if extra else ''}")
    apply_log = job_root / "apply_log.json"
    if apply_log.is_file():
        try:
            entries = json.loads(apply_log.read_text(encoding="utf-8")).get("changes", [])
            counts: dict[str, int] = {}
            for entry in entries:
                counts[entry.get("apply_status", "?")] = counts.get(entry.get("apply_status", "?"), 0) + 1
            lines.append(f"반영 결과: {json.dumps(counts, ensure_ascii=False)}")
        except (ValueError, OSError):
            lines.append("반영 결과: apply_log.json 을 읽지 못함")
    return "\n".join(lines) + "\n"


def build_report_zip(job_root: Path | None, out_dir: Path, full: bool = False) -> Path:
    """Write reports/dongdongs-report-<job>-<time>.zip and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = None
    if job_root is not None and (job_root / "manifest.json").is_file():
        manifest = json.loads((job_root / "manifest.json").read_text(encoding="utf-8"))
    names = _placeholders(manifest)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    label = redact_text((manifest or {}).get("job_id") or (job_root.name if job_root else "no-job"), names)
    label = re.sub(r"[^0-9A-Za-z._-]+", "-", label).strip("-")[:40] or "job"
    out = out_dir / f"dongdongs-report-{label}-{stamp}{'-full' if full else ''}.zip"

    def add_text(zf: zipfile.ZipFile, arcname: str, text: str) -> None:
        zf.writestr(arcname, redact_text(text, names))

    def add_json(zf: zipfile.ZipFile, arcname: str, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return
        zf.writestr(arcname, json.dumps(redact_json(data, names), ensure_ascii=False, indent=1))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.txt", redact_text(report_summary(job_root, manifest, full), names))
        env_file = project_root() / ENV_FILE
        if env_file.is_file():
            keys = parse_env_text(env_file.read_text(encoding="utf-8-sig"))
            zf.writestr("dongdongs.env.keys.txt", "\n".join(f"{k}={'<set>' if v else '<empty>'}" for k, v in keys.items()) + "\n")
        for log in sorted((project_root() / "logs").glob("run-*.log")):
            add_text(zf, f"logs/project/{log.name}", log.read_text(encoding="utf-8", errors="replace"))
        if job_root is not None:
            wanted = list(REPORT_JSON) + (list(FULL_ONLY_JSON) if full else [])
            for name in wanted:
                path = job_root / name
                if path.is_file():
                    add_json(zf, f"job/{name}", path)
            for log in sorted((job_root / "logs").glob("run-*.log")):
                add_text(zf, f"logs/job/{log.name}", log.read_text(encoding="utf-8", errors="replace"))
        # safety: nothing with a data suffix can be in the archive
        for info in zf.infolist():
            if Path(info.filename).suffix.lower() in DATA_SUFFIXES:
                raise RuntimeError(f"report zip must not contain {info.filename}")
    return out


__all__ = [
    "ENV_FILE",
    "REPORT_DIR",
    "RunLog",
    "build_report_zip",
    "latest_job",
    "load_env_file",
    "log_directory",
    "parse_env_text",
    "project_root",
    "redact_json",
    "redact_text",
]
