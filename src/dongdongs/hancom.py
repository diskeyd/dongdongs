"""Can this Python drive Hancom Office (한글) through COM?

``apply`` is the only step that needs it, and on 2026-09-17 a user's run died
at ``import pyhwpx`` with "라이브러리가 등록되지 않았습니다" after three hours of
analysis and review: the type library was not registered for that process.
Everything here only reads the registry, so it is safe to call from any step;
``dispatch_test`` is the one call that actually starts 한글 and is used by
``dongdongs doctor`` alone.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

PROGID = "HWPFrame.HwpObject"
# other names Hancom has used for the same automation object
PROGID_ALIASES = (PROGID, "HWPFrame.HwpObject.1", "HwpCtrl.Object", "HWPFrame.HwpCtrl", "Hwp.Application")


def python_bits() -> int:
    return struct.calcsize("P") * 8


def _registry() -> dict:
    """ProgID and install keys, read in both the 64-bit and the 32-bit registry view."""
    import winreg

    def has(root: int, sub: str, view: int) -> bool:
        try:
            winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view).Close()
            return True
        except OSError:
            return False

    def versions(view: int) -> set[str]:
        found: set[str] = set()
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(root, r"SOFTWARE\HNC\Hwp", 0, winreg.KEY_READ | view)
            except OSError:
                continue
            index = 0
            while True:
                try:
                    found.add(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
            key.Close()
        return found

    return {
        "progid_64bit": has(winreg.HKEY_CLASSES_ROOT, rf"{PROGID}\CLSID", winreg.KEY_WOW64_64KEY),
        "progid_32bit": has(winreg.HKEY_CLASSES_ROOT, rf"{PROGID}\CLSID", winreg.KEY_WOW64_32KEY),
        "versions_64bit": sorted(versions(winreg.KEY_WOW64_64KEY)),
        "versions_32bit": sorted(versions(winreg.KEY_WOW64_32KEY)),
    }


def probe() -> dict:
    """What the registry says about 한글 here, plus a Korean verdict for the user."""
    info: dict = {
        "python_bits": python_bits(),
        "installed": False,
        "product_name": None,
        "version": None,
        "progid_64bit": False,
        "progid_32bit": False,
        "com_available": False,
    }
    if sys.platform != "win32":
        info["verdict"] = "한글 반영은 Windows 에서만 됩니다."
        return info

    info.update(_registry())
    versions = info["versions_64bit"] + info["versions_32bit"]
    if versions:
        info["installed"] = True
        info["product_name"] = "Hancom Office Hwp"
        info["version"] = sorted(versions)[-1]
    mine = "progid_64bit" if info["python_bits"] == 64 else "progid_32bit"
    other = "progid_32bit" if mine == "progid_64bit" else "progid_64bit"
    info["com_available"] = bool(info[mine])
    if info["com_available"]:
        info["installed"] = True
        info["verdict"] = "한글 COM 을 쓸 수 있습니다."
    elif info[other]:
        info["verdict"] = f"한글은 {64 if other == 'progid_64bit' else 32}비트이고 이 프로그램은 {info['python_bits']}비트라서 서로 연결되지 않습니다."
    elif info["installed"]:
        info["verdict"] = "한글은 설치돼 있지만 COM 자동화가 등록되어 있지 않습니다. 한글을 한 번 직접 실행해 본 뒤 다시 시도하세요."
    else:
        info["verdict"] = "이 PC 에서 한글(한컴오피스)을 찾지 못했습니다."
    return info


def details() -> dict:
    """Everything ``doctor`` needs to tell a viewer-only install from an unregistered one."""
    if sys.platform != "win32":
        return {"progids": {}, "install_values": {}, "executables": []}
    import glob
    import os
    import winreg

    progids: dict[str, str] = {}
    for name in PROGID_ALIASES:
        views = []
        for label, view in (("64", winreg.KEY_WOW64_64KEY), ("32", winreg.KEY_WOW64_32KEY)):
            try:
                winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{name}\CLSID", 0, winreg.KEY_READ | view).Close()
                views.append(label)
            except OSError:
                pass
        progids[name] = "+".join(views) if views else "없음"

    install: dict[str, str] = {}
    for root, root_name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                base = winreg.OpenKey(root, r"SOFTWARE\HNC\Hwp", 0, winreg.KEY_READ | view)
            except OSError:
                continue
            index = 0
            while True:
                try:
                    version = winreg.EnumKey(base, index)
                except OSError:
                    break
                index += 1
                try:
                    key = winreg.OpenKey(base, version, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                for value_index in range(winreg.QueryInfoKey(key)[1]):
                    try:
                        name, value, _kind = winreg.EnumValue(key, value_index)
                    except OSError:
                        break
                    if isinstance(value, str) and value:
                        install[f"{root_name}\\HNC\\Hwp\\{version}\\{name or '(기본값)'}"] = value
                key.Close()
            base.Close()

    executables = []
    for folder in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA"))):
        for pattern in ("Hnc/*/*/Bin/*.exe", "Hnc/*/*/*.exe", "Hnc/*/*.exe"):
            executables += [p for p in glob.glob(os.path.join(folder, pattern)) if Path(p).name.lower().startswith(("hwp", "hoffice"))]
    return {"progids": progids, "install_values": install, "executables": sorted(set(executables))[:12]}


def dispatch_test() -> dict:
    """Actually start 한글 through COM and close it again. Only ``doctor`` calls this."""
    if sys.platform != "win32":
        return {"tried": False, "reason": "Windows 전용"}
    try:
        import win32com.client
    except ImportError as exc:
        return {"tried": False, "reason": f"pywin32 없음: {exc}"}
    try:
        api = win32com.client.Dispatch(PROGID)
    except Exception as exc:  # noqa: BLE001 - the error code is what we are after
        return {"tried": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        api.Quit()
    except Exception:  # noqa: BLE001 - it started, that is what matters
        pass
    return {"tried": True, "ok": True}


def pyhwpx_test() -> dict:
    """``import pyhwpx`` builds the COM type library wrapper; that import is what failed for the user."""
    try:
        import pyhwpx  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - com_error included
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True}


__all__ = ["PROGID", "PROGID_ALIASES", "details", "dispatch_test", "probe", "pyhwpx_test", "python_bits"]
