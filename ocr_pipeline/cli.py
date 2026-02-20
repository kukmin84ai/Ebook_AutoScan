"""CLI 파싱 및 파이프라인 오케스트레이션"""

import argparse
import sys
import time
from pathlib import Path

from tqdm import tqdm

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import setup_logging, get_page_files, load_image, get_page_number, save_json
from ocr_pipeline.checkpoint import (
    save_checkpoint,
    load_checkpoint,
    get_remaining_pages,
    CheckpointData,
)


def parse_args(argv: list[str] | None = None) -> OCRConfig:
    """CLI 인자 파싱 → OCRConfig 변환"""
    parser = argparse.ArgumentParser(
        description="OCR 파이프라인 — 캡쳐 이미지에서 한글 텍스트 추출"
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        type=Path,
        help="캡쳐 폴더 경로 (page_NNNN.png 파일이 있는 디렉토리)",
    )
    parser.add_argument(
        "--engine", "-e",
        default="paddle",
        choices=["paddle", "easyocr", "klocr"],
        help="OCR 엔진 (기본: paddle)",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        default=True,
        dest="gpu",
        help="GPU 사용 (기본값)",
    )
    parser.add_argument(
        "--no-gpu",
        action="store_false",
        dest="gpu",
        help="GPU 미사용",
    )
    parser.add_argument(
        "--layout",
        action="store_true",
        default=True,
        dest="layout",
        help="레이아웃 분석 사용 (기본값)",
    )
    parser.add_argument(
        "--no-layout",
        action="store_false",
        dest="layout",
        help="레이아웃 분석 미사용",
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        default=False,
        help="체크포인트에서 재개",
    )
    parser.add_argument(
        "--pages", "-p",
        default=None,
        help='페이지 범위 (예: "1-50")',
    )
    parser.add_argument(
        "--confidence", "-c",
        type=float,
        default=0.7,
        help="최소 신뢰도 임계값 (기본: 0.7)",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=4,
        help="배치 크기 (기본: 4)",
    )
    parser.add_argument(
        "--quality-check-only", "-q",
        action="store_true",
        default=False,
        help="품질 평가만 수행 (OCR 건너뜀)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="상세 로그 출력",
    )

    args = parser.parse_args(argv)

    # --pages "1-50" 파싱
    page_start = 1
    page_end = 0
    if args.pages:
        parts = args.pages.split("-")
        try:
            page_start = int(parts[0])
            if len(parts) >= 2:
                page_end = int(parts[1])
        except ValueError:
            parser.error(f"잘못된 페이지 범위: {args.pages} (예: '1-50')")

    return OCRConfig(
        input_dir=args.input.resolve(),
        engine=args.engine,
        use_gpu=args.gpu,
        use_layout=args.layout,
        page_start=page_start,
        page_end=page_end,
        batch_size=args.batch_size,
        confidence_threshold=args.confidence,
        resume=args.resume,
        quality_check_only=args.quality_check_only,
        verbose=args.verbose,
    )


def run_pipeline(config: OCRConfig):
    """메인 파이프라인 실행"""
    logger = setup_logging(config.verbose)
    config.ensure_dirs()

    # 1. 페이지 파일 수집
    page_files = get_page_files(config.input_dir, config.page_start, config.page_end)
    if not page_files:
        print("❌ 캡쳐 이미지를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"\n📚 OCR 파이프라인 시작")
    print(f"   입력: {config.input_dir}")
    print(f"   페이지: {len(page_files)}장")
    print(f"   엔진: {config.engine}")
    print(f"   GPU: {'사용' if config.use_gpu else '미사용'}")

    # 2. 품질 검사만 모드
    if config.quality_check_only:
        from ocr_pipeline.preprocessor import run_quality_check
        run_quality_check(page_files, config)
        return

    # 3. 체크포인트 확인
    checkpoint = None
    if config.resume:
        checkpoint = load_checkpoint(config)
        if checkpoint:
            page_files = get_remaining_pages(page_files, checkpoint)
            print(f"   ▶️  체크포인트에서 재개: {len(checkpoint.completed_pages)}페이지 완료됨")
        else:
            print("   ⚠️  체크포인트를 찾을 수 없습니다. 처음부터 시작합니다.")

    if not checkpoint:
        checkpoint = CheckpointData(total_pages=len(page_files), engine=config.engine)

    if not page_files:
        print("✅ 모든 페이지가 이미 처리되었습니다.")
        return

    # 4. OCR 엔진 초기화
    from ocr_pipeline.ocr_engine import create_engine, run_ocr
    engine = create_engine(config)

    # 5. 페이지별 처리
    from ocr_pipeline.preprocessor import assess_quality, preprocess
    from ocr_pipeline.layout_analyzer import analyze_layout, extract_figures, save_layout
    from ocr_pipeline.postprocessor import postprocess_page

    start_time = time.time()

    for i, page_file in enumerate(tqdm(page_files, desc="OCR 처리중")):
        page_num = get_page_number(page_file)
        try:
            # 5a. 이미지 로드
            image = load_image(page_file)

            # 5b. 품질 평가
            quality = assess_quality(image, config)
            if not quality.is_acceptable:
                logger.warning(f"페이지 {page_num}: 품질 불량 — {quality.warnings}")
                checkpoint.failed_pages.append(page_num)
                continue

            # 5c. 전처리
            processed = preprocess(image, config)

            # 5d. 레이아웃 분석
            layout = analyze_layout(processed, page_num, config)
            layout = extract_figures(image, layout, config)
            save_layout(layout, config.output_dir)

            # 5e. OCR
            regions = [
                {
                    "id": r.id,
                    "bbox": r.bbox,
                    "type": r.region_type,
                    "reading_order": r.reading_order,
                }
                for r in layout.regions
                if r.region_type in ("text", "header")
            ]
            ocr_result = run_ocr(engine, processed, page_num, regions, config)

            # 5f. 후처리 → 저장 (후처리된 결과를 JSON으로 저장)
            raw_dicts = [
                {
                    "region_id": r.region_id,
                    "text": r.text,
                    "confidence": r.confidence,
                    "reading_order": idx + 1,
                    "needs_review": r.needs_review,
                }
                for idx, r in enumerate(ocr_result.results)
            ]
            processed_results = postprocess_page(raw_dicts, config)
            save_json(
                {
                    "page_num": page_num,
                    "engine": ocr_result.engine,
                    "results": processed_results,
                },
                config.output_dir / f"page_{page_num:04d}_ocr.json",
            )

            # 5g. 체크포인트
            checkpoint.completed_pages.append(page_num)
            if (i + 1) % config.checkpoint_interval == 0:
                save_checkpoint(checkpoint, config)
                logger.debug(f"체크포인트 저장 ({len(checkpoint.completed_pages)}페이지 완료)")

        except Exception as e:
            logger.error(f"페이지 {page_num} 처리 실패: {e}")
            checkpoint.failed_pages.append(page_num)
            continue

    # 6. 최종 체크포인트
    save_checkpoint(checkpoint, config)

    # 7. 마크다운 조립
    print("\n📝 마크다운 문서 생성중...")
    from ocr_pipeline.markdown_builder import build_book
    md_path = build_book(config.input_dir, config)

    # 8. 결과 요약
    elapsed = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ OCR 완료!")
    print(f"   처리: {len(checkpoint.completed_pages)}페이지")
    print(f"   실패: {len(checkpoint.failed_pages)}페이지")
    print(f"   소요: {elapsed:.1f}초")
    print(f"   출력: {md_path}")
    print(f"{'='*50}")


def main(argv: list[str] | None = None):
    """CLI 진입점"""
    config = parse_args(argv)
    run_pipeline(config)
