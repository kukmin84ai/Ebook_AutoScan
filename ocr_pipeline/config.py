"""OCR 파이프라인 설정 dataclass"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OCRConfig:
    """OCR 파이프라인 전체 설정"""

    # 입출력 경로
    input_dir: Path = field(default_factory=lambda: Path("."))
    output_subdir: str = "ocr_output"

    # OCR 엔진
    engine: str = "paddle"  # "paddle" | "easyocr"
    use_gpu: bool = True

    # 레이아웃 분석
    use_layout: bool = True

    # 페이지 범위
    page_start: int = 1
    page_end: int = 0  # 0 = 전체

    # 배치/성능
    batch_size: int = 4

    # 신뢰도 임계값
    confidence_threshold: float = 0.7

    # 체크포인트
    resume: bool = False
    checkpoint_interval: int = 10  # N페이지마다 저장

    # 품질 검사
    quality_check_only: bool = False

    # 전처리 파라미터
    blur_threshold: float = 100.0  # Laplacian 분산 기준
    brightness_min: int = 50
    brightness_max: int = 230
    deskew_enabled: bool = True
    clahe_clip_limit: float = 2.0
    clahe_grid_size: int = 8

    # 로깅
    verbose: bool = False

    @property
    def output_dir(self) -> Path:
        """OCR 결과 출력 폴더"""
        return self.input_dir / self.output_subdir

    @property
    def images_dir(self) -> Path:
        """추출된 이미지/표 저장 폴더"""
        return self.output_dir / "images"

    @property
    def checkpoint_path(self) -> Path:
        """체크포인트 파일 경로"""
        return self.input_dir / ".ocr_checkpoint.json"

    def ensure_dirs(self):
        """출력 디렉토리 생성"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
