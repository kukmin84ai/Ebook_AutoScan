# CLAUDE.md — Ebook AutoScan

## Project Overview
알라딘 PC 뷰어 자동 스크린 캡쳐 도구. 지정 영역 또는 전체 화면을 캡쳐하고, 키보드 입력으로 페이지를 넘기며 자동으로 책 전체를 스캔한다. OCR 파이프라인을 통해 캡쳐된 이미지에서 한글 텍스트를 추출하고 마크다운 문서를 생성한다.

## Tech Stack
- **Language**: Python 3.10+
- **Key Libraries**: pyautogui, Pillow, keyboard, numpy
- **OCR Libraries**: PaddleOCR, Surya OCR, KLOCR (선택), EasyOCR (폴백)
- **Platform**: Windows only (ctypes.windll 사용)

## Project Structure
```
Ebook_AutoScan/
├── capture.py              # 메인 캡쳐 스크립트 (단일 파일)
├── ocr.py                  # OCR 파이프라인 진입점
├── setup_ocr_env.py        # OCR 가상환경 자동 구성
├── requirements.txt        # 캡쳐 의존성
├── requirements-ocr.txt    # OCR 의존성
├── ocr_pipeline/           # OCR 파이프라인 패키지
│   ├── __init__.py
│   ├── __main__.py         # python -m ocr_pipeline 진입점
│   ├── cli.py              # CLI 파싱 + 파이프라인 오케스트레이션
│   ├── config.py           # 설정 dataclass
│   ├── preprocessor.py     # 이미지 품질 평가 + 전처리
│   ├── layout_analyzer.py  # Surya 기반 레이아웃 + 읽기 순서
│   ├── ocr_engine.py       # OCR 엔진 래퍼 (PaddleOCR/KLOCR/EasyOCR)
│   ├── postprocessor.py    # 한글 후처리, 자모 보정, 신뢰도
│   ├── markdown_builder.py # 마크다운 조립 (페이지별 → 전체 문서)
│   ├── checkpoint.py       # 체크포인트 저장/복원
│   └── utils.py            # 공통 유틸 (로깅, 파일 I/O)
├── venv/                   # 캡쳐 가상환경
├── venv_ocr/               # OCR 가상환경 (Python 3.10)
├── captures/               # 캡쳐 결과 저장 폴더
│   └── book_timestamp/
│       ├── page_0001.png
│       └── ocr_output/     # OCR 결과
│           ├── book.md
│           ├── book_metadata.json
│           └── images/
├── README.md
└── CLAUDE.md
```

## Key Commands
```bash
# === 캡쳐 ===
venv\Scripts\activate
pip install -r requirements.txt
python capture.py --name "책이름"
python capture.py --name "책이름" --fullscreen

# === OCR ===
# 환경 설정 (최초 1회)
python setup_ocr_env.py
venv_ocr\Scripts\activate
pip install -r requirements-ocr.txt

# 기본 OCR 실행
python ocr.py -i captures/책이름_폴더/

# 중단 후 재개
python ocr.py -i captures/책이름_폴더/ --resume

# 품질 검사만
python ocr.py -i captures/책이름_폴더/ --quality-check-only

# 특정 페이지만
python ocr.py -i captures/책이름_폴더/ --pages 1-50

# GPU 미사용
python ocr.py -i captures/책이름_폴더/ --no-gpu

# 모듈 실행
python -m ocr_pipeline -i captures/책이름_폴더/
```

## Architecture Notes
- `capture.py` 단일 파일 구조 — 모든 캡쳐 로직이 하나의 파일에 있음
- DPI-aware 캡쳐: `ctypes.windll.shcore.SetProcessDpiAwareness(2)` 사용
- 중복 감지 기반 자동 정지: 연속 동일 페이지 감지 시 캡쳐 종료
- 책 영역 자동 탐지: 밝은 직사각형 영역(흰색 배경)을 numpy로 검출
- OCR 파이프라인: Surya(레이아웃) → PaddleOCR/KLOCR(텍스트) → 마크다운 조립
- 체크포인트 기반 중단/재개 지원 (대용량 책 대비)
- 한글 자모 후처리: OCR 오류 보정, 줄바꿈 병합

## Conventions
- 한국어 UI 메시지 사용 (print 문, 이모지 접두)
- 함수별 한국어 docstring
- CLI 인자: argparse 기반
- 캡쳐 파일명: `page_NNNN.png` (4자리 zero-pad)
- 출력 폴더: `captures/{book_name}_{timestamp}/`
- OCR 중간 결과: `page_NNNN_layout.json`, `page_NNNN_ocr.json`

## Development Guidelines
- Windows 전용 프로젝트이므로 Unix 호환성 고려 불필요
- `keyboard` 라이브러리는 관리자 권한이 필요할 수 있음
- 캡쳐 테스트 시 실제 화면 의존성이 있어 유닛 테스트 작성이 어려움
- `captures/` 폴더는 대용량이므로 `.gitignore`에 추가
- OCR 의존성은 `venv_ocr/` 별도 가상환경 사용 (Python 3.10 권장)
- Surya, PaddleOCR, KLOCR은 선택적 의존성 — import 실패 시 폴백 처리
