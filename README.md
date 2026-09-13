# dongdongs

시험기관이 발행한 시험성적서 PDF 한 건을 분석해, 이미 있는 HWP 보고서 사본의 시험결과 값과 그림을 성적서에 맞게 바꾸는 반자동 도구다. 새 보고서를 만들지 않고 기존 HWP를 고친다.

그래프와 회로도는 다시 그리거나 보정하지 않는다. PDF 안의 독립 워터마크 객체만 지운 뒤, 사각 테두리 영역을 원본 그대로 PNG로 렌더링한다. 모든 변경은 사람이 검수 화면에서 승인해야 HWP에 들어간다.

## 현재 상태

| 단계 | 명령 | 상태 |
|---|---|---|
| 환경 기록 | `init` | 동작 확인 (macOS) |
| PDF 객체 조사 | `inspect-pdf` | 동작 확인 |
| 워터마크 객체 삭제 + 무변형 검증 | `clean`, `verify --stage clean` | 실제 성적서 전 쪽 통과 (150·300 DPI, 테두리 밖 픽셀 차이 0) |
| 표 값 추출 | `extract` | 동작 확인 |
| 그래프·회로도 PNG | `extract` | 동작 확인 (300 DPI) |
| HWP 구조 조사 | `inspect-hwp` | 동작 확인 (읽기 전용, OS 무관) |
| 대응 후보 생성 | `map` | 표 값과 회로도 그림 후보 생성. 오실로그램은 자동 대응 안 함 |
| 검수 화면 | `review` | 127.0.0.1 로컬 서버 |
| HWP 반영 | `apply` | **코드만 작성. Windows에서 아직 실행하지 않음** |
| HWP 결과 검증 | `verify --stage hwp` | 비교 로직 테스트 완료. 실제 반영본으로는 미실행 |
| Gemini 읽기 보조 | `--use-gemini` | 코드만 작성. 실제 호출 미실행 |

## 설치

[uv](https://docs.astral.sh/uv/)가 필요하다. Python 3.12를 쓴다.

```bash
uv sync
```

Windows에서는 같은 명령이 `pywin32`까지 설치한다. `apply`에는 한컴오피스(한글)가 설치돼 있어야 한다.

## 사용 순서

```powershell
# 1. 작업 폴더 만들기 (environment.json 기록, 기관 자동 판별)
uv run dongdongs init --pdf ".\input\성적서.pdf" --hwp ".\report\작업용보고서.hwp" --work-dir .\work --job-id keri-001

# 2. 워터마크 삭제 → 무변형 검증 → 표·그래프 추출 → HWP 조사 → 대응 후보
uv run dongdongs analyze --job .\work\keri-001

# (선택) 300 DPI 전체 무변형 재검증
uv run dongdongs verify --job .\work\keri-001 --stage clean --dpi 300

# 3. 검수 (브라우저가 열린다. 승인·수정 후 저장)
uv run dongdongs review --job .\work\keri-001

# 4. 반영 (Windows) — 원본은 열지 않고 result\ 사본에만 쓴다
uv run dongdongs apply --job .\work\keri-001

# 5. 반영 결과 검증
uv run dongdongs verify --job .\work\keri-001 --stage hwp
```

단계별로 따로 실행할 수도 있다: `inspect-pdf`, `clean`, `extract`, `inspect-hwp`, `map`. `--job`에는 작업 폴더나 그 안의 `manifest.json`을 준다.

## 작업 폴더

```text
work/<job-id>/
├─ manifest.json            입력 파일 경로·해시, 기관, 실행 단계 기록
├─ environment.json         OS·Python·의존성·한컴 COM·Gemini 키 유무 (키 값은 저장 안 함)
├─ pdf_inspection.json      쪽별 콘텐츠 스트림·이미지·폼·OCG
├─ watermark_report.json    쪽별 판정(delete / reference_only / review_required)과 근거
├─ verification_clean.json  무변형 검증 결과
├─ extracted_values.json    표 값 (원문 그대로 + 셀 좌표 근거)
├─ regions.json             그래프·회로도 영역, 제목, PNG 경로
├─ hwp_inventory.json       HWP 표·셀·그림 인벤토리
├─ mapping_candidates.json  HWP 셀·그림 변경 후보 (전부 review_required)
├─ approved_changes.json    검수 결과 (승인·거절·보류, 수정값)
├─ apply_log.json           반영 결과 (Windows)
├─ verification_hwp.json    반영 전후 구조·값 비교
├─ cleaned_pdf/  images/  previews/  logs/
└─ result/<원본명>.before.hwp · <원본명>.processed.hwp
```

## 코드가 강제하는 안전 규칙

- 워터마크는 규칙의 모든 조건(이미지 크기·해시, 그리는 위치, 반투명 합성, 쪽 비율)이 맞을 때만 **객체 단위로** 지운다. 하나라도 어긋나면 그 쪽은 건드리지 않고 `확인 필요 — 워터마크 수동 처리`로 표시한다. 픽셀은 수정하지 않는다.
- 무변형 검증은 원본과 정리본을 렌더링해 비교한다. 워터마크 사각형 밖은 픽셀이 완전히 같아야 하고, 안쪽은 밝아지기만 해야 한다(곱하기 합성 레이어를 빼면 어두워질 수 없다). 푸터와 보호 레이어 객체도 확인한다.
- `extract`는 무변형 검증을 통과한 정리본에서만 실행된다.
- 그래프 PNG는 테두리 전체를 포함하고 제목은 뺀다. 테두리 안쪽은 자르지 않는다.
- 표 값은 숫자로 바꾸지 않는다(`4.84`, `< 0.1`, `1 872`, `isolated` 그대로).
- 모든 후보는 `review_required`로 시작한다. 워터마크 수동 처리 쪽의 그림은 `blocked`라 승인할 수 없다.
- `apply`는 `approved_changes.json`에서 승인된 항목만 반영한다. 원본 HWP를 `before`·`processed` 두 사본으로 복사하고 해시를 확인한 뒤 `processed`만 연다. 결과 사본이 이미 있으면 덮어쓰지 않는다.
- 셀마다 기준 머리 셀 텍스트와 대상 셀의 현재값이 검수 때 본 값과 같은지 먼저 읽어 확인한다. 다르면 쓰지 않고 건너뛴다. 쓴 뒤 다시 읽어 확인한다.
- 검수 서버는 127.0.0.1에만 바인딩하고 `previews/`, `images/` 밖의 파일은 내주지 않는다.

## 기관 규칙

`src/dongdongs/config/institutions.yaml`에 기관별 판별 문자열, 워터마크 규칙, 보호 레이어, 표 구역 이름, 그래프 영역 규칙을 둔다. 다른 파일을 쓰려면 `--config`로 지정한다. 새 기관은 `inspect-pdf` 결과(반복 이미지, OCG 사용처)를 보고 규칙을 추가한다. 이름에 "Watermark"가 들어간 레이어라도 푸터 같은 본문 요소를 담고 있을 수 있으니, 사용처를 확인한 뒤 보호 목록에 넣는다.

HWP 표는 구역마다 칸 구성이 다를 수 있다. 항목명·단위·값이 세 칸인 표, 항목명과 단위가 한 칸에 공백으로 떨어져 있는 표, 구역 경계를 넘어 합쳐진 칸이 있는 표를 모두 셀 단위로 인식한다. PDF와 HWP의 Ω·μ 문자 코드가 달라 눈으로만 같은 경우에는 후보에 `unicode_lookalike_only` 표시를 붙인다.

## Gemini

`--use-gemini`를 붙였을 때만 호출한다. 보내는 것은 잘라낸 PNG와 짧은 지시문뿐이고 전체 쪽은 보내지 않는다. 결과는 후보로만 기록한다.

- `clean`: 워터마크 이미지에 적힌 문자 판독
- `map`: 아래첨자가 있는 항목명 판독

```powershell
setx GEMINI_API_KEY "발급받은 키"
setx DONGDONGS_GEMINI_MODEL "사용할 모델 ID"   # 선택. 기본값은 gemini.py 참고
```

키는 환경변수로만 읽고 파일·로그에 남기지 않는다.

## 테스트

```bash
export DONGDONGS_FIXTURE_PDF="/path/to/성적서.pdf"
export DONGDONGS_FIXTURE_HWP="/path/to/보고서.hwp"
export DONGDONGS_FIXTURE_EXPECT="/path/to/expected.json"   # 선택. 기본값 tests/local/expected.json
uv run pytest
```

단위 테스트는 만든 값으로 돌아서 파일 없이 실행된다. 실제 파일로 도는 테스트는 필요한 PDF 또는 HWP와 기대값 파일이 함께 있을 때만 실행되고, 없으면 건너뛴다. `expected.json`에는 그 성적서에서 기대하는 쪽 번호·표 값·영역 좌표·HWP 표 번호를 적는다. 형식은 `tests/test_tables.py` 등에서 읽는 키를 따른다.

성적서 PDF, HWP, 추출한 PNG, 기대값 파일, 요구사항 원문은 모두 로컬에만 둔다(`.gitignore`의 `local/`, `tests/local/`, `work/`).

## 아직 안 된 것

- **Windows 실측**: `apply`의 COM 호출(`Open`, `RepeatFind`, `KeyIndicator`, 셀 이동, `InsertText`, `SaveAs`)은 한 번도 실행하지 않았다. 첫 실행은 반드시 `--visible`로 한 셀만 승인해서 확인한다.
- **그림 교체**: 회로도 교체 후보는 만들지만 COM으로 그림을 바꾸는 코드는 없다(`skipped_not_implemented`로 기록).
- **오실로그램 대응**: HWP 그림과 자동으로 짝짓지 않는다. 검수 화면에 PNG 목록만 보인다.
- **한 쪽 두 그래프 배치 규칙**: 완성 예시를 받은 뒤 정한다.
- **문서 코드 판독**: 푸터가 벡터라 자동 추출하지 않는다.
- **Circuit components 목록 문장** 교체 후보.
- **HWP 검증 범위**: 표 구조·셀 크기·셀 텍스트·그림 수만 비교한다. 글꼴·문단 모양·쪽 수 비교는 아직 없다.
- **행 추가**: PDF에 있는데 HWP 표에 빈 행이 없는 항목은 경고만 남긴다. 표 구조를 바꾸지 않기 위해 행을 늘리지 않으므로 사람이 직접 넣는다.
- **아래·위첨자 서식**: 항목명은 글자로만 쓴다. HWP에서 u<sub>c</sub>의 c를 아래첨자로 만드는 서식 적용은 없다.
