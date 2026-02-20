"""공통 유틸리티 — 로깅, 파일 I/O"""

import json
import logging
import sys
from pathlib import Path

from PIL import Image
import numpy as np


def setup_logging(verbose: bool = False) -> logging.Logger:
    """로깅 설정"""
    logger = logging.getLogger("ocr_pipeline")
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    return logger


def get_page_files(input_dir: Path, page_start: int = 1, page_end: int = 0) -> list[Path]:
    """캡쳐 폴더에서 page_NNNN.png 파일 목록 반환 (정렬됨)"""
    files = sorted(input_dir.glob("page_*.png"))
    if not files:
        return []

    result = []
    for f in files:
        try:
            num = int(f.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if num < page_start:
            continue
        if page_end > 0 and num > page_end:
            continue
        result.append(f)

    return result


def get_page_number(path: Path) -> int:
    """파일 경로에서 페이지 번호 추출"""
    return int(path.stem.split("_")[1])


def load_image(path: Path) -> np.ndarray:
    """이미지 로드 → numpy uint8 HxWx3"""
    img = Image.open(path).convert("RGB")
    return np.array(img, dtype=np.uint8)


def save_json(data: dict, path: Path):
    """JSON 파일 저장"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict:
    """JSON 파일 로드"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
