"""OCR 환경 자동 구성 스크립트

venv_ocr/ 가상환경 생성 + KLOCR/PaddleOCR/Surya 설치 안내
"""

import subprocess
import sys
import shutil
from pathlib import Path


VENV_DIR = Path("venv_ocr")
REQUIREMENTS = "requirements-ocr.txt"


def find_python310() -> str | None:
    """Python 3.10 실행 파일 탐색"""
    # Windows py launcher
    for cmd in ["py -3.10", "python3.10"]:
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and "3.10" in result.stdout:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # 일반 설치 경로 확인 (Windows)
    common_paths = [
        Path(r"C:\Python310\python.exe"),
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python310" / "python.exe",
    ]
    for p in common_paths:
        if p.exists():
            return str(p)

    return None


def create_venv(python_cmd: str):
    """가상환경 생성"""
    print(f"\n📦 가상환경 생성: {VENV_DIR}/")
    cmd = python_cmd.split() + ["-m", "venv", str(VENV_DIR)]
    subprocess.run(cmd, check=True)
    print(f"   ✅ 가상환경 생성 완료")


def check_gpu():
    """GPU 사용 가능 여부 확인"""
    print("\n🔍 GPU 확인중...")
    pip_path = VENV_DIR / "Scripts" / "pip.exe"
    python_path = VENV_DIR / "Scripts" / "python.exe"

    if not python_path.exists():
        print("   ⚠️  가상환경이 아직 활성화되지 않았습니다.")
        return

    try:
        result = subprocess.run(
            [str(python_path), "-c", "import torch; print(torch.cuda.is_available())"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if "True" in result.stdout:
            print("   ✅ CUDA GPU 사용 가능!")
        else:
            print("   ⚠️  CUDA GPU를 찾을 수 없습니다. CPU 모드로 동작합니다.")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("   ⚠️  PyTorch가 아직 설치되지 않았습니다. 의존성 설치 후 확인하세요.")


def print_install_instructions():
    """설치 안내 메시지 출력"""
    print(f"\n{'='*60}")
    print("📋 다음 단계: 아래 명령어를 순서대로 실행하세요")
    print(f"{'='*60}")

    print(f"\n1️⃣  가상환경 활성화:")
    print(f"   {VENV_DIR}\\Scripts\\activate")

    print(f"\n2️⃣  기본 의존성 설치:")
    print(f"   pip install -r {REQUIREMENTS}")

    print(f"\n3️⃣  KLOCR 설치 (한글 OCR 엔진):")
    print(f"   git clone https://github.com/JHLee0513/KLOCR.git")
    print(f"   cd KLOCR && pip install .")

    print(f"\n4️⃣  KLOCR 모델 가중치 다운로드:")
    print(f"   Google Drive에서 가중치 파일을 다운로드하여")
    print(f"   KLOCR/weights/ 폴더에 배치하세요.")
    print(f"   (자세한 링크는 KLOCR GitHub 저장소의 README 참조)")

    print(f"\n5️⃣  GPU 확인 (선택):")
    print(f"   python -c \"import torch; print(torch.cuda.is_available())\"")

    print(f"\n6️⃣  OCR 실행:")
    print(f"   python ocr.py -i captures/책이름_폴더/")
    print(f"{'='*60}")


def main():
    """메인 실행"""
    print("🛠️  OCR 환경 자동 구성")
    print("=" * 40)

    # 1. Python 3.10 탐색
    print("\n🔍 Python 3.10 탐색중...")
    python_cmd = find_python310()

    if python_cmd:
        print(f"   ✅ Python 3.10 발견: {python_cmd}")
    else:
        print(f"   ⚠️  Python 3.10을 찾을 수 없습니다.")
        print(f"   현재 Python({sys.version.split()[0]})으로 진행합니다.")
        print(f"   (KLOCR는 Python 3.10 권장)")
        python_cmd = sys.executable

    # 2. 기존 가상환경 확인
    if VENV_DIR.exists():
        print(f"\n⚠️  {VENV_DIR}/ 가 이미 존재합니다.")
        answer = input("   삭제 후 재생성하시겠습니까? [y/N]: ").strip().lower()
        if answer == "y":
            shutil.rmtree(VENV_DIR)
            print(f"   🗑️  기존 가상환경 삭제됨")
        else:
            print(f"   기존 가상환경을 유지합니다.")
            print_install_instructions()
            return

    # 3. 가상환경 생성
    try:
        create_venv(python_cmd)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 가상환경 생성 실패: {e}")
        print(f"   수동으로 생성하세요: {python_cmd} -m venv {VENV_DIR}")
        sys.exit(1)

    # 4. requirements 파일 확인
    if not Path(REQUIREMENTS).exists():
        print(f"\n⚠️  {REQUIREMENTS} 파일이 없습니다.")

    # 5. 설치 안내
    print_install_instructions()

    # 6. GPU 확인은 의존성 설치 후 가능
    print(f"\n💡 의존성 설치 후 GPU 확인을 위해 다시 실행할 수 있습니다:")
    print(f"   python setup_ocr_env.py --check-gpu")


if __name__ == "__main__":
    if "--check-gpu" in sys.argv:
        check_gpu()
    else:
        main()
