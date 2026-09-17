"""``dongdongs start``: the question-and-answer flow behind run.bat.

Asks for the PDF, the HWP (or offers to continue a report from its previous
result) and a job name, then runs the same commands a developer would type:
init → analyze → (confirm sections) → review → apply → verify. Nothing is
written to the original files. Run once per test report as they arrive.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from .job import read_json
from .ledger import compact_numbers, ledger_path, list_ledgers, load_ledger, numbers_with_status, parse_numbers, status_line, usable_latest
from .support import project_root


def _ask(prompt: str, default: str | None = None) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{hint}: ").strip().strip('"').strip("'")
        if answer:
            return answer
        if default:
            return default


def _ask_file(prompt: str, suffixes: tuple[str, ...], optional: bool = False) -> Path | None:
    while True:
        answer = input(f"{prompt}{' (없으면 그냥 Enter)' if optional else ''}: ").strip().strip('"').strip("'")
        if not answer and optional:
            return None
        path = Path(answer).expanduser()
        if path.is_file() and path.suffix.lower() in suffixes:
            return path.resolve()
        print(f"  파일을 찾지 못했거나 확장자가 {'/'.join(suffixes)} 가 아닙니다. 파일을 이 창에 끌어다 놓고 Enter 를 누르세요.")


def _serve_review(job_root: Path, port: int = 8765) -> None:
    import threading
    import webbrowser

    from .job import open_job
    from .review.server import make_server

    server = make_server(open_job(job_root), port=port)
    host, real_port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{host}:{real_port}/"
    print(f"  검수 화면 주소: {url}  (자동으로 열리지 않으면 브라우저에 직접 입력)")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        input("  저장을 마쳤으면 Enter: ")
    finally:
        server.shutdown()
        server.server_close()


def _yes(prompt: str, default: bool = False) -> bool:
    answer = input(f"{prompt} {'[Y/n]' if default else '[y/N]'} ").strip().lower()
    return default if not answer else answer == "y"


def _ledger_line(ledger: dict) -> str:
    filled = compact_numbers(numbers_with_status(ledger, "done") + numbers_with_status(ledger, "partial") + numbers_with_status(ledger, "blocked"))
    return status_line(ledger) + (f" (반영된 구역: {filled})" if filled else "")


def choose_report(work: Path) -> tuple[Path | None, str | None]:
    """Offer to continue a report from its newest result. Returns (hwp, parent job) or (None, None)."""
    options = [(ledger, path) for _, ledger in list_ledgers(work) if (path := usable_latest(ledger, work)) is not None]
    if not options:
        return None, None
    if len(options) == 1:
        ledger, path = options[0]
        print(f"  작업 중인 보고서: {ledger['report']} — {_ledger_line(ledger)}")
        if _yes("  이 보고서의 이전 결과에 이어서 넣을까요? (새 보고서면 n)", default=True):
            return path, ledger["latest"]["job"]
        return None, None
    print("  작업 중인 보고서:")
    for number, (ledger, _) in enumerate(options, start=1):
        print(f"    {number}) {ledger['report']} — {_ledger_line(ledger)}")
    while True:
        answer = input("  이어서 넣을 보고서 번호 (새 보고서면 그냥 Enter): ").strip()
        if not answer:
            return None, None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            ledger, path = options[int(answer) - 1]
            return path, ledger["latest"]["job"]


def confirm_sections(job: Path, argv_main, use_gemini: bool) -> bool:
    """Make sure this test report goes to the right report sections. False when the user stops.

    The sections found from the test report's own list are shown for a yes/no.
    When none were found, or the user says no, the report's sections are listed
    and numbers must be given; an empty answer is not accepted, because the
    fallback (whole PDF against whole report) would put graphs in the wrong place.
    """
    index_path = job / "sections.json"
    tests = (read_json(index_path).get("sections") or []) if index_path.is_file() else []
    while True:
        candidates = read_json(job / "mapping_candidates.json")
        sections = candidates.get("hwp_sections") or []
        if not sections:
            return True  # the report has no "N. name(code)" headings: the whole document is one scope
        # whole mode maps the PDF against everything: never offer that as "the sections"
        scopes = [] if candidates["mode"] == "whole" else (candidates.get("scopes") or [])
        if scopes:
            print("\n이 성적서를 넣을 보고서 구역:")
            for scope in scopes:
                source = f"  ← 성적서 '{scope['pdf_title']}'" if scope.get("pdf_title") else ""
                print(f"  {scope['no']}. {scope['title']}{source}")
            if tests and candidates["mode"] == "auto" and len(scopes) == len(tests) and all(s.get("method") == "code" for s in scopes):
                # every test matched a section by its code: nothing to decide, so do not make the user wait here
                print(f"  성적서 시험 {len(tests)}개가 모두 시험 코드로 짝지어져 그대로 진행합니다.")
                return True
            if tests and candidates["mode"] == "auto" and len(scopes) < len(tests):
                print(f"  성적서 시험 {len(tests)}개 중 {len(scopes)}개만 보고서 구역을 찾았습니다.")
            if _yes("이 구역들이 맞나요?", default=True):
                return True
        elif candidates["mode"] == "auto":
            print("\n성적서 시험 목록의 이름·코드와 같은 보고서 구역을 찾지 못했습니다.")
        else:
            print("\n성적서에서 시험 목록을 찾지 못했습니다. 이 성적서가 채울 보고서 구역을 골라 주세요.")
        print("보고서 구역:")
        for section in sections:
            print(f"  {section['no']:>3}. {section['title']}")
        if tests:
            print(f"성적서 시험 {len(tests)}개 — 이 순서대로 구역 번호를 하나씩 적습니다 (넣지 않을 시험은 0):")
            for number, test in enumerate(tests, start=1):
                print(f"  {number}) {test['title']}")
        answer = input(f"구역 번호 ({'예: 2,3,0' if tests else '예: 2,3 또는 10-12'} · 그만두려면 q): ").strip()
        if answer.lower() == "q":
            return False
        numbers = parse_numbers(answer)
        if not numbers:
            print("  숫자, 쉼표(,), 범위(-)로 적어 주세요.")
            continue
        wrong = sorted({n for n in numbers if n and n not in {s["no"] for s in sections}})
        if wrong:
            print(f"  보고서에 없는 구역 번호: {wrong}")
            continue
        if tests and len(numbers) != len(tests):
            print(f"  성적서 시험이 {len(tests)}개라 번호도 {len(tests)}개가 필요합니다 (지금 {len(numbers)}개).")
            continue
        if argv_main(["map", "--job", str(job), "--sections", answer] + (["--use-gemini"] if use_gemini else [])):
            print("  대응을 다시 만들지 못했습니다. 위 메시지를 확인하세요.")


def closing_summary(job: Path, work: Path) -> None:
    manifest = read_json(job / "manifest.json")
    hwp = (manifest.get("inputs") or {}).get("hwp")
    ledger = load_ledger(ledger_path(work, Path(hwp["path"]))) if hwp else None
    if not ledger:
        return
    print(f"\n보고서 {ledger['report']}: {_ledger_line(ledger)}")
    partial = numbers_with_status(ledger, "partial")
    if partial:
        print(f"  일부만 반영된 구역: {compact_numbers(partial)} — 같은 성적서로 다시 실행해 나머지를 넣으세요.")
    pending = numbers_with_status(ledger, "pending")
    if pending:
        print(f"  아직 성적서가 없는 구역: {compact_numbers(pending)}")
        print("  다음 성적서가 오면 run.bat 을 다시 실행하고 '이전 결과에 이어서 넣을까요?' 에 Enter(Y) 를 누르세요.")
    else:
        print("  모든 구역이 채워졌습니다.")


def run(argv_main) -> int:
    """argv_main: the CLI ``main`` function, reused for every step."""
    root = project_root()
    work = root / "work"
    print("dongdongs 시작 — 질문에 답하면 나머지는 자동으로 진행합니다. 원본 파일은 바꾸지 않습니다.")
    print("성적서가 올 때마다 한 번씩 실행합니다. 같은 보고서는 이전 결과에 이어서 쌓입니다.")
    pdf = _ask_file("1) 시험성적서 PDF 파일", (".pdf",))
    hwp, parent = choose_report(work)
    if hwp is None:
        hwp = _ask_file("2) 보고서 HWP 파일 (처음 넣는 보고서는 원본)", (".hwp",), optional=True)
    default_id = f"{dt.datetime.now():%Y%m%d-%H%M}"
    job_id = _ask("3) 작업 이름", default_id)
    if (work / job_id).exists() and any((work / job_id).iterdir()):
        print(f"  work/{job_id} 가 이미 있습니다. 다른 이름을 쓰세요.")
        return 1

    args = ["init", "--pdf", str(pdf), "--work-dir", str(work), "--job-id", job_id]
    if hwp:
        args += ["--hwp", str(hwp)]
    if parent:
        args += ["--parent-job", parent]
    if argv_main(args):
        return 1
    job = str(work / job_id)
    hancom = (read_json(Path(job) / "environment.json").get("hancom") or {}) if (Path(job) / "environment.json").is_file() else {}
    ready = sys.platform == "win32" and bool(hancom.get("com_available"))
    if not ready and sys.platform == "win32":
        # found at init, not three hours later at the apply step
        print(f"\n{hancom.get('verdict') or '이 PC 에서는 한글 반영이 안 됩니다.'}")
        print("분석과 검수는 할 수 있지만, 한글 보고서에 넣는 단계는 이 PC 에서 되지 않습니다.")
        from .hancom import hwp_executable, probe, register

        exe = hwp_executable()
        if exe is not None and _yes("한글 자동화를 지금 등록할까요? (관리자 권한 창이 한 번 뜹니다)", default=True):
            if register(exe)["ok"] and probe()["com_available"]:
                print("등록했습니다. 반영까지 진행합니다.")
                ready = True
            else:
                print("등록하지 못했습니다. doctor.bat 을 실행해 나온 내용을 GitHub Issue 에 올려 주세요.")
        if not ready and not _yes("분석·검수까지만 진행할까요?", default=True):
            print("doctor.bat 을 실행해 나온 내용을 GitHub Issue 에 올려 주세요.")
            return 1
    use_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    print("\n분석을 시작합니다 (워터마크 삭제 → 검증 → 표·그래프 추출 → HWP 조사 → 후보). 몇 분 걸립니다.")
    analyze = ["analyze", "--job", job] + (["--use-gemini"] if use_gemini else [])
    if argv_main(analyze):
        print("분석이 중간에 멈췄습니다. 화면의 메시지를 보고 report.bat 으로 보고서를 만들어 주세요.")
        return 1
    if not hwp:
        print(f"\nHWP 를 지정하지 않아 여기서 끝냅니다. 추출 결과: {job}")
        return 0
    if not confirm_sections(Path(job), argv_main, use_gemini):
        print("구역을 정하지 않아 여기서 멈춥니다. 다시 실행하면 새 작업으로 시작합니다.")
        return 0
    print("\n검수 화면을 엽니다. 브라우저에서 승인·수정 후 [저장] 을 누르고, 이 창으로 돌아와 Enter 를 누르세요.")
    _serve_review(Path(job))
    approved = Path(job) / "approved_changes.json"
    if not approved.is_file():
        print("저장된 검수 결과가 없어 반영하지 않습니다. 다시 실행하면 같은 작업을 이어서 검수할 수 있습니다:")
        print(f"  uv run dongdongs review --job \"{job}\"")
        return 0
    if not ready:
        print("한글 반영은 하지 않았습니다. 검수 저장까지만 끝냈습니다." if sys.platform == "win32" else "HWP 반영은 Windows 에서만 됩니다. 이 PC 에서는 검수 저장까지만 진행했습니다.")
        return 0
    if not _yes("\n승인한 항목을 HWP 사본에 반영할까요? (한글 창이 열립니다)"):
        print("반영을 건너뛰었습니다. 나중에: uv run dongdongs apply --job", f'"{job}"')
        return 0
    print("한글 창은 띄우지 않고 진행합니다. 이 창을 최소화하고 다른 일을 하셔도 됩니다.")
    print("다만 반영이 끝날 때까지 한글로 다른 문서를 편집하지 마세요. (한글 창을 보려면 dongdongs.env 에 HWP_VISIBLE=1)")
    show_hancom = os.environ.get("HWP_VISIBLE", "").strip() in ("1", "true", "True")
    if argv_main(["apply", "--job", job, "--yes"] + (["--visible"] if show_hancom else [])):
        return 1
    if argv_main(["verify", "--job", job, "--stage", "hwp"]):
        print("\nHWP 검증을 통과하지 못했습니다. 이 결과 파일로 이어서 넣지 말고 report.bat 으로 보고서를 만들어 보내 주세요.")
        print(f"확인용 결과 폴더: {Path(job) / 'result'}")
        return 1
    print(f"\n결과 파일: {Path(job) / 'result'} 안의 *.processed.hwp (반영 전 사본은 *.before.hwp)")
    closing_summary(Path(job), work)
    return 0
