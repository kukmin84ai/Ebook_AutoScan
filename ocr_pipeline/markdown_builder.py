"""마크다운 문서 조립 — OCR 결과를 Markdown 책으로 변환"""

import logging
import re
from datetime import datetime
from pathlib import Path

from ocr_pipeline.config import OCRConfig
from ocr_pipeline.utils import load_json, save_json
from ocr_pipeline.postprocessor import aggregate_confidence

logger = logging.getLogger("ocr_pipeline")

# ── 페이지 마크다운 생성 ──────────────────────────────────────

_SENTENCE_END = re.compile(r"[.!?。…]\s*$")


def build_page_markdown(
    page_num: int, layout: dict, ocr_results: list[dict], config: OCRConfig
) -> str:
    """단일 페이지의 OCR/레이아웃 결과를 마크다운으로 조립한다"""
    regions = sorted(layout.get("regions", []), key=lambda r: r.get("reading_order", 0))
    lines: list[str] = []

    # OCR 결과를 region id로 매핑
    ocr_by_region: dict[int, dict] = {}
    for r in ocr_results:
        rid = r.get("region_id")
        if rid is not None:
            ocr_by_region[rid] = r

    # 매핑이 안 되면 순서대로 대응
    unmatched_ocr = [r for r in ocr_results if r.get("region_id") is None]
    unmatched_idx = 0

    figure_counter = 0
    table_counter = 0

    for region in regions:
        rtype = region.get("type", "text")
        rid = region.get("id")
        extracted_image = region.get("extracted_image")

        # OCR 텍스트 가져오기
        ocr = ocr_by_region.get(rid)
        if ocr is None and unmatched_idx < len(unmatched_ocr):
            ocr = unmatched_ocr[unmatched_idx]
            unmatched_idx += 1

        if rtype == "figure":
            figure_counter += 1
            if extracted_image:
                lines.append(f"![그림 {figure_counter}]({extracted_image})")
            elif ocr and ocr.get("text"):
                lines.append(f"![그림 {figure_counter}]")
            lines.append("")
            continue

        if rtype == "table":
            table_counter += 1
            if extracted_image:
                lines.append(f"![표 {table_counter}]({extracted_image})")
            elif ocr and ocr.get("text"):
                lines.append(f"![표 {table_counter}]")
            lines.append("")
            continue

        if rtype == "footer":
            # 각주는 작은 글씨 표시
            if ocr and ocr.get("text"):
                text = ocr["text"].strip()
                if text:
                    lines.append(f"<sub>{text}</sub>")
                    lines.append("")
            continue

        # text, header 처리
        if not ocr or not ocr.get("text"):
            continue

        text = ocr["text"].strip()
        if not text:
            continue

        confidence_level = ocr.get("confidence_level", "high")

        if confidence_level == "very_low":
            lines.append(f"<!-- 불확실: {text} -->")
            lines.append("")
            continue

        if confidence_level == "low":
            lines.append(f"<!-- 불확실: {text} -->")
            lines.append("")
            continue

        if rtype == "header":
            lines.append(f"## {text}")
        else:
            lines.append(text)

        lines.append("")

    # 페이지 구분 주석
    lines.append(f"<!-- page {page_num} -->")
    lines.append("")

    return "\n".join(lines)


# ── 교차 페이지 문단 병합 ─────────────────────────────────────


def merge_cross_page_paragraphs(pages_md: list[str]) -> str:
    """페이지 경계에서 잘린 문단을 병합한다"""
    if not pages_md:
        return ""

    if len(pages_md) == 1:
        return pages_md[0]

    merged_parts: list[str] = [pages_md[0]]

    for i in range(1, len(pages_md)):
        prev = merged_parts[-1]
        curr = pages_md[i]

        # 이전 페이지 끝에서 page 주석과 빈 줄 제거 후 마지막 텍스트 줄 확인
        prev_lines = prev.rstrip().split("\n")
        last_text_line = ""
        for line in reversed(prev_lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("<!--"):
                last_text_line = stripped
                break

        # 현재 페이지 첫 텍스트 줄 확인
        curr_lines = curr.lstrip().split("\n")
        first_text_line = ""
        for line in curr_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("<!--"):
                first_text_line = stripped
                break

        # 병합 조건: 이전 줄이 문장 끝이 아니고, 다음이 소문자/한글로 시작
        should_merge = (
            last_text_line
            and first_text_line
            and not _SENTENCE_END.search(last_text_line)
            and not first_text_line.startswith("#")
            and not first_text_line.startswith("![")
            and not first_text_line.startswith("<!--")
            and _starts_with_continuation(first_text_line)
        )

        if should_merge:
            # page 주석은 유지하되, 줄바꿈 대신 공백으로 연결
            merged_parts[-1] = prev.rstrip() + " " + curr.lstrip()
        else:
            merged_parts.append(curr)

    return "\n".join(merged_parts)


def _starts_with_continuation(line: str) -> bool:
    """문장 이어쓰기로 판단할 수 있는 시작인지 확인"""
    if not line:
        return False
    first_char = line[0]
    # 한글 음절, 소문자 영문 → 이어쓰기 가능
    if 0xAC00 <= ord(first_char) <= 0xD7A3:
        return True
    if first_char.islower():
        return True
    return False


# ── 메타데이터 ────────────────────────────────────────────────


def build_metadata(
    input_dir: Path, page_count: int, engine: str, stats: dict
) -> dict:
    """책 메타데이터 JSON을 생성한다"""
    return {
        "source_dir": str(input_dir),
        "page_count": page_count,
        "engine": engine,
        "mean_confidence": stats.get("mean_confidence", 0.0),
        "pages_needing_review": stats.get("pages_needing_review", []),
        "created_at": datetime.now().isoformat(),
        "ocr_pipeline_version": "0.1.0",
    }


# ── 전체 책 조립 ─────────────────────────────────────────────


def build_book(input_dir: Path, config: OCRConfig) -> Path:
    """모든 페이지 OCR/레이아웃 결과를 모아 book.md를 생성한다"""
    output_dir = config.output_dir

    # 레이아웃/OCR JSON 파일 수집
    layout_files = sorted(output_dir.glob("page_*_layout.json"))
    ocr_files = sorted(output_dir.glob("page_*_ocr.json"))

    if not layout_files and not ocr_files:
        logger.error("OCR 결과 파일이 없습니다: %s", output_dir)
        raise FileNotFoundError(f"OCR 결과 없음: {output_dir}")

    # 페이지 번호 매핑
    layouts: dict[int, dict] = {}
    for f in layout_files:
        data = load_json(f)
        layouts[data["page_num"]] = data

    ocr_data: dict[int, list[dict]] = {}
    for f in ocr_files:
        data = load_json(f)
        page_num = data.get("page_num", 0)
        ocr_data[page_num] = data.get("results", [])

    # 전체 페이지 번호 (합집합)
    all_pages = sorted(set(layouts.keys()) | set(ocr_data.keys()))

    if not all_pages:
        logger.error("처리할 페이지가 없습니다")
        raise ValueError("처리할 페이지 없음")

    # 페이지별 마크다운 생성
    pages_md: list[str] = []
    all_results: list[dict] = []
    pages_needing_review: list[int] = []

    for page_num in all_pages:
        layout = layouts.get(page_num, _default_layout(page_num))
        results = ocr_data.get(page_num, [])

        md = build_page_markdown(page_num, layout, results, config)
        pages_md.append(md)

        all_results.extend(results)

        # 리뷰 필요 페이지 수집
        if any(r.get("needs_review", False) for r in results):
            pages_needing_review.append(page_num)

    # 교차 페이지 문단 병합
    full_md = merge_cross_page_paragraphs(pages_md)

    # 전면 머릿말 추가
    book_name = input_dir.name
    page_count = len(all_pages)

    front_matter = (
        f"# {book_name}\n\n"
        f"- 페이지 수: {page_count}\n"
        f"- OCR 엔진: {config.engine}\n"
        f"- 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"---\n\n"
    )

    full_md = front_matter + full_md

    # book.md 저장
    book_path = output_dir / "book.md"
    book_path.write_text(full_md, encoding="utf-8")
    logger.info("book.md 저장 완료: %s", book_path)

    # 신뢰도 통계
    stats = aggregate_confidence(all_results)
    stats["pages_needing_review"] = pages_needing_review

    # 메타데이터 저장
    metadata = build_metadata(input_dir, page_count, config.engine, stats)
    save_json(metadata, output_dir / "book_metadata.json")
    logger.info("book_metadata.json 저장 완료")

    # 요약 출력
    print(f"\n{'='*50}")
    print(f"  책 변환 완료: {book_name}")
    print(f"{'='*50}")
    print(f"  총 페이지: {page_count}")
    print(f"  평균 신뢰도: {stats['mean_confidence']:.2%}")
    print(f"  높음: {stats['high_count']}  "
          f"보통: {stats['medium_count']}  "
          f"낮음: {stats['low_count']}  "
          f"매우낮음: {stats['very_low_count']}")
    if pages_needing_review:
        print(f"  검토 필요 페이지: {len(pages_needing_review)}개")
        if len(pages_needing_review) <= 10:
            print(f"    {pages_needing_review}")
    print(f"  출력: {book_path}")
    print(f"{'='*50}\n")

    return book_path


def _default_layout(page_num: int) -> dict:
    """레이아웃 파일이 없는 페이지용 기본 레이아웃"""
    return {
        "page_num": page_num,
        "width": 0,
        "height": 0,
        "regions": [
            {
                "id": 0,
                "bbox": [0, 0, 0, 0],
                "type": "text",
                "reading_order": 0,
                "confidence": 1.0,
            }
        ],
    }
