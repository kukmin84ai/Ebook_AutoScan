"""
알라딘 PC 뷰어 자동 스크린 캡쳐
- 지정 영역 or 전체 화면 캡쳐
- 방향키(→)로 페이지 넘김
- 캡쳐 간 딜레이 조절 가능
- 책 영역 자동 탐지
- DPI-aware 고해상도 캡쳐
"""

import ctypes
import pyautogui
import keyboard
import time
import os
import sys
import argparse
import numpy as np
from datetime import datetime
from PIL import Image, ImageFilter

# Windows DPI 인식 활성화 — 고해상도 캡쳐를 위해 필수
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # fallback
    except Exception:
        pass


def get_output_dir(book_name: str = "book") -> str:
    """캡쳐 저장 폴더 생성"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dirname = f"captures/{book_name}_{timestamp}"
    os.makedirs(dirname, exist_ok=True)
    return dirname


def detect_book_region() -> tuple | None:
    """
    전체 화면을 캡쳐한 뒤, 책 콘텐츠 영역을 자동으로 탐지.
    알라딘 뷰어의 책 페이지는 주변(툴바, 배경)과 색상 차이가 크므로
    밝은 직사각형 영역(책 페이지)을 찾아냄.
    """
    print("\n🔍 책 영역 자동 탐지 중...")
    print("   알라딘 뷰어가 화면에 보이는 상태여야 합니다.")
    time.sleep(1)

    screenshot = pyautogui.screenshot()
    img = np.array(screenshot.convert("L"))  # 그레이스케일
    h, w = img.shape

    # 책 페이지는 보통 밝은 영역(흰색 배경) — 임계값으로 이진화
    threshold = 240
    binary = (img > threshold).astype(np.uint8)

    # 행/열 방향으로 밝은 픽셀 비율 계산
    row_ratio = binary.mean(axis=1)  # 각 행의 밝은 픽셀 비율
    col_ratio = binary.mean(axis=0)  # 각 열의 밝은 픽셀 비율

    # 밝은 비율이 일정 이상인 연속 구간 찾기
    row_thresh = 0.3
    col_thresh = 0.3

    row_mask = row_ratio > row_thresh
    col_mask = col_ratio > col_thresh

    def find_longest_run(mask):
        """True가 연속되는 가장 긴 구간의 시작/끝 인덱스"""
        best_start, best_len = 0, 0
        cur_start, cur_len = 0, 0
        for i, v in enumerate(mask):
            if v:
                if cur_len == 0:
                    cur_start = i
                cur_len += 1
            else:
                if cur_len > best_len:
                    best_start, best_len = cur_start, cur_len
                cur_len = 0
        if cur_len > best_len:
            best_start, best_len = cur_start, cur_len
        return best_start, best_start + best_len

    y1, y2 = find_longest_run(row_mask)
    x1, x2 = find_longest_run(col_mask)

    # 너무 작거나 전체 화면과 거의 같으면 탐지 실패
    region_w = x2 - x1
    region_h = y2 - y1
    if region_w < w * 0.1 or region_h < h * 0.1:
        print("   ⚠️  책 영역을 찾지 못했습니다. 수동 선택으로 전환합니다.")
        return None
    if region_w > w * 0.95 and region_h > h * 0.95:
        print("   ⚠️  전체 화면이 감지되었습니다. 수동 선택으로 전환합니다.")
        return None

    # 약간의 패딩 제거 (경계 여백 정리)
    pad = 5
    x1 = min(x1 + pad, x2)
    y1 = min(y1 + pad, y2)
    x2 = max(x2 - pad, x1)
    y2 = max(y2 - pad, y1)

    region = (x1, y1, x2 - x1, y2 - y1)
    print(f"   ✅ 탐지 완료: 위치({x1}, {y1}), 크기 {region[2]}x{region[3]} px")
    return region


def select_region() -> tuple | None:
    """캡쳐 영역 선택 (자동 탐지 / 수동 / 전체화면)"""
    print("\n📐 캡쳐 영역을 설정합니다.")
    print("   [1] 전체 화면")
    print("   [2] 영역 지정 (마우스로 좌상단 → 우하단 F8)")
    print("   [3] 자동 탐지 (책 영역 자동 감지)")
    choice = input("   선택: ").strip()

    if choice == "3":
        region = detect_book_region()
        if region:
            return region
        print("   → 수동 선택으로 전환합니다.\n")
        choice = "2"

    if choice != "2":
        return None

    print("\n   👆 알라딘 뷰어의 책 내용 좌상단 모서리에서 F8을 누르세요...")
    print("   (3초 후 감지 시작)")
    time.sleep(3)
    keyboard.wait("F8")
    x1, y1 = pyautogui.position()
    print(f"   ✅ 좌상단: ({x1}, {y1})")

    print("   👆 이제 우하단 모서리에서 F8을 누르세요...")
    keyboard.wait("F8")
    x2, y2 = pyautogui.position()
    print(f"   ✅ 우하단: ({x2}, {y2})")

    region = (x1, y1, x2 - x1, y2 - y1)
    print(f"   📏 영역: {region[2]}x{region[3]} px")
    return region


def capture_page(output_dir: str, page_num: int, region: tuple | None = None) -> str:
    """한 페이지 캡쳐"""
    filename = os.path.join(output_dir, f"page_{page_num:04d}.png")
    
    if region:
        screenshot = pyautogui.screenshot(region=region)
    else:
        screenshot = pyautogui.screenshot()
    
    screenshot.save(filename)
    return filename


def is_duplicate(img1_path: str, img2_path: str, threshold: float = 0.99) -> bool:
    """두 이미지가 거의 동일한지 비교 (마지막 페이지 감지용)"""
    try:
        img1 = Image.open(img1_path).convert("L").resize((200, 200))
        img2 = Image.open(img2_path).convert("L").resize((200, 200))
        
        pixels1 = list(img1.getdata())
        pixels2 = list(img2.getdata())
        
        matches = sum(1 for a, b in zip(pixels1, pixels2) if abs(a - b) < 10)
        similarity = matches / len(pixels1)
        
        return similarity >= threshold
    except Exception:
        return False


def run_capture(
    book_name: str = "book",
    total_pages: int = 0,
    delay: float = 1.0,
    next_key: str = "right",
    region: tuple | None = None,
    auto_stop: bool = True,
    duplicate_limit: int = 3,
):
    """
    메인 캡쳐 루프
    
    Args:
        book_name: 책 이름 (폴더명)
        total_pages: 총 페이지 수 (0이면 무한, 중복 감지로 자동 정지)
        delay: 페이지 넘김 후 대기 시간 (초)
        next_key: 페이지 넘김 키 (right, space, pagedown 등)
        region: 캡쳐 영역 (None이면 전체)
        auto_stop: 중복 페이지 감지 시 자동 정지
        duplicate_limit: 연속 중복 이 횟수면 정지
    """
    output_dir = get_output_dir(book_name)
    
    print(f"\n{'='*50}")
    print(f"📖 자동 캡쳐 시작: {book_name}")
    print(f"   저장: {output_dir}/")
    print(f"   페이지 넘김: [{next_key}] 키")
    print(f"   딜레이: {delay}초")
    print(f"   총 페이지: {'자동감지' if total_pages == 0 else total_pages}")
    print(f"{'='*50}")
    print(f"\n⏳ 5초 후 시작합니다. 알라딘 뷰어를 포커스하세요!")
    print(f"   🛑 중지: ESC 키")
    time.sleep(5)
    
    page = 1
    duplicate_count = 0
    last_file = None
    
    try:
        while True:
            # ESC 중지
            if keyboard.is_pressed("esc"):
                print(f"\n🛑 ESC — 중지됨 (총 {page-1} 페이지)")
                break
            
            # 총 페이지 도달
            if total_pages > 0 and page > total_pages:
                print(f"\n✅ {total_pages} 페이지 완료!")
                break
            
            # 캡쳐
            filepath = capture_page(output_dir, page, region)
            
            # 중복 감지
            if auto_stop and last_file:
                if is_duplicate(last_file, filepath):
                    duplicate_count += 1
                    if duplicate_count >= duplicate_limit:
                        # 중복 파일 삭제
                        for i in range(duplicate_limit):
                            dup = os.path.join(output_dir, f"page_{page-i:04d}.png")
                            if os.path.exists(dup):
                                os.remove(dup)
                        print(f"\n✅ 마지막 페이지 감지! (총 {page - duplicate_limit} 페이지)")
                        break
                else:
                    duplicate_count = 0
            
            last_file = filepath
            
            # 진행 표시
            if total_pages > 0:
                pct = page / total_pages * 100
                print(f"   📄 {page}/{total_pages} ({pct:.0f}%) — {filepath}", end="\r")
            else:
                print(f"   📄 {page} — {filepath}", end="\r")
            
            # 페이지 넘기기
            pyautogui.press(next_key)
            time.sleep(delay)
            
            page += 1
            
    except KeyboardInterrupt:
        print(f"\n🛑 Ctrl+C — 중지됨 (총 {page-1} 페이지)")
    
    # 결과
    files = [f for f in os.listdir(output_dir) if f.endswith(".png")]
    print(f"\n📊 결과: {len(files)} 페이지 → {output_dir}/")
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="알라딘 PC 뷰어 자동 스크린 캡쳐")
    parser.add_argument("--name", "-n", default="book", help="책 이름 (폴더명)")
    parser.add_argument("--pages", "-p", type=int, default=0, help="총 페이지 수 (0=자동감지)")
    parser.add_argument("--delay", "-d", type=float, default=1.0, help="페이지 넘김 딜레이 (초)")
    parser.add_argument("--key", "-k", default="right", help="페이지 넘김 키 (right/space/pagedown)")
    parser.add_argument("--fullscreen", "-f", action="store_true", help="전체 화면 캡쳐 (영역 선택 건너뜀)")
    parser.add_argument("--no-auto-stop", action="store_true", help="자동 정지 비활성화")
    
    args = parser.parse_args()
    
    print("🖥️  알라딘 자동 캡쳐 도구")
    print("="*40)
    
    # 영역 선택
    region = None
    if not args.fullscreen:
        region = select_region()
    
    # 실행
    run_capture(
        book_name=args.name,
        total_pages=args.pages,
        delay=args.delay,
        next_key=args.key,
        region=region,
        auto_stop=not args.no_auto_stop,
    )


if __name__ == "__main__":
    main()
