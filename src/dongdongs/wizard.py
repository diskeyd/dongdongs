"""``dongdongs start``: the question-and-answer flow behind run.bat.

Asks for the PDF, the HWP and a job name, then runs the same commands a
developer would type: init → analyze → review → apply → verify. Nothing is
written to the original files.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

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


def _yes(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def run(argv_main) -> int:
    """argv_main: the CLI ``main`` function, reused for every step."""
    root = project_root()
    print("dongdongs 시작 — 질문에 답하면 나머지는 자동으로 진행합니다. 원본 파일은 바꾸지 않습니다.")
    pdf = _ask_file("1) 시험성적서 PDF 파일", (".pdf",))
    hwp = _ask_file("2) 보고서 HWP 파일", (".hwp",), optional=True)
    default_id = f"{dt.datetime.now():%Y%m%d}-{pdf.stem[:20]}"
    job_id = _ask("3) 작업 이름", default_id)
    work = root / "work"
    if (work / job_id).exists() and any((work / job_id).iterdir()):
        print(f"  work/{job_id} 가 이미 있습니다. 다른 이름을 쓰세요.")
        return 1

    args = ["init", "--pdf", str(pdf), "--work-dir", str(work), "--job-id", job_id]
    if hwp:
        args += ["--hwp", str(hwp)]
    if argv_main(args):
        return 1
    job = str(work / job_id)
    print("\n분석을 시작합니다 (워터마크 삭제 → 검증 → 표·그래프 추출 → HWP 조사 → 후보). 몇 분 걸립니다.")
    analyze = ["analyze", "--job", job]
    if os.environ.get("GEMINI_API_KEY"):
        analyze.append("--use-gemini")
    if argv_main(analyze):
        print("분석이 중간에 멈췄습니다. 화면의 메시지를 보고 report.bat 으로 보고서를 만들어 주세요.")
        return 1
    if not hwp:
        print(f"\nHWP 를 지정하지 않아 여기서 끝냅니다. 추출 결과: {job}")
        return 0
    print("\n검수 화면을 엽니다. 브라우저에서 승인·수정 후 [저장] 을 누르고, 이 창으로 돌아와 Ctrl+C 를 누르세요.")
    argv_main(["review", "--job", job])
    approved = Path(job) / "approved_changes.json"
    if not approved.is_file():
        print("저장된 검수 결과가 없어 반영하지 않습니다. 다시 실행하면 같은 작업을 이어서 검수할 수 있습니다:")
        print(f"  uv run dongdongs review --job \"{job}\"")
        return 0
    if sys.platform != "win32":
        print("HWP 반영은 Windows 에서만 됩니다. 이 PC 에서는 검수 저장까지만 진행했습니다.")
        return 0
    if not _yes("\n승인한 항목을 HWP 사본에 반영할까요? (한글 창이 열립니다)"):
        print("반영을 건너뛰었습니다. 나중에: uv run dongdongs apply --job", f'"{job}"')
        return 0
    if argv_main(["apply", "--job", job, "--yes", "--visible"]):
        return 1
    argv_main(["verify", "--job", job, "--stage", "hwp"])
    print(f"\n결과 파일: {Path(job) / 'result'} 안의 *.processed.hwp (원본 사본은 *.before.hwp)")
    return 0
