"""레이아웃 분석 -Surya 기반 영역 검출 및 읽기 순서 결정"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import save_json

logger = logging.getLogger("ocr_pipeline")

# ── 데이터클래스 ──────────────────────────────────────────────


@dataclass
class LayoutRegion:
    """페이지 내 단일 영역"""

    id: int
    bbox: list[int]  # [x1, y1, x2, y2]
    region_type: str  # "text", "figure", "table", "header", "footer"
    reading_order: int
    confidence: float
    extracted_image: str | None = None  # 이미지/표 추출 시 상대 경로


@dataclass
class PageLayout:
    """페이지 전체 레이아웃 정보"""

    page_num: int
    width: int
    height: int
    regions: list[LayoutRegion]


# ── Surya 초기화 ─────────────────────────────────────────────

_layout_predictor = None
_ordering_predictor = None
_surya_available: bool | None = None


def _init_surya():
    """Surya 레이아웃/순서 모델 초기화 (선택적 의존성)"""
    global _layout_predictor, _ordering_predictor, _surya_available

    if _surya_available is not None:
        return _surya_available

    try:
        from surya.layout import LayoutPredictor
        from surya.ordering import OrderingPredictor

        _layout_predictor = LayoutPredictor()
        _ordering_predictor = OrderingPredictor()
        _surya_available = True
        logger.info("Surya 레이아웃 모델 초기화 완료")
    except Exception as e:
        _surya_available = False
        logger.warning("Surya 사용 불가 -전체 페이지를 단일 텍스트 영역으로 처리합니다: %s", e)

    return _surya_available


# ── Surya 영역 타입 매핑 ──────────────────────────────────────

_SURYA_TYPE_MAP = {
    "Text": "text",
    "TextInlineMath": "text",
    "Title": "header",
    "SectionHeader": "header",
    "Caption": "text",
    "Picture": "figure",
    "Figure": "figure",
    "Table": "table",
    "Formula": "text",
    "Footnote": "footer",
    "PageHeader": "header",
    "PageFooter": "footer",
    "ListItem": "text",
}


def _map_region_type(surya_type: str) -> str:
    """Surya 영역 타입을 내부 타입으로 변환"""
    return _SURYA_TYPE_MAP.get(surya_type, "text")


# ── 레이아웃 분석 ─────────────────────────────────────────────


def analyze_layout(image: np.ndarray, page_num: int, config: OCRConfig) -> PageLayout:
    """페이지 이미지의 레이아웃을 분석하여 영역과 읽기 순서를 결정한다"""
    h, w = image.shape[:2]

    if config.use_layout and _init_surya():
        return _analyze_with_surya(image, page_num, w, h)

    # Surya 미사용 또는 사용 불가 -전체 페이지를 하나의 텍스트 영역으로
    region = LayoutRegion(
        id=0,
        bbox=[0, 0, w, h],
        region_type="text",
        reading_order=0,
        confidence=1.0,
    )
    return PageLayout(page_num=page_num, width=w, height=h, regions=[region])


def _analyze_with_surya(
    image: np.ndarray, page_num: int, width: int, height: int
) -> PageLayout:
    """Surya를 사용한 실제 레이아웃 분석"""
    pil_image = Image.fromarray(image)

    # 레이아웃 검출
    layout_results = _layout_predictor([pil_image])
    layout_result = layout_results[0]

    # 읽기 순서 결정
    ordering_results = _ordering_predictor([pil_image], [layout_result])
    ordering_result = ordering_results[0]

    regions: list[LayoutRegion] = []

    for idx, (bbox_obj, order_obj) in enumerate(
        zip(layout_result.bboxes, ordering_result.bboxes)
    ):
        bbox = [int(v) for v in bbox_obj.bbox]
        region_type = _map_region_type(getattr(bbox_obj, "label", "Text"))
        confidence = getattr(bbox_obj, "confidence", 0.9)
        reading_order = getattr(order_obj, "position", idx)

        regions.append(
            LayoutRegion(
                id=idx,
                bbox=bbox,
                region_type=region_type,
                reading_order=reading_order,
                confidence=confidence,
            )
        )

    regions.sort(key=lambda r: r.reading_order)

    logger.debug(
        "페이지 %d: %d개 영역 검출 (surya)", page_num, len(regions)
    )

    return PageLayout(page_num=page_num, width=width, height=height, regions=regions)


# ── 그림/표 추출 ─────────────────────────────────────────────


def extract_figures(
    image: np.ndarray, layout: PageLayout, config: OCRConfig
) -> PageLayout:
    """figure/table 영역을 크롭하여 이미지 파일로 저장한다"""
    config.images_dir.mkdir(parents=True, exist_ok=True)

    for region in layout.regions:
        if region.region_type not in ("figure", "table"):
            continue

        x1, y1, x2, y2 = region.bbox
        cropped = image[y1:y2, x1:x2]

        if cropped.size == 0:
            continue

        prefix = region.region_type  # "figure" or "table"
        filename = f"{prefix}_{layout.page_num:04d}_{region.id:03d}.png"
        save_path = config.images_dir / filename

        Image.fromarray(cropped).save(save_path)
        region.extracted_image = f"images/{filename}"

        logger.debug(
            "페이지 %d: %s 영역 %d 추출 → %s",
            layout.page_num,
            prefix,
            region.id,
            filename,
        )

    return layout


# ── 레이아웃 저장 ─────────────────────────────────────────────


def save_layout(layout: PageLayout, output_dir: Path):
    """레이아웃 정보를 JSON으로 저장한다"""
    data = {
        "page_num": layout.page_num,
        "width": layout.width,
        "height": layout.height,
        "regions": [
            {
                "id": r.id,
                "bbox": r.bbox,
                "type": r.region_type,
                "reading_order": r.reading_order,
                "confidence": r.confidence,
                **({"extracted_image": r.extracted_image} if r.extracted_image else {}),
            }
            for r in layout.regions
        ],
    }
    path = output_dir / f"page_{layout.page_num:04d}_layout.json"
    save_json(data, path)
