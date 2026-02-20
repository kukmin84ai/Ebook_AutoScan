"""OCR 엔진 래퍼 — 다중 백엔드 지원 (KLOCR / PaddleOCR / EasyOCR)"""

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import setup_logging, save_json


@dataclass
class OCRResult:
    """단일 텍스트 영역 인식 결과"""

    region_id: int
    text: str
    confidence: float
    bbox: list[int]  # [x1, y1, x2, y2]
    needs_review: bool = False  # confidence < threshold 시 True


@dataclass
class PageOCRResult:
    """한 페이지의 OCR 결과"""

    page_num: int
    engine: str
    results: list[OCRResult] = field(default_factory=list)
    processing_time: float = 0.0  # 초


class BaseOCREngine(ABC):
    """OCR 엔진 추상 기반 클래스"""

    def __init__(self, config: OCRConfig):
        self.config = config
        self.logger = setup_logging(config.verbose)

    @abstractmethod
    def recognize(self, image: np.ndarray, regions: list[dict] | None = None) -> list[OCRResult]:
        """이미지에서 텍스트 인식"""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """엔진 사용 가능 여부"""
        ...


class KLOCREngine(BaseOCREngine):
    """KLOCR 엔진 래퍼"""

    def __init__(self, config: OCRConfig):
        super().__init__(config)
        self._available = False
        self._pipeline = None

        try:
            import kloser
            self._pipeline = kloser.Pipeline("configs/default.yaml")
            self._available = True
            self.logger.debug("KLOCR 엔진 초기화 완료")
        except ImportError:
            self.logger.debug("kloser 패키지를 찾을 수 없습니다")
        except Exception as e:
            self.logger.debug(f"KLOCR 초기화 실패: {e}")

    def is_available(self) -> bool:
        """KLOCR 사용 가능 여부"""
        if not self._available:
            return False
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def recognize(self, image: np.ndarray, regions: list[dict] | None = None) -> list[OCRResult]:
        """KLOCR로 텍스트 인식"""
        results: list[OCRResult] = []

        try:
            if regions:
                for idx, region in enumerate(regions):
                    bbox = region["bbox"]
                    x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                    cropped = image[y1:y2, x1:x2]
                    output = self._pipeline.run({"image": cropped})
                    for text_item in output.get("text", []):
                        text = text_item if isinstance(text_item, str) else str(text_item)
                        results.append(OCRResult(
                            region_id=idx + 1,
                            text=text,
                            confidence=0.9,  # KLOCR은 confidence를 직접 제공하지 않을 수 있음
                            bbox=[x1, y1, x2, y2],
                        ))
            else:
                output = self._pipeline.run({"image": image})
                rois = output.get("roi", [])
                texts = output.get("text", [])
                for idx, text in enumerate(texts):
                    text_str = text if isinstance(text, str) else str(text)
                    bbox = [0, 0, image.shape[1], image.shape[0]]
                    if idx < len(rois):
                        roi = rois[idx]
                        if isinstance(roi, (list, tuple)) and len(roi) >= 4:
                            bbox = [int(v) for v in roi[:4]]
                    results.append(OCRResult(
                        region_id=idx + 1,
                        text=text_str,
                        confidence=0.9,
                        bbox=bbox,
                    ))
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "CUDA" in str(e):
                self.logger.warning("KLOCR GPU 메모리 부족 — 이 페이지 건너뜀")
            else:
                raise

        return results


class PaddleOCREngine(BaseOCREngine):
    """PaddleOCR 엔진 래퍼"""

    def __init__(self, config: OCRConfig):
        super().__init__(config)
        self._available = False
        self._ocr = None

        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang="korean",
                use_gpu=config.use_gpu,
                show_log=False,
            )
            self._available = True
            self.logger.debug("PaddleOCR 엔진 초기화 완료")
        except ImportError:
            self.logger.debug("paddleocr 패키지를 찾을 수 없습니다")
        except Exception as e:
            self.logger.debug(f"PaddleOCR 초기화 실패: {e}")

    def is_available(self) -> bool:
        """PaddleOCR 사용 가능 여부"""
        return self._available

    def recognize(self, image: np.ndarray, regions: list[dict] | None = None) -> list[OCRResult]:
        """PaddleOCR로 텍스트 인식"""
        results: list[OCRResult] = []

        targets = []
        if regions:
            for region in regions:
                bbox = region["bbox"]
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                targets.append((image[y1:y2, x1:x2], [x1, y1, x2, y2]))
        else:
            targets.append((image, [0, 0, image.shape[1], image.shape[0]]))

        region_id = 1
        for target_img, fallback_bbox in targets:
            try:
                ocr_output = self._ocr.ocr(target_img, cls=True)
            except Exception as e:
                self.logger.warning(f"PaddleOCR 인식 실패: {e}")
                continue

            if not ocr_output or ocr_output[0] is None:
                continue

            for line in ocr_output[0]:
                # line = [bbox_points, (text, confidence)]
                bbox_points = line[0]
                text, confidence = line[1]

                # bbox_points는 4개의 꼭짓점 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

                # 영역 기준 좌표를 원본 이미지 기준으로 보정
                if regions:
                    bbox = [
                        bbox[0] + fallback_bbox[0],
                        bbox[1] + fallback_bbox[1],
                        bbox[2] + fallback_bbox[0],
                        bbox[3] + fallback_bbox[1],
                    ]

                results.append(OCRResult(
                    region_id=region_id,
                    text=text,
                    confidence=float(confidence),
                    bbox=bbox,
                ))
                region_id += 1

        return results


class EasyOCREngine(BaseOCREngine):
    """EasyOCR 엔진 래퍼 (폴백용)"""

    def __init__(self, config: OCRConfig):
        super().__init__(config)
        self._available = False
        self._reader = None

        try:
            import easyocr
            self._reader = easyocr.Reader(["ko", "en"], gpu=config.use_gpu)
            self._available = True
            self.logger.debug("EasyOCR 엔진 초기화 완료")
        except ImportError:
            self.logger.debug("easyocr 패키지를 찾을 수 없습니다")
        except Exception as e:
            self.logger.debug(f"EasyOCR 초기화 실패: {e}")

    def is_available(self) -> bool:
        """EasyOCR 사용 가능 여부"""
        return self._available

    def recognize(self, image: np.ndarray, regions: list[dict] | None = None) -> list[OCRResult]:
        """EasyOCR로 텍스트 인식"""
        results: list[OCRResult] = []

        targets = []
        if regions:
            for region in regions:
                bbox = region["bbox"]
                x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                targets.append((image[y1:y2, x1:x2], [x1, y1, x2, y2]))
        else:
            targets.append((image, [0, 0, image.shape[1], image.shape[0]]))

        region_id = 1
        for target_img, fallback_bbox in targets:
            try:
                ocr_output = self._reader.readtext(target_img)
            except Exception as e:
                self.logger.warning(f"EasyOCR 인식 실패: {e}")
                continue

            for (bbox_points, text, confidence) in ocr_output:
                # bbox_points는 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 또는 유사 형태
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                bbox = [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

                # 영역 기준 좌표를 원본 이미지 기준으로 보정
                if regions:
                    bbox = [
                        bbox[0] + fallback_bbox[0],
                        bbox[1] + fallback_bbox[1],
                        bbox[2] + fallback_bbox[0],
                        bbox[3] + fallback_bbox[1],
                    ]

                results.append(OCRResult(
                    region_id=region_id,
                    text=text,
                    confidence=float(confidence),
                    bbox=bbox,
                ))
                region_id += 1

        return results


def create_engine(config: OCRConfig) -> BaseOCREngine:
    """설정에 따라 적절한 OCR 엔진 생성 (폴백 지원)"""
    logger = setup_logging(config.verbose)

    if config.engine == "klocr":
        engine = KLOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: KLOCR")
            return engine
        logger.warning("KLOCR 사용 불가 — PaddleOCR로 폴백")

        engine = PaddleOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: PaddleOCR (폴백)")
            return engine
        logger.warning("PaddleOCR 사용 불가 — EasyOCR로 폴백")

        engine = EasyOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: EasyOCR (폴백)")
            return engine

    elif config.engine == "paddle":
        engine = PaddleOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: PaddleOCR")
            return engine
        logger.warning("PaddleOCR 사용 불가 — EasyOCR로 폴백")

        engine = EasyOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: EasyOCR (폴백)")
            return engine

    elif config.engine == "easyocr":
        engine = EasyOCREngine(config)
        if engine.is_available():
            logger.info("OCR 엔진: EasyOCR")
            return engine

    raise RuntimeError(
        f"사용 가능한 OCR 엔진이 없습니다. "
        f"paddleocr 또는 easyocr를 설치해 주세요: pip install paddleocr easyocr"
    )


def run_ocr(
    engine: BaseOCREngine,
    image: np.ndarray,
    page_num: int,
    regions: list[dict] | None,
    config: OCRConfig,
) -> PageOCRResult:
    """단일 페이지 OCR 실행"""
    logger = setup_logging(config.verbose)
    engine_name = engine.__class__.__name__.replace("Engine", "").lower()

    start = time.time()

    try:
        results = engine.recognize(image, regions)
    except RuntimeError as e:
        if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
            logger.warning(f"페이지 {page_num}: GPU 메모리 부족 — 빈 결과 반환")
            return PageOCRResult(
                page_num=page_num,
                engine=engine_name,
                results=[],
                processing_time=time.time() - start,
            )
        raise
    except Exception as e:
        logger.error(f"페이지 {page_num}: OCR 실패 — {e}")
        return PageOCRResult(
            page_num=page_num,
            engine=engine_name,
            results=[],
            processing_time=time.time() - start,
        )

    # needs_review 플래그 설정
    for r in results:
        r.needs_review = r.confidence < config.confidence_threshold

    elapsed = time.time() - start

    return PageOCRResult(
        page_num=page_num,
        engine=engine_name,
        results=results,
        processing_time=elapsed,
    )


def save_ocr_result(result: PageOCRResult, output_dir: Path):
    """OCR 결과를 JSON으로 저장 (page_NNNN_ocr.json)"""
    data = {
        "page_num": result.page_num,
        "engine": result.engine,
        "results": [
            {
                "region_id": r.region_id,
                "text": r.text,
                "confidence": round(r.confidence, 4),
                "reading_order": idx + 1,
                "needs_review": r.needs_review,
            }
            for idx, r in enumerate(result.results)
        ],
    }

    filename = f"page_{result.page_num:04d}_ocr.json"
    save_json(data, output_dir / filename)
