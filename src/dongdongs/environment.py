"""Environment probe written to ``environment.json`` (handoff section 12).

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
    """Detect Hancom Office through the registry.

    The registry locations below are the commonly documented ones and have not
    been checked on the target Windows PC yet; ``com_available`` is the value
    that matters for ``apply``.
    """
    info: dict = {"installed": False, "product_name": None, "version": None, "com_available": False}
    if sys.platform != "win32":
        info["note"] = "Hancom Office COM is Windows-only; not probed on this OS"
        return info

    import winreg

    def open_key(root, sub):
        try:
            return winreg.OpenKey(root, sub)
        except OSError:
            return None

    key = open_key(winreg.HKEY_CLASSES_ROOT, r"HWPFrame.HwpObject\CLSID")
    if key is not None:
        info["com_available"] = True
        key.Close()

    versions: set[str] = set()
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for base in (r"SOFTWARE\HNC\Hwp", r"SOFTWARE\WOW6432Node\HNC\Hwp"):
            key = open_key(root, base)
            if key is None:
                continue
            index = 0
            while True:
                try:
                    versions.add(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
            key.Close()
    if versions:
        info["installed"] = True
        info["product_name"] = "Hancom Office Hwp"
        info["version"] = sorted(versions)[-1]
    if info["com_available"]:
        info["installed"] = True
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
