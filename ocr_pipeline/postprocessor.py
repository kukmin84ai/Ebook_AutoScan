"""OCR 후처리 -한국어 자모 보정, 줄 병합, 신뢰도 분류"""

import logging
import re
import unicodedata

from ocr_pipeline.config import OCRConfig

logger = logging.getLogger("ocr_pipeline")

# ── 자모 오류 수정 ────────────────────────────────────────────

# Hangul Jamo 범위
_JAMO_INITIAL = range(0x1100, 0x1113)  # 초성
_JAMO_MEDIAL = range(0x1161, 0x1176)  # 중성
_JAMO_FINAL = range(0x11A8, 0x11C3)  # 종성

# Hangul Compatibility Jamo (OCR이 자주 출력하는 형태)
_COMPAT_CONSONANTS = range(0x3131, 0x314F)  # ㄱ-ㅎ
_COMPAT_VOWELS = range(0x314F, 0x3164)  # ㅏ-ㅣ


def _is_hangul_syllable(ch: str) -> bool:
    """완성형 한글 음절인지 확인"""
    return 0xAC00 <= ord(ch) <= 0xD7A3


def _is_isolated_jamo(ch: str) -> bool:
    """조합되지 않은 단독 자모인지 확인"""
    cp = ord(ch)
    return (
        cp in _COMPAT_CONSONANTS
        or cp in _COMPAT_VOWELS
        or cp in _JAMO_INITIAL
        or cp in _JAMO_MEDIAL
        or cp in _JAMO_FINAL
    )


def fix_jamo_errors(text: str) -> str:
    """한국어 자모 OCR 오류를 수정한다"""
    if not text:
        return text

    # 한글 채움 문자(ㅤ, U+3164) → 공백
    text = text.replace("\u3164", " ")

    # 가운뎃점 변환 (ㆍ → ·)
    text = text.replace("\u318D", "\u00B7")

    # 중복 공백 정리
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 연속 자모 시퀀스를 완성형으로 조합 시도
    text = _try_compose_jamo(text)

    return text.strip()


# 호환 자모 → 조합용 자모 매핑 (초성)
_COMPAT_TO_INITIAL = {
    0x3131: 0, 0x3132: 1, 0x3134: 2, 0x3137: 3, 0x3138: 4,
    0x3139: 5, 0x3141: 6, 0x3142: 7, 0x3143: 8, 0x3145: 9,
    0x3146: 10, 0x3147: 11, 0x3148: 12, 0x3149: 13, 0x314A: 14,
    0x314B: 15, 0x314C: 16, 0x314D: 17, 0x314E: 18,
}

# 호환 자모 → 조합용 자모 매핑 (중성)
_COMPAT_TO_MEDIAL = {
    0x314F: 0, 0x3150: 1, 0x3151: 2, 0x3152: 3, 0x3153: 4,
    0x3154: 5, 0x3155: 6, 0x3156: 7, 0x3157: 8, 0x3158: 9,
    0x3159: 10, 0x315A: 11, 0x315B: 12, 0x315C: 13, 0x315D: 14,
    0x315E: 15, 0x315F: 16, 0x3160: 17, 0x3161: 18, 0x3162: 19,
    0x3163: 20,
}

# 호환 자모 → 종성 인덱스 (0 = 종성 없음이므로 +1)
_COMPAT_TO_FINAL = {
    0x3131: 1, 0x3132: 2, 0x3134: 4, 0x3137: 7, 0x3139: 8,
    0x3141: 16, 0x3142: 17, 0x3145: 19, 0x3146: 20, 0x3147: 21,
    0x3148: 22, 0x314A: 23, 0x314B: 24, 0x314C: 25, 0x314D: 26,
    0x314E: 27,
}


def _try_compose_jamo(text: str) -> str:
    """호환 자모 시퀀스를 완성형 한글로 조합 시도"""
    result = []
    i = 0
    n = len(text)

    while i < n:
        cp = ord(text[i])

        # 초성 후보
        if cp in _COMPAT_TO_INITIAL and i + 1 < n:
            cp_next = ord(text[i + 1])
            # 다음이 중성이면 조합 시도
            if cp_next in _COMPAT_TO_MEDIAL:
                initial = _COMPAT_TO_INITIAL[cp]
                medial = _COMPAT_TO_MEDIAL[cp_next]
                final = 0

                # 종성 확인
                if i + 2 < n:
                    cp_final = ord(text[i + 2])
                    if cp_final in _COMPAT_TO_FINAL:
                        # 종성 뒤에 중성이 오면 종성이 아니라 다음 음절의 초성
                        if i + 3 < n and ord(text[i + 3]) in _COMPAT_TO_MEDIAL:
                            pass  # final 유지 = 0
                        else:
                            final = _COMPAT_TO_FINAL[cp_final]
                            i += 1  # 종성 소비

                syllable = chr(0xAC00 + initial * 21 * 28 + medial * 28 + final)
                result.append(syllable)
                i += 2  # 초성 + 중성 소비
                continue

        result.append(text[i])
        i += 1

    return "".join(result)


# ── 줄 병합 ──────────────────────────────────────────────────

_SENTENCE_END = re.compile(r"[.!?。…]\s*$")
_BULLET_START = re.compile(r"^[\s]*[-•▪▸►●○◆◇※☞·\d]+[.)]\s")


def merge_lines(text: str) -> str:
    """문장 중간에서 잘린 줄을 병합한다"""
    if not text:
        return text

    paragraphs = text.split("\n\n")
    merged_paragraphs = []

    for para in paragraphs:
        lines = para.split("\n")
        if len(lines) <= 1:
            merged_paragraphs.append(para)
            continue

        merged = [lines[0]]
        for line in lines[1:]:
            prev = merged[-1]
            stripped = line.strip()

            if not stripped:
                continue

            # 이전 줄이 문장 끝이 아니고, 다음 줄이 목록이 아닌 경우 → 병합
            if (
                not _SENTENCE_END.search(prev)
                and not _BULLET_START.match(line)
                and not stripped[0].isupper()  # 영문 대문자 시작 = 새 문장 가능
            ):
                merged[-1] = prev.rstrip() + " " + stripped
            else:
                merged.append(line)

        merged_paragraphs.append("\n".join(merged))

    return "\n\n".join(merged_paragraphs)


# ── 신뢰도 분류 ──────────────────────────────────────────────


def classify_confidence(confidence: float, threshold: float = 0.7) -> str:
    """OCR 신뢰도를 등급으로 분류한다"""
    if confidence >= 0.85:
        return "high"
    if confidence >= threshold:
        return "medium"
    if confidence >= 0.5:
        return "low"
    return "very_low"


# ── 페이지 후처리 ─────────────────────────────────────────────


def postprocess_page(ocr_results: list[dict], config: OCRConfig) -> list[dict]:
    """페이지 OCR 결과에 자모 보정, 줄 병합, 신뢰도 분류를 적용한다"""
    processed = []

    for result in ocr_results:
        r = dict(result)  # 원본 보존

        text = r.get("text", "")
        confidence = r.get("confidence", 0.0)

        # 신뢰도 분류
        level = classify_confidence(confidence, config.confidence_threshold)
        r["confidence_level"] = level

        if confidence < 0.5:
            r["text"] = "[이미지: 텍스트 불명확]"
            r["needs_review"] = True
        else:
            # 텍스트 후처리
            text = fix_jamo_errors(text)
            text = merge_lines(text)
            r["text"] = text
            r["needs_review"] = confidence < 0.85

        processed.append(r)

    return processed


# ── 신뢰도 통계 ──────────────────────────────────────────────


def aggregate_confidence(results: list[dict]) -> dict:
    """페이지 OCR 결과의 신뢰도 통계를 산출한다"""
    if not results:
        return {
            "mean_confidence": 0.0,
            "min_confidence": 0.0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "very_low_count": 0,
            "needs_review": False,
        }

    confidences = [r.get("confidence", 0.0) for r in results]
    levels = [r.get("confidence_level", classify_confidence(c)) for r, c in zip(results, confidences)]

    return {
        "mean_confidence": round(sum(confidences) / len(confidences), 4),
        "min_confidence": round(min(confidences), 4),
        "high_count": levels.count("high"),
        "medium_count": levels.count("medium"),
        "low_count": levels.count("low"),
        "very_low_count": levels.count("very_low"),
        "needs_review": any(r.get("needs_review", False) for r in results),
    }
