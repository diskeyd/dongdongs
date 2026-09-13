"""Hancom Office COM editor (Windows only).

STATUS: written on macOS and NOT YET RUN on Windows. The calls follow the
HwpAutomation API (HWPFrame.HwpObject) as wrapped by pyhwpx. Every write is
guarded by read-backs: the anchor text and the target cell's current content
must match the reviewed ``before`` value, otherwise the change is skipped,
never forced.

The original HWP is never opened. ``apply`` copies it to
``result/<name>.before.hwp`` and ``result/<name>.processed.hwp`` and edits only
the processed copy.

Three kinds of change are applied:

* ``set_cell_text``          replace the text of one table cell
* ``replace_picture``        delete the picture in a cell and insert a PNG at the same size
* ``fill_oscillogram_page``  rewrite the title line of a graph page and insert its graphs at the
                             planned size; pages that do not exist yet are made by copying the
                             last graph page of the same test section, right after it
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from ..job import report_stem, sha256_file
from .mapping import anchor_page_of, cell_address, hu_to_mm

_ADDRESS = re.compile(r"\b([A-Z]{1,3})(\d{1,4})\b")
SIZE_TOLERANCE = 0.01  # 1 % of the planned size


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


def size_matches(expected: tuple[int, int], found: tuple[int, int], tolerance: float = SIZE_TOLERANCE) -> bool:
    return all(abs(e - f) <= max(1, e * tolerance) for e, f in zip(expected, found))


class HwpEditor:
    def __init__(self, visible: bool = False) -> None:
        if sys.platform != "win32":
            raise EditorError("HWP editing needs Windows with Hancom Office (COM). Run 'apply' on the Windows PC.")
        from pyhwpx import Hwp  # registers the bundled security module (FilePathCheckerModule) in HKCU

        self.api = Hwp(new=True, visible=visible, register_module=True)
        self.hwp = self.api.hwp

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

    def page_count(self) -> int | None:
        try:
            return int(self.hwp.PageCount)
        except Exception:  # noqa: BLE001 - property missing on old versions
            return None

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

    def insert_text(self, text: str) -> None:
        action = self.hwp.CreateAction("InsertText")
        pset = action.CreateSet()
        action.GetDefault(pset)
        pset.SetItem("Text", text.replace("\n", "\r\n"))
        action.Execute(pset)

    def set_cell_text(self, text: str) -> None:
        if self.cell_text():
            self._select_cell_content()
            self._run("Delete")
        if text:
            self.insert_text(text)
        self._run("Cancel")

    # pictures -----------------------------------------------------------
    def pictures_in_cell(self) -> list:
        """Picture controls anchored in the current cell, in document order."""
        self._run("Cancel")
        self._run("MoveListBegin")
        found = []
        ctrl = self.hwp.HeadCtrl
        # walk the control chain and keep the pictures whose anchor lies in this list
        here = self.hwp.GetPos()[0]
        while ctrl is not None:
            try:
                if ctrl.CtrlID == "gso" and ctrl.GetAnchorPos(0).Item("List") == here:
                    found.append(ctrl)
            except Exception:  # noqa: BLE001 - controls without anchors
                pass
            ctrl = ctrl.Next
        return found

    def picture_size(self, ctrl) -> tuple[int, int, bool]:
        prop = ctrl.Properties
        return int(prop.Item("Width")), int(prop.Item("Height")), bool(prop.Item("TreatAsChar"))

    def delete_ctrl(self, ctrl) -> None:
        if not self.hwp.DeleteCtrl(ctrl):
            raise EditorError("could not delete the picture control")

    def insert_picture(self, png: Path, width_hu: int, height_hu: int, treat_as_char: bool = True):
        """Insert a PNG at the caret at exactly ``width_hu`` x ``height_hu`` HWPUNIT."""
        ctrl = self.hwp.InsertPicture(
            Path=str(png),
            Embedded=True,
            sizeoption=1,
            Reverse=False,
            watermark=False,
            Effect=0,
            Width=hu_to_mm(width_hu),
            Height=hu_to_mm(height_hu),
        )
        if not ctrl:
            raise EditorError(f"InsertPicture failed for {png.name}")
        prop = ctrl.Properties
        prop.SetItem("Width", int(width_hu))
        prop.SetItem("Height", int(height_hu))
        prop.SetItem("TreatAsChar", 1 if treat_as_char else 0)
        ctrl.Properties = prop
        width, height, _ = self.picture_size(ctrl)
        if not size_matches((width_hu, height_hu), (width, height)):
            raise EditorError(f"inserted picture is {width}x{height} HWPUNIT, planned {width_hu}x{height_hu}")
        return ctrl

    def replace_picture(self, png: Path, width_hu: int, height_hu: int, expected_size: tuple[int, int] | None) -> dict:
        pictures = self.pictures_in_cell()
        treat_as_char = True
        if pictures:
            width, height, treat_as_char = self.picture_size(pictures[0])
            if expected_size is not None and not size_matches(tuple(expected_size), (width, height)):
                raise EditorError(f"picture in the cell is {width}x{height}, review saw {expected_size[0]}x{expected_size[1]}")
            for ctrl in pictures:
                self.delete_ctrl(ctrl)
        self._run("MoveListBegin")
        if treat_as_char:
            self._run("ParagraphShapeAlignCenter")  # an inline picture is centred in its cell; a floating one keeps its anchor
        self.insert_picture(png, width_hu, height_hu, treat_as_char)
        left = self.pictures_in_cell()
        if len(left) != 1:
            raise EditorError(f"{len(left)} pictures in the cell after replacement")
        return {"width": width_hu, "height": height_hu, "treat_as_char": treat_as_char}

    # graph pages --------------------------------------------------------
    def copy_current_frame_after_itself(self, copies: int) -> None:
        """Duplicate the page frame table that holds the caret ``copies`` times right after it."""
        for _ in range(copies):
            self._run("Cancel")
            self._run("TableCellBlock")
            self._run("TableCellBlockExtend")
            self._run("TableCellBlockExtend")
            if not self._run("Copy"):
                raise EditorError("could not copy the page frame")
            self._run("Cancel")
            self._run("CloseEx")  # leave the table
            self._run("MoveNextParaBegin")
            if not self._run("Paste"):
                raise EditorError("could not paste the page frame")
            self._run("Cancel")

    def fill_graph_page(self, title_before: str, title_after: str, pictures: list[dict]) -> dict:
        """Rewrite the title line of the current graph-page cell and insert the graphs below it."""
        current = self.cell_text()
        if title_before and _norm(title_before) not in _norm(current):
            raise EditorError(f"graph page title {title_before!r} not found in the cell")
        for ctrl in self.pictures_in_cell():
            self.delete_ctrl(ctrl)
        self._select_cell_content()
        self._run("Delete")
        self.insert_text("\n" + title_after + "\n")
        rows: list[list[dict]] = []
        for pic in pictures:
            if pic["layout"] == "half-right" and rows and rows[-1][0]["layout"] == "half-left" and len(rows[-1]) == 1:
                rows[-1].append(pic)
            else:
                rows.append([pic])
        for index, row in enumerate(rows):
            if index:
                self.insert_text("\n")
            self._run("ParagraphShapeAlignCenter")  # graphs sit centred like on the PDF page
            for pic in row:
                self.insert_picture(Path(pic["png_path"]), pic["width_hwpunit"], pic["height_hwpunit"], treat_as_char=True)
        self._run("Cancel")
        found = self.pictures_in_cell()
        if len(found) != len(pictures):
            raise EditorError(f"{len(found)} pictures in the graph page after filling, planned {len(pictures)}")
        return {"title": title_after, "pictures": len(found)}


def prepare_result_copies(original: Path, result_dir: Path) -> tuple[Path, Path]:
    result_dir.mkdir(parents=True, exist_ok=True)
    # continuing from a previous result keeps the report's own name: 보고서.processed.hwp, never .processed.processed
    before = result_dir / f"{report_stem(original)}.before.hwp"
    processed = result_dir / f"{report_stem(original)}.processed.hwp"
    if before.exists() or processed.exists():
        raise EditorError("결과 파일이 이미 있습니다. 덮어쓰지 않으니 새 작업으로 다시 실행하세요")
    digest = sha256_file(original)
    shutil.copy2(original, before)
    shutil.copy2(original, processed)
    if sha256_file(before) != digest or sha256_file(processed) != digest:
        raise EditorError("copy verification failed; original left untouched")
    return before, processed


def _goto_anchor(editor: HwpEditor, change: dict) -> None:
    anchor = change["anchor"]
    editor.goto_occurrence(anchor["text"], anchor["occurrence"])
    if editor.current_address() != anchor["address"] or _norm(anchor["text"]) not in _norm(editor.cell_text()):
        raise EditorError(f"anchor mismatch at {editor.current_address()}")


def _apply_order(change: dict) -> tuple:
    """Graph pages first, in page order; a section's new pages before its last page is retitled (it is their anchor)."""
    hwp = change.get("hwp", {})
    is_graph = change["kind"] == "fill_oscillogram_page"
    added = bool(hwp.get("page_to_be_added"))
    page = (hwp.get("page_no_before") or hwp.get("page_no") or 0) if is_graph else 0
    return (not is_graph, page, not added, hwp.get("copies_after_anchor") or 0)


def apply_changes(original: Path, result_dir: Path, approved: list[dict], visible: bool = False, job_root: Path | None = None) -> dict:
    before, processed = prepare_result_copies(original, result_dir)
    editor = HwpEditor(visible=visible)
    log: list[dict] = []
    pages_before = pages_after = None
    added_pages: set[int] = set()
    copies: list[dict] = []
    try:
        editor.open(processed)
        pages_before = editor.page_count()
        ordered = sorted(approved, key=_apply_order)
        # new graph pages of one section hang off the same anchor (the section's last graph page)
        to_add: dict[str, int] = {}
        for change in ordered:
            if change["kind"] == "fill_oscillogram_page" and change["hwp"].get("page_to_be_added") and not change.get("no_op"):
                to_add[change["anchor"]["text"]] = to_add.get(change["anchor"]["text"], 0) + 1
        copied: set[str] = set()
        for change in ordered:
            entry = {"id": change["id"], "kind": change["kind"]}
            try:
                if change["kind"] == "set_cell_text":
                    if change.get("no_op") and change["after"] == change["before"]:
                        entry["apply_status"] = "skipped_no_op"
                    else:
                        _goto_anchor(editor, change)
                        editor.goto_cell(change["hwp"]["address"])
                        current = editor.cell_text()
                        if _norm(current) != _norm(change["before"]):
                            entry.update(apply_status="skipped_before_mismatch", found=current)
                        else:
                            editor.set_cell_text(change["after"])
                            readback = editor.cell_text()
                            entry.update(apply_status="applied" if _norm(readback) == _norm(change["after"]) else "readback_mismatch", readback=readback)
                elif change["kind"] == "replace_picture":
                    _goto_anchor(editor, change)
                    editor.goto_cell(change["hwp"]["address"])
                    target = change["target"]
                    png = (job_root / change["after_png"]) if job_root else Path(change["after_png"])
                    result = editor.replace_picture(png, target["width_hwpunit"], target["height_hwpunit"], tuple(change["hwp"].get("size_hwpunit") or ()) or None)
                    entry.update(apply_status="applied", inserted=result)
                elif change["kind"] == "fill_oscillogram_page" and change.get("no_op"):
                    entry["apply_status"] = "skipped_no_op"
                elif change["kind"] == "fill_oscillogram_page":
                    _goto_anchor(editor, change)
                    editor.goto_cell(change["hwp"]["address"])
                    if change["hwp"].get("page_to_be_added"):
                        group = change["anchor"]["text"]
                        if group not in copied:
                            # first new page of this section: make all of the section's approved copies right after its last graph page
                            editor.copy_current_frame_after_itself(to_add[group])
                            copied.add(group)
                            copies.append({"anchor": group, "anchor_page": anchor_page_of(change), "count": to_add[group]})
                            _goto_anchor(editor, change)
                        # copies still carry the old title; renamed ones no longer match, so the first hit is the next unfilled copy
                        editor._run("CloseEx")
                        if not editor.find_forward(change["anchor"]["text"]):
                            raise EditorError("copied graph page not found after the anchor")
                        editor._run("Cancel")
                        editor.goto_cell(change["hwp"]["address"])
                        added_pages.add(change["hwp"].get("page_no_after") or change["hwp"]["page_no"])
                    pictures = []
                    for pic in change["pictures"]:
                        pictures.append({**pic, "png_path": str((job_root / pic["png"]) if job_root else Path(pic["png"]))})
                    result = editor.fill_graph_page(change["before"], change["after"], pictures)
                    entry.update(apply_status="applied", inserted=result)
                else:
                    entry["apply_status"] = "skipped_not_implemented"
            except EditorError as exc:
                entry.update(apply_status="error", error=str(exc))
            except Exception as exc:  # noqa: BLE001 - unknown Hancom failure: stop editing, save what is done
                entry.update(apply_status="error", error=f"{type(exc).__name__}: {exc}")
                log.append({**change, **entry})
                done = {e["id"] for e in log}
                log.extend({**c, "apply_status": "skipped_after_error"} for c in ordered if c["id"] not in done)
                break
            log.append({**change, **entry})
        pages_after = editor.page_count()
        editor.save_as(processed)
    finally:
        editor.close()
    return {
        "before_hwp": str(before),
        "processed_hwp": str(processed),
        "page_count_before": pages_before,
        "page_count_after": pages_after,
        "pages_added": sorted(added_pages),
        "copies": copies,
        "changes": log,
    }


__all__ = ["EditorError", "HwpEditor", "apply_changes", "cell_address", "prepare_result_copies", "size_matches"]
