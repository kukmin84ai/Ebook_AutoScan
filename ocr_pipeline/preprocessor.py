"""이미지 품질 평가 및 전처리 모듈"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import setup_logging, load_image, get_page_number


@dataclass
class QualityResult:
    """이미지 품질 평가 결과"""

    page_num: int
    is_acceptable: bool  # OCR 진행 가능 여부
    blur_score: float  # Laplacian 분산 (높을수록 선명)
    brightness: float  # 평균 밝기 0-255
    contrast: float  # 밝기 표준편차
    warnings: list[str] = field(default_factory=list)


def assess_quality(image: np.ndarray, config: OCRConfig, page_num: int = 0) -> QualityResult:
    """이미지 품질 평가 -흐림, 밝기, 대비 검사"""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # 흐림 감지: Laplacian 분산
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    blur_score = float(laplacian.var())

    # 밝기: 그레이스케일 평균
    brightness = float(gray.mean())

    # 대비: 그레이스케일 표준편차
    contrast = float(gray.std())

    warnings: list[str] = []

    if blur_score < config.blur_threshold:
        warnings.append(f"이미지가 흐릿합니다 (blur_score={blur_score:.1f}, 기준={config.blur_threshold})")

    if brightness < config.brightness_min:
        warnings.append(f"이미지가 너무 어둡습니다 (brightness={brightness:.1f})")

    if brightness > config.brightness_max:
        warnings.append(f"이미지가 너무 밝습니다 (brightness={brightness:.1f})")

    if contrast < 20:
        warnings.append(f"대비가 너무 낮습니다 (contrast={contrast:.1f})")

    # 극도로 흐릿한 경우만 is_acceptable=False
    is_acceptable = blur_score >= config.blur_threshold * 0.5

    return QualityResult(
        page_num=page_num,
        is_acceptable=is_acceptable,
        blur_score=blur_score,
        brightness=brightness,
        contrast=contrast,
        warnings=warnings,
    )


def _detect_skew_angle(gray: np.ndarray) -> float:
    """이진화된 이미지에서 기울기 각도 감지 (도 단위)"""
    # 이진화
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 텍스트 영역의 좌표 추출
    coords = np.column_stack(np.where(binary > 0))
    if len(coords) < 100:
        return 0.0

    # minAreaRect로 기울기 추정
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]

    # OpenCV minAreaRect 각도 보정
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90

    return float(angle)


def preprocess(image: np.ndarray, config: OCRConfig) -> np.ndarray:
    """이미지 전처리 -기울기 보정, CLAHE, 노이즈 제거"""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # 기울기 보정
    if config.deskew_enabled:
        angle = _detect_skew_angle(gray)
        if abs(angle) > 0.5:
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            image = cv2.warpAffine(
                image, rotation_matrix, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # CLAHE 적응형 히스토그램 평활화
    clahe = cv2.createCLAHE(
        clipLimit=config.clahe_clip_limit,
        tileGridSize=(config.clahe_grid_size, config.clahe_grid_size),
    )
    enhanced = clahe.apply(gray)

    # 노이즈 제거
    denoised = cv2.fastNlMeansDenoising(enhanced, h=10, templateWindowSize=7, searchWindowSize=21)

    # 그레이스케일 → RGB 3채널로 변환
    result = cv2.cvtColor(denoised, cv2.COLOR_GRAY2RGB)

    return result.astype(np.uint8)


def run_quality_check(page_files: list[Path], config: OCRConfig) -> list[QualityResult]:
    """배치 품질 검사 -전체 페이지 품질 평가 및 요약 출력"""
    logger = setup_logging(config.verbose)
    results: list[QualityResult] = []

    for page_path in tqdm(page_files, desc="품질 검사"):
        page_num = get_page_number(page_path)
        image = load_image(page_path)
        result = assess_quality(image, config, page_num=page_num)
        results.append(result)

    # 요약 출력
    acceptable = sum(1 for r in results if r.is_acceptable and not r.warnings)
    with_warnings = sum(1 for r in results if r.is_acceptable and r.warnings)
    unacceptable = sum(1 for r in results if not r.is_acceptable)

    print(f"\n품질 검사 완료: 총 {len(results)}페이지")
    print(f"  양호: {acceptable}페이지")
    print(f"  경고: {with_warnings}페이지")
    print(f"  부적합: {unacceptable}페이지")

    # 경고/부적합 상세 출력
    for r in results:
        if r.warnings:
            for w in r.warnings:
                logger.warning(f"페이지 {r.page_num}: {w}")
        if not r.is_acceptable:
            logger.error(f"페이지 {r.page_num}: OCR 진행 불가 (blur_score={r.blur_score:.1f})")

    return results
