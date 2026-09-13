"""Hancom Office COM editor (Windows only).

STATUS: written on macOS and NOT YET RUN on Windows. The calls follow the
HwpAutomation API (HWPFrame.HwpObject). Every write is guarded by read-backs:
the anchor header cell and the target cell's current text must match the
reviewed ``before`` value, otherwise the change is skipped, never forced.

The original HWP is never opened. ``apply`` copies it to
``result/<name>.before.hwp`` and ``result/<name>.processed.hwp`` and edits only
the processed copy.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from ..job import sha256_file
from .mapping import cell_address

_ADDRESS = re.compile(r"\b([A-Z]{1,3})(\d{1,4})\b")


class EditorError(RuntimeError):
    pass


def _norm(text: str) -> str:
    return " ".join((text or "").replace("\r\n", "\n").split()).casefold()


def _parse(address: str) -> tuple[int, int]:
    match = _ADDRESS.fullmatch(address)
    if not match:
        raise EditorError(f"bad cell address {address!r}")
    col = 0
    for ch in match.group(1):
        col = col * 26 + (ord(ch) - 64)
    return int(match.group(2)) - 1, col - 1


class HwpEditor:
    def __init__(self, visible: bool = False) -> None:
        if sys.platform != "win32":
            raise EditorError("HWP editing needs Windows with Hancom Office (COM). Run 'apply' on the Windows PC.")
        import win32com.client

        self.hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
        try:
            self.hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
        except Exception:
            pass  # without the security module Hancom may ask for confirmation when opening files
        try:
            self.hwp.XHwpWindows.Item(0).Visible = visible
        except Exception:
            pass

    # document -----------------------------------------------------------
    def open(self, path: Path) -> None:
        if not self.hwp.Open(str(path), "HWP", "forceopen:true"):
            raise EditorError(f"Hancom could not open {path}")

    def save_as(self, path: Path) -> None:
        if not self.hwp.SaveAs(str(path), "HWP", ""):
            raise EditorError(f"Hancom could not save {path}")

    def close(self) -> None:
        try:
            self.hwp.Clear(1)
        finally:
            self.hwp.Quit()

    # navigation ---------------------------------------------------------
    def _run(self, action: str) -> bool:
        return bool(self.hwp.HAction.Run(action))

    def find_forward(self, text: str) -> bool:
        pset = self.hwp.HParameterSet.HFindReplace
        self.hwp.HAction.GetDefault("RepeatFind", pset.HSet)
        pset.FindString = text
        pset.Direction = self.hwp.FindDir("Forward")
        pset.IgnoreMessage = 1
        pset.MatchCase = 1
        pset.FindRegExp = 0
        return bool(self.hwp.HAction.Execute("RepeatFind", pset.HSet))

    def goto_occurrence(self, text: str, occurrence: int) -> None:
        self._run("Cancel")
        self._run("MoveDocBegin")
        for _ in range(occurrence):
            if not self.find_forward(text):
                raise EditorError(f"occurrence {occurrence} of {text!r} not found")
        self._run("Cancel")

    def current_address(self) -> str | None:
        indicator = self.hwp.KeyIndicator()
        name = str(indicator[-1]) if isinstance(indicator, (tuple, list)) else str(indicator)
        match = _ADDRESS.search(name)
        return match.group(0) if match else None

    def goto_cell(self, address: str, max_steps: int = 400) -> None:
        target_row, target_col = _parse(address)
        for _ in range(max_steps):
            current = self.current_address()
            if current is None:
                raise EditorError("cursor is not inside a table cell")
            if current == address:
                return
            row, col = _parse(current)
            if row < target_row:
                moved = self._run("TableLowerCell")
            elif row > target_row:
                moved = self._run("TableUpperCell")
            elif col < target_col:
                moved = self._run("TableRightCell")
            else:
                moved = self._run("TableLeftCell")
            if not moved or self.current_address() == current:
                raise EditorError(f"stuck at {current} while moving to {address} (merged cells?)")
        raise EditorError(f"could not reach {address} in {max_steps} moves")

    # cell text ----------------------------------------------------------
    def _select_cell_content(self) -> None:
        self._run("Cancel")
        self._run("MoveListBegin")
        self._run("MoveSelListEnd")

    def cell_text(self) -> str:
        self._select_cell_content()
        text = self.hwp.GetTextFile("TEXT", "saveblock") or ""
        self._run("Cancel")
        return text.replace("\r\n", "\n").strip("\n")

    def set_cell_text(self, text: str) -> None:
        if self.cell_text():
            self._select_cell_content()
            self._run("Delete")
        if text:
            action = self.hwp.CreateAction("InsertText")
            pset = action.CreateSet()
            action.GetDefault(pset)
            pset.SetItem("Text", text.replace("\n", "\r\n"))
            action.Execute(pset)
        self._run("Cancel")


def prepare_result_copies(original: Path, result_dir: Path) -> tuple[Path, Path]:
    result_dir.mkdir(parents=True, exist_ok=True)
    before = result_dir / f"{original.stem}.before.hwp"
    processed = result_dir / f"{original.stem}.processed.hwp"
    if before.exists() or processed.exists():
        raise EditorError(f"result copies already exist in {result_dir}; start a new job instead of overwriting")
    digest = sha256_file(original)
    shutil.copy2(original, before)
    shutil.copy2(original, processed)
    if sha256_file(before) != digest or sha256_file(processed) != digest:
        raise EditorError("copy verification failed; original left untouched")
    return before, processed


def apply_changes(original: Path, result_dir: Path, approved: list[dict], visible: bool = False) -> dict:
    before, processed = prepare_result_copies(original, result_dir)
    editor = HwpEditor(visible=visible)
    log: list[dict] = []
    try:
        editor.open(processed)
        for change in approved:
            entry = {"id": change["id"], "kind": change["kind"]}
            if change["kind"] != "set_cell_text":
                entry["apply_status"] = "skipped_not_implemented"
            elif change.get("no_op") and change["after"] == change["before"]:
                entry["apply_status"] = "skipped_no_op"
            else:
                try:
                    anchor = change["anchor"]
                    editor.goto_occurrence(anchor["text"], anchor["occurrence"])
                    if editor.current_address() != anchor["address"] or _norm(editor.cell_text()) != _norm(anchor["text"]):
                        raise EditorError(f"anchor mismatch at {editor.current_address()}")
                    editor.goto_cell(change["hwp"]["address"])
                    current = editor.cell_text()
                    if _norm(current) != _norm(change["before"]):
                        entry.update(apply_status="skipped_before_mismatch", found=current)
                    else:
                        editor.set_cell_text(change["after"])
                        readback = editor.cell_text()
                        entry.update(apply_status="applied" if _norm(readback) == _norm(change["after"]) else "readback_mismatch", readback=readback)
                except EditorError as exc:
                    entry.update(apply_status="error", error=str(exc))
            log.append({**change, **entry})
        editor.save_as(processed)
    finally:
        editor.close()
    return {"before_hwp": str(before), "processed_hwp": str(processed), "changes": log}


__all__ = ["EditorError", "HwpEditor", "apply_changes", "cell_address", "prepare_result_copies"]
