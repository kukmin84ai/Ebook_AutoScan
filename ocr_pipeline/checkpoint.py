"""체크포인트 — 대용량 책 처리 시 중단/재개 지원"""

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import setup_logging, get_page_number


@dataclass
class CheckpointData:
    """체크포인트 상태"""
    completed_pages: list[int] = field(default_factory=list)
    failed_pages: list[int] = field(default_factory=list)
    total_pages: int = 0
    engine: str = "paddle"
    last_updated: str = ""
    config_hash: str = ""  # detect config changes


def save_checkpoint(data: CheckpointData, config: OCRConfig):
    """체크포인트 저장 (백업 포함)"""
    logger = setup_logging(config.verbose)
    cp_path = config.checkpoint_path
    backup_path = cp_path.with_suffix(".json.bak")

    # 기존 파일이 있으면 백업 생성
    if cp_path.exists():
        try:
            shutil.copy2(cp_path, backup_path)
        except OSError as e:
            logger.warning(f"체크포인트 백업 실패: {e}")

    # 타임스탬프 갱신
    data.last_updated = datetime.now().isoformat()

    # JSON 저장
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(asdict(data), f, ensure_ascii=False, indent=2)

    logger.debug(f"체크포인트 저장: {len(data.completed_pages)}페이지 완료")


def load_checkpoint(config: OCRConfig) -> CheckpointData | None:
    """체크포인트 로드. 없으면 None 반환"""
    logger = setup_logging(config.verbose)
    cp_path = config.checkpoint_path
    backup_path = cp_path.with_suffix(".json.bak")

    for path in [cp_path, backup_path]:
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cp = CheckpointData(**{
                k: v for k, v in raw.items()
                if k in CheckpointData.__dataclass_fields__
            })
            if path == backup_path:
                logger.warning("백업 체크포인트에서 복구됨")
            return cp
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"체크포인트 로드 실패 ({path.name}): {e}")
            continue

    return None


def get_remaining_pages(all_pages: list[Path], checkpoint: CheckpointData | None) -> list[Path]:
    """완료된 페이지를 제외한 나머지 반환"""
    if checkpoint is None:
        return all_pages

    completed = set(checkpoint.completed_pages)
    return [p for p in all_pages if get_page_number(p) not in completed]
