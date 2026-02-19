# 📖 Auto Screen Capture

알라딘 PC 뷰어 자동 스크린 캡쳐 도구

## 설치

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 사용법

### 기본 (영역 선택 + 자동 정지)
```bash
python capture.py --name "사피엔스"
```

### 전체 화면 캡쳐
```bash
python capture.py --name "사피엔스" --fullscreen
```

### 페이지 수 지정
```bash
python capture.py --name "사피엔스" --pages 350
```

### 딜레이 조절 (느린 렌더링일 때)
```bash
python capture.py --name "사피엔스" --delay 2.0
```

### 페이지 넘김 키 변경
```bash
python capture.py --name "사피엔스" --key space
```

## 워크플로우

1. 알라딘 PC 뷰어에서 책을 열고 **첫 페이지**로 이동
2. `python capture.py --name "책이름"` 실행
3. 영역 선택: F8로 좌상단/우하단 클릭 (또는 `--fullscreen`)
4. 5초 카운트다운 동안 알라딘 뷰어 클릭하여 포커스
5. 자동 캡쳐 시작 → 마지막 페이지에서 자동 정지
6. 중간에 멈추려면 **ESC**

## 결과

`captures/책이름_날짜시간/` 폴더에 `page_0001.png` ~ 순서대로 저장

## 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--name, -n` | 책 이름 | book |
| `--pages, -p` | 총 페이지 수 (0=자동) | 0 |
| `--delay, -d` | 넘김 딜레이 (초) | 1.0 |
| `--key, -k` | 넘김 키 | right |
| `--fullscreen, -f` | 전체화면 캡쳐 | false |
| `--no-auto-stop` | 자동정지 끔 | false |
