"""Local review server (handoff section 10).

Binds to 127.0.0.1 only. Serves the review page, evidence crops and region
PNGs from the job directory, and writes the reviewer's decisions to
``approved_changes.json``. Nothing is sent anywhere else.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from jinja2 import Environment, select_autoescape

from ..environment import now_kst
from ..job import Job, read_json, write_json

SERVED_DIRS = ("previews", "images")
DECISIONS = ("approve", "reject", "hold")
MAX_BODY = 5 * 1024 * 1024


def _template():
    text = resources.files(__package__).joinpath("templates", "review.html").read_text(encoding="utf-8")
    return Environment(autoescape=select_autoescape(["html"])).from_string(text)


def _optional(job: Job, name: str):
    path = job.path(name)
    return read_json(path) if path.is_file() else None


def render_page(job: Job) -> str:
    candidates = read_json(job.path("mapping_candidates.json"))
    saved = _optional(job, "approved_changes.json") or {"changes": []}
    watermark = _optional(job, "watermark_report.json")
    verification = _optional(job, "verification_clean.json")
    pages: dict[int, list[dict]] = {}
    for change in candidates["changes"]:
        pages.setdefault(change["source"].get("pdf_page", 0), []).append(change)
    return _template().render(
        manifest=job.manifest(),
        candidates=candidates,
        pages=sorted(pages.items()),
        decisions={c["id"]: c for c in saved["changes"]},
        watermark=watermark,
        verification=verification,
        saved_at=saved.get("saved_at"),
    )


def save_decisions(job: Job, payload: dict) -> dict:
    candidates = {c["id"]: c for c in read_json(job.path("mapping_candidates.json"))["changes"]}
    entries = []
    for change_id, decision in (payload.get("decisions") or {}).items():
        base = candidates.get(change_id)
        if base is None or not isinstance(decision, dict):
            continue
        choice = decision.get("decision") if decision.get("decision") in DECISIONS else "hold"
        entry = dict(base)
        entry["flags"] = list(base.get("flags", []))
        if base["kind"] == "set_cell_text":
            entry["after"] = str(decision.get("after", base["after"]))
            entry["edited"] = entry["after"] != base.get("after_extracted", base["after"])
            entry["no_op"] = entry["after"].strip() == base["before"].strip()
        if base.get("status") == "blocked" and choice == "approve":
            choice = "hold"
            entry["flags"].append("approval_refused_item_is_blocked")
        entry["decision"] = choice
        entry["note"] = str(decision.get("note", ""))[:500]
        entries.append(entry)
    data = {
        "job_id": job.manifest()["job_id"],
        "saved_at": now_kst(),
        "reviewer": (payload.get("reviewer") or "").strip()[:100] or None,
        "changes": entries,
    }
    write_json(job.path("approved_changes.json"), data)
    return {
        "saved": len(entries),
        "approved": sum(1 for e in entries if e["decision"] == "approve"),
        "rejected": sum(1 for e in entries if e["decision"] == "reject"),
        "held": sum(1 for e in entries if e["decision"] == "hold"),
        "saved_at": data["saved_at"],
    }


def make_handler(job: Job):
    root = job.root.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "dongdongs-review"

        def log_message(self, format, *args):  # keep the console quiet
            return

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if path in ("/", "/index.html"):
                self._send(HTTPStatus.OK, render_page(job).encode("utf-8"), "text/html; charset=utf-8")
                return
            if path.startswith("/files/"):
                target = (root / path[len("/files/"):]).resolve()
                allowed = any(target.is_relative_to(root / d) for d in SERVED_DIRS)
                if allowed and target.is_file():
                    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                    self._send(HTTPStatus.OK, target.read_bytes(), content_type)
                    return
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if urllib.parse.urlsplit(self.path).path != "/save":
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
                return
            host, port = self.server.server_address[:2]
            origin = self.headers.get("Origin")
            if origin not in (None, f"http://{host}:{port}", f"http://localhost:{port}"):
                self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain; charset=utf-8")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._send(HTTPStatus.BAD_REQUEST, b"bad request", "text/plain; charset=utf-8")
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(HTTPStatus.BAD_REQUEST, b"invalid json", "text/plain; charset=utf-8")
                return
            result = save_decisions(job, payload)
            self._send(HTTPStatus.OK, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    return Handler


def make_server(job: Job, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(job))


def serve(job: Job, port: int = 8765, open_browser: bool = True) -> None:
    server = make_server(job, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"검수 서버: {url}  (종료: Ctrl+C)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
