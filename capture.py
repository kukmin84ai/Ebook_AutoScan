"""
알라딘 PC 뷰어 자동 스크린 캡쳐
- 지정 영역 or 전체 화면 캡쳐
- 방향키(→)로 페이지 넘김
- 캡쳐 간 딜레이 조절 가능
"""

import pyautogui
import keyboard
import time
import os
import sys
import argparse
from datetime import datetime
from PIL import Image


def get_output_dir(book_name: str = "book") -> str:
    """캡쳐 저장 폴더 생성"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dirname = f"captures/{book_name}_{timestamp}"
    os.makedirs(dirname, exist_ok=True)
    return dirname


def select_region() -> tuple | None:
    """마우스로 캡쳐 영역 선택 (None이면 전체 화면)"""
    print("\n📐 캡쳐 영역을 설정합니다.")
    print("   [1] 전체 화면")
    print("   [2] 영역 지정 (마우스로 좌상단 → 우하단 클릭)")
    choice = input("   선택: ").strip()
    
    if choice != "2":
        return None
    
    print("\n   👆 알라딘 뷰어의 책 내용 좌상단 모서리를 클릭하세요...")
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
