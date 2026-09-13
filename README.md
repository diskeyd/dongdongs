# dongdongs — 시험성적서 PDF를 한글 보고서에 옮겨 주는 프로그램

시험기관이 보낸 성적서 PDF 한 개를 읽어서,

1. PDF에 찍힌 **DRAFT 도장을 지우고** (쪽 번호·문서 코드는 그대로 둡니다),
2. 표의 값과 그래프·회로도 그림을 **꺼낸 다음**,
3. 브라우저 검수 화면에서 **사람이 승인한 것만** 기존 한글 보고서의 **사본**에 넣습니다.

원본 PDF와 원본 HWP는 절대 바뀌지 않습니다. 결과는 항상 새 파일로 나옵니다.

> 코드를 고치는 사람은 [`docs/개발.md`](docs/개발.md)를 보세요. 이 문서는 프로그램을 **쓰는** 사람을 위한 안내입니다.

---

## 준비물

| 필요한 것 | 비고 |
|---|---|
| Windows 10 또는 11 PC | 개인 PC면 됩니다 |
| 한글(한컴오피스) 설치 | 마지막 "반영" 단계에서 한글 창이 열립니다 |
| 인터넷 | 설치할 때만 필요합니다 |
| 시험성적서 PDF, 보고서 HWP | 작업할 파일 |
| (선택) Gemini API 키 | 없어도 됩니다. 있으면 아래첨자 항목명 판독을 도와줍니다 |

설치는 한 번만 하면 됩니다. 아래 1단계부터 4단계까지 순서대로 따라 하세요. 30분쯤 걸립니다.

---

## 1단계. 파이썬 설치

이 프로그램은 파이썬 3.12로 만들었습니다.

1. 이 파일을 내려받아 실행합니다: **[python-3.12.10-amd64.exe](https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe)**
   (파이썬 공식 사이트의 다운로드 버튼은 더 새 버전을 주므로 위 링크를 쓰세요.)
2. 설치 첫 화면 **맨 아래의 "Add python.exe to PATH" 체크박스를 반드시 켜고** `Install Now`를 누릅니다.
3. 설치가 끝나면 확인: 키보드에서 `Windows 키 + R` → `cmd` 입력 → Enter → 검은 창에 아래를 입력하고 Enter.

```
python --version
```

`Python 3.12.10` 처럼 나오면 됩니다.

📺 따라 하기 영상
- [파이썬 설치 가이드 (2024년 기준, 맥북 및 윈도우)](https://www.youtube.com/watch?v=Cq8jVZORHZI) — 다비드스튜디오
- [혼자 공부하는 파이썬 개정판 71강 윈도우 환경설정(1) - 파이썬 설치하기](https://www.youtube.com/watch?v=ca1B094SBG0) — 윤인성

> 체크박스를 깜빡했더라도 괜찮습니다. 3단계의 `install.bat`이 필요한 파이썬을 스스로 내려받습니다.

---

## 2단계. 프로그램 내려받기

1. 이 저장소 페이지에서 초록색 **`<> Code`** 버튼 → **`Download ZIP`**.
2. 내려받은 zip을 **`C:\dongdongs`** 처럼 짧은 경로에 풀어 놓습니다. 풀고 나면 그 폴더 안에 `install.bat`, `run.bat`, `report.bat` 세 파일이 보여야 합니다.

📺 GitHub가 처음이라면: [깃허브 모르면 바이브코딩 못합니다 | 비개발자를 위한 깃허브 설명](https://www.youtube.com/watch?v=-vBtNVK49ls) — 비캠프
📄 글로 보기: [GitHub 문서 – 소스 코드 아카이브 다운로드](https://docs.github.com/ko/repositories/working-with-files/using-files/downloading-source-code-archives)

---

## 3단계. 설치

폴더 안의 **`install.bat`을 더블클릭**합니다. 검은 창이 열리고 필요한 것을 알아서 내려받습니다(처음 한 번 몇 분).

"설치가 끝났습니다"가 나오면 완료입니다. 창에 오류가 보이면 그 창을 닫지 말고 [문제가 생겼을 때](#문제가-생겼을-때)로 가세요.

폴더 안에 이런 것이 생깁니다.

| 폴더/파일 | 용도 |
|---|---|
| `input\` | 성적서 PDF를 여기에 두면 찾기 편합니다 (다른 곳에 있어도 됩니다) |
| `report\` | 보고서 HWP를 두는 곳 |
| `work\` | 작업 결과가 작업 이름별로 쌓이는 곳 |
| `reports\` | 오류 보고 zip이 생기는 곳 |
| `dongdongs.env` | 설정 파일 (Gemini 키를 여기에 넣습니다) |

> 참고: `install.bat`은 [uv](https://docs.astral.sh/uv/getting-started/installation/)라는 실행 도구를 씁니다. 몰라도 됩니다. 궁금하면 📺 [Python: EP122 - 미친듯이 빠른 uv에 대해 알아보자](https://www.youtube.com/watch?v=M_YER9jM9lY) — 미쿡엔지니어.

---

## 4단계. (선택) Gemini 키 넣기

Gemini 키가 있으면 표에서 아래첨자가 들어간 항목명(u<sub>c</sub>, t<sub>3</sub> 같은 것)을 한 번 더 읽어서 검수 화면에 참고로 보여 줍니다. 없어도 모든 기능이 됩니다.

1. [Google AI Studio – API 키](https://aistudio.google.com/apikey)에서 키를 만듭니다 (구글 계정 필요, 무료).
2. 폴더 안의 `dongdongs.env` 파일을 **메모장**으로 열어 `GEMINI_API_KEY=` 뒤에 키를 붙여 넣고 저장합니다.

```
GEMINI_API_KEY=여기에_키_붙여넣기
```

📺 따라 하기 영상
- [100% 무료! Gemini API 키 발급 (Google AI Studio에서 1분 만에 생성하는 방법)](https://www.youtube.com/watch?v=gCFqpFXY578) — AI 연구노트
- [100% 무료 구글 AI 스튜디오 & 제미나이 API 키 발급 가이드 (초보자 필독)](https://www.youtube.com/watch?v=hyD7YdTqhM8) — 스탠리탬의AI워크랩

키는 이 파일에만 있고 다른 곳에 저장되거나 전송되지 않습니다. 키를 남에게 보여 주지 마세요.

> 시스템 환경 변수로 넣어도 됩니다(고급). 방법: 📺 [윈도우 환경 변수 설정](https://www.youtube.com/watch?v=jbRneBEdfu8) — 한빛미디어 (자바 강의지만 같은 창입니다. 변수 이름만 `GEMINI_API_KEY`로).

---

## 5단계. 실행하기

1. **`run.bat`을 더블클릭**합니다.
2. 검은 창이 묻는 대로 답합니다.
   - `1) 시험성적서 PDF 파일` → 탐색기에서 PDF 파일을 **검은 창 안으로 끌어다 놓고** Enter.
   - `2) 보고서 HWP 파일` → HWP 파일을 끌어다 놓고 Enter.
   - `3) 작업 이름` → 그냥 Enter (오늘 날짜로 정해집니다).
3. 분석이 자동으로 돌아갑니다. 몇 분 걸립니다. (DRAFT 삭제 → 삭제 검증 → 표·그래프 추출 → HWP 조사 → 후보 만들기)
4. 브라우저에 **검수 화면**이 열립니다. 아래 "검수 화면 보는 법"대로 승인하고 **[저장]**을 누릅니다.
5. 검은 창으로 돌아와 `Ctrl + C`를 누르면 "반영할까요?"라고 묻습니다. `y` → Enter.
6. **한글 창이 저절로 열리고** 승인한 값과 그림이 들어갑니다. 한글 창을 건드리지 말고 기다리세요.
7. 끝나면 결과 파일 위치가 나옵니다.

📺 검은 창(명령 프롬프트)이 낯설다면: [cmd(명령 프롬프트) 해당 폴더에서 바로 여는 법](https://www.youtube.com/watch?v=kmRQhUIOsjA) — YYR

### 검수 화면 보는 법

표 한 줄이 "바꿀 것 하나"입니다.

| 열 | 뜻 |
|---|---|
| 근거 | 성적서 PDF에서 잘라낸 원본 조각. 이걸 보고 판단합니다 |
| HWP 위치 | 한글 보고서의 몇 번 표, 어느 칸(또는 몇 쪽)인지 |
| HWP 현재값 | 지금 한글에 적혀 있는 값 |
| 추출값 | PDF에서 읽은 값 |
| 반영값 | 한글에 실제로 들어갈 값. **직접 고칠 수 있습니다** |
| 표시 | 주의할 점. 노란색이면 한 번 더 보세요 |
| 결정 | 승인 / 거절 / 보류 |

- 값이 같은 줄(회색)은 **[변경 없음 항목 모두 승인]** 버튼으로 한 번에 승인하면 됩니다.
- **그래프 쪽** 줄에는 그래프 미리보기와 "세로 85%" 같은 배율이 보입니다. 가로는 한글 칸 폭에 맞추고 세로만 줄여서 한 쪽에 넣는다는 뜻입니다.
- 한글에 그래프 쪽이 모자라면 "(추가)"라고 표시됩니다. 마지막 그래프 쪽을 복사해서 새 쪽을 만듭니다.
- 빨간 `blocked` 표시가 있는 줄은 승인할 수 없습니다. 그 쪽의 DRAFT를 자동으로 지우지 못했다는 뜻이니 개발자에게 알려 주세요.
- 저장은 여러 번 해도 됩니다. 나중에 다시 열면 이어서 볼 수 있습니다.

### 결과 확인

`work\작업이름\result\` 폴더에 두 파일이 생깁니다.

| 파일 | 뜻 |
|---|---|
| `보고서이름.processed.hwp` | **결과**. 이 파일을 한글로 열어 확인합니다 |
| `보고서이름.before.hwp` | 반영 전 사본. 비교용 |

검은 창 마지막에 "HWP 검증 통과"가 나오면 표 구조와 그림 수가 계획대로인 것입니다. "실패"가 나오면 결과 파일을 쓰지 말고 [문제가 생겼을 때](#문제가-생겼을-때)로 가세요.

---

## 문제가 생겼을 때

오류가 나면 아래 세 가지만 하면 됩니다. 고치는 것은 개발자가 합니다.

**① `report.bat` 더블클릭** → `reports` 폴더에 `dongdongs-report-….zip`이 생기고 폴더가 열립니다.
이 zip에는 실행 기록과 설정 정보만 들어 있습니다. **성적서 PDF, 보고서 HWP, 그림, 표 값은 들어가지 않습니다.**

**② GitHub에 로그인** (처음이라면 가입: 이메일만 있으면 됩니다)
📄 [GitHub 계정 만들기 – 한국어 안내](https://docs.github.com/ko/get-started/start-your-journey/creating-an-account-on-github)

**③ 이 저장소의 `Issues` 탭 → `New issue` → "오류 보고"** 양식에서 세 칸을 채우고 zip을 끌어다 붙인 뒤 `Submit`.
- 어느 단계에서 났는지
- 화면에 뜬 메시지 (복사하거나 사진)
- 성적서 몇 쪽과 관련 있는지

📄 [이슈 만들기 – 한국어 안내](https://docs.github.com/ko/issues/tracking-your-work-with-issues/using-issues/creating-an-issue)

**절대 PDF나 HWP 파일을 첨부하지 마세요.** 고쳐진 뒤에는 2단계처럼 ZIP을 다시 내려받아 풀면 됩니다(`install.bat`을 한 번 더 실행).

---

## 자주 묻는 것

| 증상 | 해결 |
|---|---|
| `python`을 찾을 수 없다고 나옴 | 1단계에서 PATH 체크박스를 안 켠 것입니다. `install.bat`을 실행하면 파이썬을 알아서 내려받으니 그대로 진행하세요 |
| 한글에서 "보안 승인" 창이 자꾸 뜸 | 프로그램이 승인 모듈을 자동 등록합니다. 그래도 뜨면 `허용`을 누르고, 계속되면 오류 보고를 해 주세요 |
| 검수 화면이 안 열림 | 브라우저 주소창에 `http://127.0.0.1:8765` 를 직접 입력하세요 |
| "결과 파일이 이미 있습니다" | 같은 작업 이름으로 두 번 반영한 것입니다. `run.bat`을 다시 실행해 다른 작업 이름을 쓰세요 |
| 반영 중 한글 창을 건드렸더니 이상함 | `work\작업이름\result\` 폴더를 지우고 `run.bat`으로 다시 하세요. 원본은 안전합니다 |
| 어떤 항목이 "확인 필요 — 워터마크 수동 처리"로 나옴 | 그 쪽은 DRAFT를 자동으로 못 지운 것입니다. 오류 보고를 해 주세요. 나머지 쪽은 정상 처리됩니다 |

---

## 고급: 명령으로 단계별 실행

`run.bat` 대신 검은 창에서 직접 실행할 수도 있습니다. 폴더에서 `Shift + 오른쪽 클릭` → "여기에 PowerShell 창 열기".

```powershell
uv run dongdongs init --pdf ".\input\성적서.pdf" --hwp ".\report\보고서.hwp" --work-dir .\work --job-id 작업이름
uv run dongdongs analyze --job .\work\작업이름
uv run dongdongs review  --job .\work\작업이름
uv run dongdongs apply   --job .\work\작업이름 --visible
uv run dongdongs verify  --job .\work\작업이름 --stage hwp
uv run dongdongs report  --job .\work\작업이름
```

단계별 명령(`inspect-pdf`, `clean`, `extract`, `inspect-hwp`, `map`)과 옵션은 `uv run dongdongs --help`에 있습니다.
