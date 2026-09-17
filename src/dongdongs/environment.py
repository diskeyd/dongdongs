"""Environment probe written to ``environment.json``.

Only facts needed to reproduce a run are recorded: OS, Python, dependency
versions, Hancom COM availability and whether a Gemini key is present.
Key values and user-specific paths are never written.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata as md
import os
import platform
import sys
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9), "KST")
DEPENDENCIES = ("pymupdf", "pyhwp", "google-genai", "pyyaml", "jinja2", "pillow", "pywin32")


def now_kst() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def _version(dist: str) -> str | None:
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None


def _scrub(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if home and path.startswith(home) else path


def _hancom() -> dict:
    """Hancom Office as seen from this process (see ``hancom.probe``)."""
    from .hancom import probe

    info = probe()
    if sys.platform != "win32":
        info["note"] = "Hancom Office COM is Windows-only; not probed on this OS"
    return info


def collect(gemini_connectivity: str = "not-run") -> dict:
    return {
        "captured_at": now_kst(),
        "os": {
            "name": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": _scrub(sys.executable),
        },
        "hancom": _hancom(),
        "dependencies": {name: _version(name) for name in DEPENDENCIES},
        "gemini": {
            "api_key_present": bool(os.environ.get("GEMINI_API_KEY")),
            "api_key_value_saved": False,
            "connectivity_test": gemini_connectivity,
        },
    }
