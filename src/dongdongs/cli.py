"""Command line interface.

    dongdongs init         --pdf P [--hwp H] [--work-dir work]
    dongdongs inspect-pdf  --job DIR
    dongdongs clean        --job DIR [--use-gemini] [--verify-dpi 150]
    dongdongs verify       --job DIR --stage clean|hwp [--dpi 300]
    dongdongs extract      --job DIR [--pages 3,5]
    dongdongs inspect-hwp  --job DIR
    dongdongs map          --job DIR [--use-gemini]
    dongdongs analyze      --job DIR            (clean + extract + inspect-hwp + map)
    dongdongs review       --job DIR [--port 8765]
    dongdongs apply        --job DIR [--yes]    (Windows + Hancom Office only)

``--job`` accepts the job directory or its manifest.json.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, gemini
from .config import detect_institution, institution, load_config
from .environment import collect
from .job import Job, create_job, open_job, read_json, write_json


def _pages(text: str | None) -> list[int] | None:
    if not text:
        return None
    pages: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        elif part:
            pages.append(int(part))
    return pages


def _job(args) -> Job:
    path = Path(args.job)
    return open_job(path.parent if path.name == "manifest.json" else path)


def _rules(job: Job, args) -> tuple[str, dict]:
    config = load_config(Path(args.config) if getattr(args, "config", None) else None)
    name = getattr(args, "institution", None) or job.manifest().get("institution") or detect_institution(job.pdf, config)
    if not name:
        raise SystemExit("기관을 판별하지 못했습니다. --institution 으로 지정하세요.")
    return name, institution(config, name)


def _rel(job: Job, path: Path) -> str:
    return path.resolve().relative_to(job.root).as_posix()


# ---------------------------------------------------------------- commands
def cmd_init(args) -> int:
    job = create_job(Path(args.work_dir), Path(args.pdf), Path(args.hwp) if args.hwp else None, args.job_id)
    config = load_config(Path(args.config) if args.config else None)
    name = args.institution or detect_institution(job.pdf, config)
    job.update(institution=name)
    env = collect(gemini.connectivity_test() if args.check_gemini else "not-run")
    write_json(job.path("environment.json"), env)
    job.record_step("init", institution=name)
    print(f"작업 폴더: {job.root}")
    print(f"기관: {name or '미확인'}")
    print(f"한컴 COM: {'사용 가능' if env['hancom']['com_available'] else '없음'} ({env['os']['name']})")
    print(f"Gemini 키: {'있음' if env['gemini']['api_key_present'] else '없음'}")
    return 0


def cmd_inspect_pdf(args) -> int:
    from .pdf.inspector import inspect_pdf

    job = _job(args)
    result = inspect_pdf(job.pdf)
    write_json(job.path("pdf_inspection.json"), result)
    job.record_step("inspect-pdf")
    print(f"{result['page_count']}쪽 · 텍스트 레이어 {result['text_layer_pages']}쪽")
    print(f"선택적 콘텐츠(OCG): {result['optional_content_groups']} · 사용 폼 수 {result['forms_per_optional_content']}")
    for image in result["repeated_images"]:
        print(f"반복 이미지 xref {image['xref']} {image['width']}x{image['height']} · 그려진 쪽 {image['drawn_page_count']} · sha256 {str(image['sha256'])[:16]}…")
    return 0


def cmd_clean(args) -> int:
    from .pdf.watermark import clean_pdf
    from .verify import compare_clean

    job = _job(args)
    name, rules = _rules(job, args)
    candidates = job.path("images", "watermark_candidates")
    report = clean_pdf(job.pdf, job.cleaned_pdf, rules, candidates)
    report["institution"] = name
    if args.use_gemini:
        expected = {r["id"]: r.get("expected_text") for r in rules.get("watermarks", [])}
        reads = {}
        for png in sorted(candidates.glob("*.png")):
            try:
                reads[png.name] = gemini.read_watermark_text(png.read_bytes())
            except gemini.GeminiUnavailable as exc:
                reads = {"error": str(exc)}
                break
        report["gemini_read"] = reads
        report["expected_text"] = expected
    write_json(job.path("watermark_report.json"), report)
    job.record_step("clean", overall=report["overall"], counts=report["counts"])
    print(f"워터마크: {report['overall']} {report['counts']} · 편집 스트림 {report['streams_edited']} · 제거 참조 {report['resource_entries_removed']}")
    if report["counts"].get("review_required"):
        print("확인 필요 — 워터마크 수동 처리 페이지:", [p["page"] for p in report["pages"] if p["status"] == "review_required"])
    if args.skip_verify:
        return 0
    result = compare_clean(job.pdf, job.cleaned_pdf, report, rules, dpi=args.verify_dpi, pages=_pages(args.pages))
    write_json(job.path("verification_clean.json"), {k: v for k, v in result.items()})
    job.record_step("verify-clean", passed=result["passed"], dpi=args.verify_dpi)
    _print_clean(result)
    return 0 if result["passed"] else 2


def _print_clean(result: dict) -> None:
    print(
        f"무변형 검증 {'통과' if result['passed'] else '실패'} · {result['pages_checked']}쪽 @{result['dpi']}dpi · "
        f"영역 밖 차이 {result['pixel_diff_outside_wm']}px · 영역 안 어두워짐 {result['pages_darker_inside_wm']} · "
        f"푸터 {'유지' if result['footer_present'] else '손상'} · 보호 객체 {'유지' if result['protected_objects_kept'] else '누락'}"
    )


def cmd_verify(args) -> int:
    job = _job(args)
    if args.stage == "clean":
        from .verify import compare_clean

        _, rules = _rules(job, args)
        report = read_json(job.path("watermark_report.json"))
        result = compare_clean(job.pdf, job.cleaned_pdf, report, rules, dpi=args.dpi, pages=_pages(args.pages))
        write_json(job.path("verification_clean.json"), result)
        job.record_step("verify-clean", passed=result["passed"], dpi=args.dpi)
        _print_clean(result)
        return 0 if result["passed"] else 2

    from .hwp.inspector import build_inventory, export_xml
    from .verify import compare_hwp

    log = read_json(job.path("apply_log.json"))
    before = Path(args.before or log["before_hwp"])
    after = Path(args.after or log["processed_hwp"])
    inv_before = build_inventory(export_xml(before, job.path("logs", "before.xml")), before.name)
    inv_after = build_inventory(export_xml(after, job.path("logs", "processed.xml")), after.name)
    result = compare_hwp(inv_before, inv_after, log["changes"])
    write_json(job.path("verification_hwp.json"), result)
    job.record_step("verify-hwp", passed=result["passed"])
    print(
        f"HWP 검증 {'통과' if result['passed'] else '실패'} · 구조 문제 {len(result['structure_problems'])} · 셀 크기 변화 {len(result['cell_size_changes'])} · "
        f"예상 밖 텍스트 변화 {len(result['unexpected_text_changes'])} · 반영값 불일치 {len(result['applied_values_not_found'])}"
    )
    return 0 if result["passed"] else 2


def cmd_extract(args) -> int:
    from .pdf.regions import find_document_regions
    from .pdf.render import render_region
    from .pdf.tables import extract_document

    job = _job(args)
    _, rules = _rules(job, args)
    verification = job.path("verification_clean.json")
    verified = job.cleaned_pdf.is_file() and verification.is_file() and read_json(verification)["passed"]
    if not verified and not args.allow_unverified:
        raise SystemExit("clean 단계와 무변형 검증이 먼저 통과해야 합니다 (--allow-unverified 로 우회 가능).")
    pdf = job.cleaned_pdf if job.cleaned_pdf.is_file() else job.pdf
    pages = _pages(args.pages)
    extracted = extract_document(pdf, rules["tables"]["known_sections"], pages)
    extracted["pdf"] = job.pdf.name
    extracted["extracted_from"] = pdf.name
    for table in extracted["tables"]:
        table["source"]["pdf"] = job.pdf.name
    write_json(job.path("extracted_values.json"), extracted)

    report_path = job.path("watermark_report.json")
    status = {p["page"]: p["status"] for p in read_json(report_path)["pages"]} if report_path.is_file() else {}
    regions = find_document_regions(pdf, rules["regions"], pages)
    rendered = 0
    for region in regions:
        region["watermark_status"] = status.get(region["page"], "unknown")
        if region["watermark_status"] == "review_required":
            region["flags"] = ["watermark_manual_required"]
        if region["export"] and not args.no_png:
            out = job.path("images", f"p{region['page']:03d}-{region['index']}-{region['kind']}.png")
            region["render"] = render_region(pdf, region["page"], region["bbox"], out, dpi=rules["regions"].get("dpi", 300))
            region["png"] = _rel(job, out)
            rendered += 1
    write_json(job.path("regions.json"), regions)
    job.record_step("extract", tables=len(extracted["tables"]), regions=len(regions), png=rendered, source=pdf.name)
    print(f"표 {len(extracted['tables'])}개 ({extracted['pages_scanned']}쪽) · 영역 {len(regions)}개 · PNG {rendered}장 · 원본 {pdf.name}")
    return 0


def cmd_inspect_hwp(args) -> int:
    from .hwp.inspector import build_inventory, export_xml, tables_with_cell

    job = _job(args)
    if job.hwp is None:
        raise SystemExit("이 작업에는 HWP가 지정되지 않았습니다 (init --hwp).")
    _, rules = _rules(job, args)
    inventory = build_inventory(export_xml(job.hwp, job.path("logs", "hwp_structure.xml")), job.hwp.name)
    write_json(job.path("hwp_inventory.json"), inventory)
    job.record_step("inspect-hwp", tables=inventory["table_count"], pictures=inventory["picture_count"])
    print(f"HWP 표 {inventory['table_count']} · 그림 {inventory['picture_count']} · 셀 {inventory['cell_count']}")
    for section in rules["tables"]["known_sections"]:
        print(f"  '{section}' 머리 셀이 있는 표: {[t['index'] for t in tables_with_cell(inventory, section)]}")
    return 0


def cmd_map(args) -> int:
    from .environment import now_kst
    from .hwp.mapping import build_candidates
    from .pdf.render import render_crop

    job = _job(args)
    name, rules = _rules(job, args)
    extracted = read_json(job.path("extracted_values.json"))
    regions = read_json(job.path("regions.json"))
    inventory = read_json(job.path("hwp_inventory.json"))
    report_path = job.path("watermark_report.json")
    status = {p["page"]: p["status"] for p in read_json(report_path)["pages"]} if report_path.is_file() else {}
    candidates = build_candidates(extracted, regions, inventory, rules["tables"]["known_sections"], status)
    pdf = job.cleaned_pdf if job.cleaned_pdf.is_file() else job.pdf
    for change in candidates["changes"]:
        source = change["source"]
        if change["kind"] == "set_cell_text" and source.get("row_bbox"):
            key = change["id"].rsplit("-", 1)[0]
            out = job.path("previews", f"{key}.png")
            if not out.is_file():
                render_crop(pdf, source["pdf_page"], source["row_bbox"], out)
            change["preview"] = _rel(job, out)
            if args.use_gemini and change["field"] == "label" and "label_has_sub_or_superscript" in change["flags"]:
                cell = job.path("previews", f"{change['id']}-cell.png")
                render_crop(pdf, source["pdf_page"], source["cell_bbox"], cell, dpi=300)
                try:
                    change["gemini_read"] = gemini.read_label(cell.read_bytes())
                except gemini.GeminiUnavailable as exc:
                    change["gemini_read"] = {"error": str(exc)}
    candidates.update(job_id=job.manifest()["job_id"], created_at=now_kst(), institution=name, pdf=job.pdf.name, hwp=job.hwp.name if job.hwp else None)
    write_json(job.path("mapping_candidates.json"), candidates)
    changed = sum(1 for c in candidates["changes"] if not c.get("no_op"))
    job.record_step("map", changes=len(candidates["changes"]), effective=changed, warnings=len(candidates["warnings"]))
    print(f"후보 {len(candidates['changes'])}건 (실제 변경 {changed}) · 경고 {len(candidates['warnings'])} · 미대응 그래프 {len(candidates['unmapped_regions'])}")
    for warning in candidates["warnings"]:
        print("  경고:", warning)
    return 0


def cmd_analyze(args) -> int:
    code = cmd_clean(args)
    if code:
        return code
    args.allow_unverified = False
    args.no_png = False
    cmd_extract(args)
    if _job(args).hwp is not None:
        cmd_inspect_hwp(args)
        cmd_map(args)
    return 0


def cmd_review(args) -> int:
    from .review.server import serve

    job = _job(args)
    if not job.path("mapping_candidates.json").is_file():
        raise SystemExit("mapping_candidates.json 이 없습니다. map 또는 analyze 를 먼저 실행하세요.")
    serve(job, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_apply(args) -> int:
    from .hwp.editor import apply_changes

    job = _job(args)
    if job.hwp is None:
        raise SystemExit("이 작업에는 HWP가 지정되지 않았습니다.")
    approved_path = job.path("approved_changes.json")
    if not approved_path.is_file():
        raise SystemExit("approved_changes.json 이 없습니다. review 에서 승인 후 저장하세요.")
    approved = read_json(approved_path)["changes"]
    chosen = [c for c in approved if c.get("decision") == "approve" and c.get("status") != "blocked"]
    effective = [c for c in chosen if not c.get("no_op")]
    print(f"승인 {len(chosen)}건 · 실제 변경 {len(effective)}건 · 대상 {job.hwp.name}")
    print("원본 HWP는 열지 않고 result/ 에 before·processed 사본을 만든 뒤 processed 사본에만 반영합니다.")
    if not args.yes and input("계속하시겠습니까? [y/N] ").strip().lower() != "y":
        print("취소했습니다.")
        return 1
    result = apply_changes(job.hwp, job.path("result"), chosen, visible=args.visible)
    write_json(job.path("apply_log.json"), result)
    counts: dict[str, int] = {}
    for change in result["changes"]:
        counts[change["apply_status"]] = counts.get(change["apply_status"], 0) + 1
    job.record_step("apply", counts=counts)
    print("반영 결과:", counts)
    print("다음: dongdongs verify --stage hwp --job", job.root)
    return 0


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dongdongs", description="시험성적서 PDF → 기존 HWP 보고서 반자동화")
    parser.add_argument("--version", action="version", version=f"dongdongs {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def job_parser(name: str, func, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--job", required=True, help="작업 폴더 또는 manifest.json")
        p.add_argument("--institution", help="기관 규칙 이름 (기본: manifest 또는 자동 판별)")
        p.add_argument("--config", help="institutions.yaml 경로 (기본: 내장 규칙)")
        p.set_defaults(func=func)
        return p

    p = sub.add_parser("init", help="작업 폴더 생성 · environment.json 기록")
    p.add_argument("--pdf", required=True)
    p.add_argument("--hwp", "--report", dest="hwp")
    p.add_argument("--work-dir", default="work")
    p.add_argument("--job-id")
    p.add_argument("--institution")
    p.add_argument("--config")
    p.add_argument("--check-gemini", action="store_true", help="Gemini 연결 확인 (키 값은 기록하지 않음)")
    p.set_defaults(func=cmd_init)

    job_parser("inspect-pdf", cmd_inspect_pdf, "PDF 객체 구조 조사")

    for name, func, text in (("clean", cmd_clean, "워터마크 객체 삭제 + 무변형 검증"), ("analyze", cmd_analyze, "clean → extract → inspect-hwp → map")):
        p = job_parser(name, func, text)
        p.add_argument("--use-gemini", action="store_true")
        p.add_argument("--verify-dpi", type=int, default=150)
        p.add_argument("--pages", help="검증·추출 페이지 (예: 3,5,8-10)")
        p.add_argument("--skip-verify", action="store_true")

    p = job_parser("verify", cmd_verify, "검증 (clean: PDF 무변형 / hwp: 반영 결과)")
    p.add_argument("--stage", choices=("clean", "hwp"), required=True)
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--pages")
    p.add_argument("--before")
    p.add_argument("--after")

    p = job_parser("extract", cmd_extract, "표 값 추출 + 그래프·회로도 PNG")
    p.add_argument("--pages")
    p.add_argument("--no-png", action="store_true")
    p.add_argument("--allow-unverified", action="store_true")

    job_parser("inspect-hwp", cmd_inspect_hwp, "HWP 구조 인벤토리 (읽기 전용)")

    p = job_parser("map", cmd_map, "HWP 셀·그림 대응 후보 생성")
    p.add_argument("--use-gemini", action="store_true")

    p = job_parser("review", cmd_review, "127.0.0.1 검수 화면")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")

    p = job_parser("apply", cmd_apply, "승인된 변경을 HWP 사본에 반영 (Windows 전용)")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--visible", action="store_true", help="한글 창을 보이게 실행")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except (FileNotFoundError, FileExistsError, KeyError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
