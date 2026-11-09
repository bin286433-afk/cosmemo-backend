"""
코스메모 영수증 OCR 엔진 (REG-02 ~ REG-05, STATE-03, STATE-04)

처리 흐름
  1) prepare_image()      : 이미지 검증 · EXIF 회전 보정 · RGB 변환 · 긴 변 2048px 축소 · JPEG 재인코딩
  2) recognize_receipt()  : 엔진을 순서대로 시도
       ① Gemini Vision (GEMINI_API_KEY 설정 시)  — 구조화(JSON Schema) 출력
       ② 로컬 Tesseract OCR (pytesseract + kor 언어팩 설치 시) → 규칙 기반 파서
       ③ 클라이언트가 보낸 OCR 텍스트(raw_ocr_text) → 규칙 기반 파서
       ④ 모두 실패하면 OcrOutcome(ok=False) — 절대로 샘플 영수증을 대신 돌려주지 않음
  3) parse_receipt_text_rules() : 한국어 영수증 텍스트 → 매장/구매일/품목/합계/할인
  4) finalize_items()           : 브랜드 분리 · 비화장품 제외 · 카테고리 추정 · 카탈로그 유사도 매칭
  5) 검증                       : 품목 합계 vs 인쇄된 합계 비교, 단가/줄금액 해석 자동 보정, 신뢰도·경고 산출

[원본 대비 주요 수정]
 - 키가 없을 때 '어떤 이미지든' 기본 샘플 영수증 결과를 반환하던 문제 제거
 - 서비스 종료된 gemini-1.5-flash → 설정값(GEMINI_MODEL) 사용, API 키를 URL 대신 헤더로 전송
 - 예외를 조용히 삼키던 부분 → 원인별 오류 코드/로그 남김
 - "단가 수량 금액" / 두 줄 품목 / 바코드 줄 / 할인 줄 / 한글·2자리 연도 날짜 지원
 - 수량 2개 품목에서 금액이 2배로 잡히던 문제(줄 금액을 단가로 오인) 수정
 - 브랜드가 달라도 '세럼' 같은 단어 하나로 매칭되던 오매칭 → 점수 기반 매칭 + 브랜드 일치 검사
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.models import CatalogProduct

logger = logging.getLogger("cosmemo.ocr")

# ---------------------------------------------------------------------------
# 사전 / 키워드
# ---------------------------------------------------------------------------
NON_COSMETIC_KEYWORDS = [
    "화장솜", "면봉", "물티슈", "쇼핑백", "종량제", "비닐", "봉투", "과자", "음료", "생수",
    "퍼프", "브러시", "브러쉬", "거울", "뷰러", "머리끈", "손톱깎이", "파우치", "우산", "양말",
    "젤리", "커피", "충전", "케이블", "포장비", "배송비", "보조배터리", "스펀지", "헤어핀",
]

KNOWN_BRANDS = [
    "라운드리프", "모닝듀", "누드블룸", "메종드보", "데일리선", "그린더마", "퓨어포레",
    "라운드랩", "토리든", "아누아", "닥터지", "이니스프리", "에스트라", "롬앤", "클리오",
    "마녀공장", "달바", "설화수", "라네즈", "헤라", "에뛰드", "페리페라", "아이소이", "닥터자르트",
    "코스알엑스", "구달", "넘버즈인", "바이오더마", "라로슈포제", "아벤느", "미샤", "토니모리",
]

STORE_HINTS = ["올리브영", "시코르", "세포라", "롭스", "랄라블라", "아리따움", "다이소", "스토어", "매장", "점"]

# 이 단어가 들어간 줄은 품목이 아님 (공백 제거 후 비교)
IGNORE_KEYWORDS = [
    "사업자", "대표", "전화", "tel", "주소", "카드", "승인", "결제", "부가세", "부가가치세", "과세", "면세",
    "vat", "포인트", "회원", "거스름", "받은금액", "현금", "일시불", "할부", "가맹점", "pos", "영수증",
    "교환", "환불", "감사합니다", "상품명", "단가", "수량", "금액", "no.", "계산원", "캐셔", "주문번호",
]
TOTAL_KEYWORDS = ["합계", "총액", "총합계", "결제금액", "판매금액", "받을금액", "총구매액", "청구금액", "총금액"]
DISCOUNT_KEYWORDS = ["할인", "쿠폰", "에누리", "프로모션", "멤버십"]

COLOR_KEYWORDS = ["틴트", "립스틱", "립글로스", "립 ", "쿠션", "파운데이션", "섀도", "쉐도우", "섀도우", "블러셔",
                  "마스카라", "아이라이너", "라이너", "컨실러", "프라이머", "하이라이터", "브로우", "팩트", "파우더", "글리터"]
PERFUME_KEYWORDS = ["향수", "퍼퓸", "오드퍼퓸", "오드뚜왈렛", "오드토일렛", "코롱", "edp", "edt", "바디미스트"]

AMOUNT_TOKEN = re.compile(r"^[-−]?(?:₩)?(?:\d{1,3}(?:,\d{3})+|\d{2,8})(?:원)?$")
QTY_TOKEN = re.compile(r"^(?:[xX×*])?(\d{1,2})(?:개|ea|EA|Ea|입|매|pcs)?$")
BARCODE_TOKEN = re.compile(r"^\d{8,14}$")
LEADING_INDEX = re.compile(r"^(?:\[?\d{1,3}[\].)]\s*|\d{1,3}\s+(?=\D))")
INLINE_QTY = re.compile(r"(?:[xX×*]\s?(\d{1,2})|(\d{1,2})\s?(?:개|EA|ea))\s*$")


# ---------------------------------------------------------------------------
# 결과 객체
# ---------------------------------------------------------------------------
@dataclass
class OcrOutcome:
    ok: bool
    engine: str
    data: Optional[Dict[str, Any]] = None
    raw_text: Optional[str] = None
    error_code: Optional[str] = None      # invalid_image | no_engine | unreadable | api_error
    message: Optional[str] = None
    attempts: List[Dict[str, str]] = field(default_factory=list)


class InvalidImageError(ValueError):
    pass


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------
def normalize_text(raw: str) -> str:
    """전각 문자·특수 공백·기호 통일 (OCR 결과에 흔한 '１８，０００' 같은 문자 정리)."""
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace("￦", "₩").replace(" ", " ").replace("\t", " ")
    text = re.sub(r"[‐‑‒–—―−]", "-", text)
    return "\n".join(re.sub(r"\s{2,}", " ", ln).strip() for ln in text.splitlines())


def to_int(value: Any, default: Optional[int] = 0) -> Optional[int]:
    """'18,000원', '₩18000', 18000.0, None 등을 안전하게 정수로."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip().replace(",", "").replace("원", "").replace("₩", "").replace(" ", "")
    s = s.replace("−", "-")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return default
    return int(round(float(m.group(0))))


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _clean_product_name(s: str) -> str:
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" ·-_[](){}*#:/")


def _norm_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\d+(?:\.\d+)?\s*(?:ml|mL|g|매|개입|oz)", "", s)       # 용량 표기 제거
    s = re.sub(r"(기획|증정|단품|리필|대용량|1\+1|special|set)", "", s)  # 프로모션 문구 제거
    return re.sub(r"[^0-9a-z가-힣]", "", s)


# ---------------------------------------------------------------------------
# 분류
# ---------------------------------------------------------------------------
def is_cosmetic_item(item_name: str) -> bool:
    return not any(kw in (item_name or "") for kw in NON_COSMETIC_KEYWORDS)


def guess_category(item_name: str) -> str:
    name = (item_name or "").lower() + " "
    if "립밤" in name or "립케어" in name:
        return "스킨케어"
    if any(k in name for k in PERFUME_KEYWORDS):
        return "향수"
    if any(k in name for k in COLOR_KEYWORDS):
        return "색조"
    return "스킨케어"


def _brand_list(catalogs: Sequence[CatalogProduct]) -> List[str]:
    brands = set(KNOWN_BRANDS) | {c.brand for c in catalogs if c.brand}
    return sorted(brands, key=len, reverse=True)  # 긴 이름 먼저 (라운드리프 vs 라운드랩 오인 방지)


def split_brand(title: str, brands: Sequence[str]) -> Tuple[Optional[str], str]:
    """'[토리든]다이브인 세럼', '토리든 다이브인 세럼' → ('토리든', '다이브인 세럼')"""
    m = re.match(r"^\s*[\[(<]([^\])>]{1,20})[\])>]\s*(.+)$", title)
    if m:
        cand = m.group(1).strip()
        for b in brands:
            if b == cand or b in cand:
                return b, _clean_product_name(m.group(2))
        return cand, _clean_product_name(m.group(2))
    for b in brands:
        if b in title:
            return b, _clean_product_name(title.replace(b, " ", 1))
    return None, _clean_product_name(title)


# ---------------------------------------------------------------------------
# 카탈로그 매칭
# ---------------------------------------------------------------------------
def score_catalog(catalog: CatalogProduct, brand: Optional[str], name: str) -> float:
    target, cat_name = _norm_for_match(name), _norm_for_match(catalog.name)
    if not target or not cat_name:
        return 0.0
    score = SequenceMatcher(None, target, cat_name).ratio()
    shorter = min(len(target), len(cat_name))
    if shorter >= 4 and (target in cat_name or cat_name in target):
        score = max(score, 0.9)
    if brand:
        b1, b2 = _squash(brand), _squash(catalog.brand or "")
        if b1 and b2 and not (b1 in b2 or b2 in b1):
            return 0.0                        # 브랜드가 확실히 다르면 매칭하지 않음
        score = min(1.0, score + 0.08)
    else:
        score -= 0.1                          # 브랜드를 모르면 더 엄격하게
    return round(max(score, 0.0), 3)


def best_catalog_match(
    catalogs: Sequence[CatalogProduct], brand: Optional[str], name: str
) -> Tuple[Optional[CatalogProduct], float]:
    best, best_score = None, 0.0
    for cat in catalogs:
        s = score_catalog(cat, brand, name)
        if s > best_score:
            best, best_score = cat, s
    if best is not None and best_score >= settings.CATALOG_MATCH_THRESHOLD:
        return best, best_score
    return None, best_score


def match_catalog_product(db: Session, brand: Optional[str], parsed_name: str) -> Optional[CatalogProduct]:
    """(하위 호환) 단일 품목 매칭"""
    cat, _ = best_catalog_match(db.query(CatalogProduct).all(), brand, parsed_name)
    return cat


def rank_catalog_candidates(db: Session, brand: Optional[str], name: str, limit: int = 5) -> List[Tuple[CatalogProduct, float]]:
    scored = [(c, score_catalog(c, brand, name)) for c in db.query(CatalogProduct).all()]
    return [x for x in sorted(scored, key=lambda x: x[1], reverse=True) if x[1] > 0.3][:limit]


# ---------------------------------------------------------------------------
# 날짜 / 매장 / 합계
# ---------------------------------------------------------------------------
_DATE_PATTERNS = [
    re.compile(r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})"),
    re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?"),
    re.compile(r"(?<![\d,])(\d{2})[./-](\d{1,2})[./-](\d{1,2})(?![\d,])"),  # 26.11.02
]


def _ocr_today() -> date:
    # 영수증 날짜 검증은 '시연 기준일'이 아니라 실제 달력 기준 (기준일 이후 영수증도 받아야 함)
    return max(settings.reference_today(), date.today())


def extract_date(line: str, today: Optional[date] = None) -> Optional[date]:
    today = today or date.today()
    for idx, pat in enumerate(_DATE_PATTERNS):
        for m in pat.finditer(line):
            y, mo, d = (int(g) for g in m.groups())
            if idx == 2:
                y += 2000
            try:
                dt = date(y, mo, d)
            except ValueError:
                continue
            # 미래 날짜·너무 오래된 날짜는 OCR 오인식일 가능성이 큼
            if date(2015, 1, 1) <= dt <= today + timedelta(days=1):
                return dt
    return None


def _is_ignored(line: str) -> bool:
    sq = _squash(line)
    return any(k in sq for k in IGNORE_KEYWORDS)


def _line_amounts(line: str) -> List[int]:
    return [to_int(t) for t in line.split() if AMOUNT_TOKEN.match(t)]


# ---------------------------------------------------------------------------
# 품목 줄 해석
# ---------------------------------------------------------------------------
def _split_trailing_numbers(tokens: List[str]) -> Tuple[List[str], List[Tuple[str, str]]]:
    """끝에서부터 숫자 토큰(금액/수량)을 최대 3개 떼어냄. [('qty','2'), ('amt','18,000')] 형태."""
    nums: List[Tuple[str, str]] = []
    rest = list(tokens)
    while rest and len(nums) < 3:
        t = rest[-1]
        if AMOUNT_TOKEN.match(t) and (("," in t) or len(re.sub(r"\D", "", t)) >= 3):
            nums.insert(0, ("amt", t))
        elif QTY_TOKEN.match(t):
            nums.insert(0, ("qty", t))
        else:
            break
        rest.pop()
    return rest, nums


def _interpret_numbers(nums: List[Tuple[str, str]]) -> Optional[Tuple[int, int, int, bool]]:
    """숫자 토큰 → (수량, 단가, 줄금액, 모호여부). 해석 불가 시 None.
    모호여부=True: 금액이 1개뿐이고 수량>1 이라 그 금액이 '줄금액'인지 '단가'인지 확정할 수 없음
    → finalize_result()에서 인쇄된 합계와 비교해 최종 결정."""
    vals = [(k, to_int(v)) for k, v in nums]
    amts = [v for k, v in vals if k == "amt"]
    qtys = [v for k, v in vals if k == "qty"]
    if not amts:
        return None
    if len(amts) >= 2:
        unit, total = amts[-2], amts[-1]
        qty = qtys[0] if qtys else (total // unit if unit and total % unit == 0 else 1)
        if unit * qty == total:
            return qty, unit, total, False
        if qty and total % qty == 0:              # 단가 표기가 틀린 경우 줄금액 우선
            return qty, total // qty, total, False
        return 1, total, total, False
    total = amts[-1]
    qty = qtys[-1] if qtys else 1
    qty = qty if 1 <= qty <= 99 else 1
    # 한국 POS 영수증의 '상품명 수량 금액'에서 금액은 보통 줄금액(단가×수량)
    unit = total // qty if total % qty == 0 else round(total / qty)
    return qty, unit, total, qty > 1


def _parse_item_line(line: str) -> Optional[Dict[str, Any]]:
    tokens = [t for t in line.split() if not BARCODE_TOKEN.match(t)]
    rest, nums = _split_trailing_numbers(tokens)
    if not nums:
        return None
    interp = _interpret_numbers(nums)
    if not interp:
        return None
    name = LEADING_INDEX.sub("", " ".join(rest)).strip()
    qty, unit, total, ambiguous = interp
    m = INLINE_QTY.search(name)                     # '토너 x2 30,000' 형태
    if m and qty == 1:
        q = int(m.group(1) or m.group(2))
        if 1 < q <= 99:
            qty, unit, ambiguous = q, (total // q if total % q == 0 else round(total / q)), True
            name = name[: m.start()].strip()
    if len(re.sub(r"[^가-힣a-zA-Z]", "", name)) < 2:
        return None
    return {"title": name, "quantity": qty, "unit_price": unit, "line_total": total, "ambiguous": ambiguous}


def parse_receipt_text_rules(
    raw_text: str,
    db: Optional[Session] = None,
    today: Optional[date] = None,
    catalogs: Optional[Sequence[CatalogProduct]] = None,
) -> Dict[str, Any]:
    """규칙 기반 한국어 영수증 텍스트 파서. 품목이 하나도 없으면 items=[] 를 반환합니다."""
    today = today or _ocr_today()
    text = normalize_text(raw_text)
    lines = [ln for ln in text.splitlines() if ln.strip()]

    store_name: Optional[str] = None
    purchase_date: Optional[date] = None
    printed_total: Optional[int] = None
    discount_total = 0
    raw_items: List[Dict[str, Any]] = []
    pending_name: Optional[str] = None

    for idx, line in enumerate(lines):
        sq = _squash(line)

        found_date = extract_date(line, today)
        if found_date:
            purchase_date = purchase_date or found_date
            continue

        if any(k in sq for k in TOTAL_KEYWORDS) and not any(k in sq for k in DISCOUNT_KEYWORDS):
            amts = [a for a in _line_amounts(line) if a and a > 0]
            if amts:
                printed_total = max(printed_total or 0, max(amts))
            continue

        if any(k in sq for k in DISCOUNT_KEYWORDS):
            amts = _line_amounts(line)
            if amts:
                discount_total += abs(amts[-1])
            continue

        if BARCODE_TOKEN.match(line.replace(" ", "")):
            continue  # 바코드만 있는 줄 (pending_name 은 유지)

        if store_name is None and idx <= 2 and not _line_amounts(line) and not _is_ignored(line):
            if any(h in line for h in STORE_HINTS) or idx == 0:
                store_name = re.sub(r"\[.*?\]", "", line).replace("매장명", "").replace(":", "").strip()[:50] or None
                continue

        if _is_ignored(line):
            pending_name = None
            continue

        item = _parse_item_line(line)
        if item is None and pending_name:
            # 두 줄 형식: 윗줄=상품명, 아랫줄='18,000 2 36,000' 처럼 숫자만
            only_nums = all(AMOUNT_TOKEN.match(t) or QTY_TOKEN.match(t) or BARCODE_TOKEN.match(t) for t in line.split())
            if only_nums:
                item = _parse_item_line(f"{pending_name} {line}")
        if item:
            item["raw_name"] = line if not pending_name or pending_name in line else f"{pending_name} / {line}"
            raw_items.append(item)
            pending_name = None
            continue

        # 금액 없는 한글 줄 → 다음 줄과 합쳐질 수 있는 상품명 후보
        if re.search(r"[가-힣]{2,}", line) and not re.search(r"\d{3,}", line):
            pending_name = LEADING_INDEX.sub("", line).strip()

    result = {
        "engine": "rule-based-parser",
        "store_name": store_name,
        "purchase_date": purchase_date.isoformat() if purchase_date else None,
        "printed_total": printed_total,
        "discount_total": discount_total or None,
        "items": [],
        "warnings": [],
    }
    return finalize_result(result, raw_items, db=db, catalogs=catalogs)


# ---------------------------------------------------------------------------
# 품목 후처리 + 검증 (규칙 파서와 Gemini 공통)
# ---------------------------------------------------------------------------
def finalize_items(
    raw_items: List[Dict[str, Any]],
    catalogs: Sequence[CatalogProduct],
) -> List[Dict[str, Any]]:
    brands = _brand_list(catalogs)
    out: List[Dict[str, Any]] = []
    for it in raw_items:
        title = _clean_product_name(str(it.get("title") or it.get("parsed_name") or it.get("raw_name") or ""))
        if not title:
            continue
        given_brand = (it.get("brand") or "").strip() or None
        if given_brand:
            brand, name = given_brand, _clean_product_name(title.replace(given_brand, " ", 1)) or title
        else:
            brand, name = split_brand(title, brands)

        cosmetic = is_cosmetic_item(title) and it.get("is_cosmetic", True) is not False
        qty = max(1, min(99, to_int(it.get("quantity"), 1) or 1))
        unit = to_int(it.get("unit_price"), None)
        total = to_int(it.get("line_total"), None)
        if unit is None and total is not None:
            unit = total // qty if total % qty == 0 else round(total / qty)
        unit = max(0, unit or 0)
        total = total if total is not None else unit * qty

        matched, score = (best_catalog_match(catalogs, brand, name) if cosmetic else (None, 0.0))
        if matched:
            brand = brand or matched.brand
            category = matched.category
        else:
            category = guess_category(name) if cosmetic else "소품"

        out.append({
            "raw_name": str(it.get("raw_name") or title)[:200],
            "brand": brand,
            "parsed_name": name if cosmetic else f"{name} · 화장품 외 상품",
            "category": category,
            "quantity": qty,
            "unit_price": unit,
            "line_total": total,
            "is_cosmetic": cosmetic,
            "is_selected": cosmetic,
            "matched_catalog_code": matched.code if matched else None,
            "match_score": score if matched else None,
            "_ambiguous": bool(it.get("ambiguous")),
        })
    return out


def finalize_result(
    result: Dict[str, Any],
    raw_items: List[Dict[str, Any]],
    db: Optional[Session] = None,
    catalogs: Optional[Sequence[CatalogProduct]] = None,
) -> Dict[str, Any]:
    if catalogs is None:
        catalogs = db.query(CatalogProduct).all() if db is not None else []
    items = finalize_items(raw_items, catalogs)
    warnings: List[str] = list(result.get("warnings") or [])
    printed = to_int(result.get("printed_total"), None)
    discount = to_int(result.get("discount_total"), None) or 0

    computed = sum(i["line_total"] for i in items) - discount
    if printed and items and computed != printed:
        # 해석 보정: '금액'이 줄금액이 아니라 단가였던 영수증 (예: 수량 2, 금액 18,000 → 실제 36,000)
        alt = sum(i["line_total"] * i["quantity"] if i["_ambiguous"] else i["line_total"] for i in items) - discount
        if any(i["_ambiguous"] for i in items) and alt == printed:
            for i in items:
                if i["_ambiguous"]:
                    i["unit_price"], i["line_total"] = i["line_total"], i["line_total"] * i["quantity"]
            computed = alt
        else:
            warnings.append(f"영수증 합계({printed:,}원)와 인식한 품목 합({computed:,}원)이 달라요. 금액을 확인해 주세요.")
    if not result.get("purchase_date"):
        warnings.append("구매일을 찾지 못했어요. 날짜를 직접 입력해 주세요.")
    missing_brand = sum(1 for i in items if i["is_cosmetic"] and not i["brand"])
    if missing_brand:
        warnings.append(f"브랜드를 확인하지 못한 품목이 {missing_brand}개 있어요.")
    unmatched = sum(1 for i in items if i["is_cosmetic"] and not i["matched_catalog_code"])
    if unmatched:
        warnings.append(f"카탈로그와 연결되지 않은 품목이 {unmatched}개 있어요. 용량·성분·PAO를 직접 확인해 주세요.")

    confidence = 1.0
    if not result.get("purchase_date"):
        confidence -= 0.2
    if not printed:
        confidence -= 0.1
    elif computed != printed:
        confidence -= 0.25
    confidence -= min(0.3, 0.1 * missing_brand)
    if not result.get("store_name"):
        confidence -= 0.05

    for i in items:
        i.pop("_ambiguous", None)
    result.update({
        "items": items,
        "total_amount": printed if printed else computed,
        "computed_total": computed,
        "printed_total": printed,
        "discount_total": discount or None,
        "warnings": warnings,
        "confidence": round(max(0.0, min(1.0, confidence)), 2) if items else 0.0,
    })
    return result


# ---------------------------------------------------------------------------
# 이미지 전처리
# ---------------------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}


def prepare_image(image_bytes: bytes, max_side: int = 2048) -> Tuple[bytes, str]:
    """이미지 검증 + EXIF 회전 보정 + 축소. 손상/비이미지 파일이면 InvalidImageError."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:  # HEIC(아이폰 기본 포맷)는 pillow-heif 가 설치된 경우에만 지원
        import pillow_heif  # type: ignore
        pillow_heif.register_heif_opener()
    except Exception:
        pass

    try:
        probe = Image.open(io.BytesIO(image_bytes))
        probe.verify()
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except UnidentifiedImageError as e:
        raise InvalidImageError("이미지 파일을 열 수 없어요. JPG·PNG·WEBP 사진을 올려 주세요. (HEIC는 JPG로 변환해 주세요)") from e
    except Exception as e:
        raise InvalidImageError("손상되었거나 지원하지 않는 이미지예요.") from e

    if min(img.size) < 200:
        raise InvalidImageError("이미지 해상도가 너무 낮아요. 영수증이 화면에 가득 차도록 다시 찍어 주세요.")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue(), "image/jpeg"


# ---------------------------------------------------------------------------
# 엔진 ① Gemini Vision
# ---------------------------------------------------------------------------
GEMINI_PROMPT = """너는 한국 화장품 매장 영수증을 읽는 OCR 도우미야.
이미지에 '인쇄된 글자'만 근거로 아래 JSON을 채워. 보이지 않거나 확실하지 않은 값은 추측하지 말고 null로 둬.
- raw_text: 영수증 전체 글자를 위에서 아래로 줄바꿈 포함 그대로 옮겨 적기
- store_name: 매장/지점명 (예: "올리브영 강남점")
- purchase_date: 거래일 YYYY-MM-DD
- printed_total: 영수증에 인쇄된 최종 합계(결제) 금액, 정수
- discount_total: 할인/쿠폰 금액의 합(양수), 없으면 0
- items: 구매 품목만 (합계·할인·부가세·카드 정보 줄은 제외)
  · raw_name: 영수증에 적힌 품목명 원문
  · brand: 품목명에 브랜드가 있으면 브랜드, 없으면 null
  · product_name: 브랜드를 뺀 제품명
  · quantity: 수량(정수). 표시가 없으면 1
  · unit_price: 단가(정수, 원).
  · line_total: 그 줄의 금액(단가×수량, 정수, 원)
  · is_cosmetic: 화장솜·면봉·쇼핑백·퍼프·브러시·음료 같은 비화장품이면 false
금액의 쉼표와 '원'은 제거하고 숫자만 써."""

GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "raw_text": {"type": "STRING"},
        "store_name": {"type": "STRING", "nullable": True},
        "purchase_date": {"type": "STRING", "nullable": True},
        "printed_total": {"type": "INTEGER", "nullable": True},
        "discount_total": {"type": "INTEGER", "nullable": True},
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "raw_name": {"type": "STRING"},
                    "brand": {"type": "STRING", "nullable": True},
                    "product_name": {"type": "STRING"},
                    "quantity": {"type": "INTEGER"},
                    "unit_price": {"type": "INTEGER", "nullable": True},
                    "line_total": {"type": "INTEGER", "nullable": True},
                    "is_cosmetic": {"type": "BOOLEAN"},
                },
                "required": ["raw_name", "product_name", "quantity", "is_cosmetic"],
            },
        },
    },
    "required": ["raw_text", "items"],
}


class GeminiError(RuntimeError):
    pass


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def call_gemini_vision(image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
    api_key = settings.GEMINI_API_KEY.strip()
    if not api_key:
        raise GeminiError("GEMINI_API_KEY 미설정")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [
            {"text": GEMINI_PROMPT},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_SCHEMA,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},  # 키를 URL에 넣지 않음(로그 노출 방지)
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=settings.GEMINI_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        hint = {
            400: "요청 형식 또는 API 키를 확인하세요.",
            403: "API 키 권한/지역 제한을 확인하세요.",
            404: f"모델 '{settings.GEMINI_MODEL}'을 찾을 수 없어요. .env 의 GEMINI_MODEL 을 확인하세요.",
            429: "무료 할당량을 초과했어요. 잠시 후 다시 시도하세요.",
        }.get(e.code, "")
        raise GeminiError(f"HTTP {e.code} {hint} {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise GeminiError(f"네트워크 오류: {e}") from e

    candidates = body.get("candidates") or []
    if not candidates:
        raise GeminiError(f"응답 없음 (promptFeedback={body.get('promptFeedback')})")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text_out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text_out:
        raise GeminiError(f"빈 응답 (finishReason={candidates[0].get('finishReason')})")
    try:
        return _extract_json(text_out)
    except json.JSONDecodeError as e:
        raise GeminiError(f"JSON 파싱 실패: {text_out[:120]}") from e


def gemini_to_result(parsed: Dict[str, Any], db: Optional[Session], catalogs=None) -> Dict[str, Any]:
    today = _ocr_today()
    p_date = None
    if parsed.get("purchase_date"):
        p_date = extract_date(str(parsed["purchase_date"]), today)
    raw_items = [{
        "raw_name": it.get("raw_name"),
        "brand": it.get("brand"),
        "title": it.get("product_name") or it.get("raw_name"),
        "quantity": it.get("quantity"),
        "unit_price": it.get("unit_price"),
        "line_total": it.get("line_total"),
        "is_cosmetic": it.get("is_cosmetic", True),
    } for it in (parsed.get("items") or []) if isinstance(it, dict)]
    result = {
        "engine": f"gemini-vision ({settings.GEMINI_MODEL})",
        "store_name": (parsed.get("store_name") or None),
        "purchase_date": p_date.isoformat() if p_date else None,
        "printed_total": parsed.get("printed_total"),
        "discount_total": parsed.get("discount_total"),
        "items": [],
        "warnings": [],
    }
    return finalize_result(result, raw_items, db=db, catalogs=catalogs)


def analyze_receipt_image_with_gemini(image_bytes: bytes, mime_type: str, db: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    """(하위 호환) 실패 시 None"""
    try:
        img, mime = prepare_image(image_bytes)
        return gemini_to_result(call_gemini_vision(img, mime), db)
    except Exception as e:
        logger.warning("Gemini OCR 실패: %s", e)
        return None


# ---------------------------------------------------------------------------
# 엔진 ② 로컬 Tesseract (선택 설치)
# ---------------------------------------------------------------------------
def tesseract_available() -> bool:
    if not settings.ENABLE_TESSERACT:
        return False
    try:
        import pytesseract  # type: ignore
        return "kor" in pytesseract.get_languages(config="")
    except Exception:
        return False


def run_tesseract(image_bytes: bytes) -> str:
    import pytesseract  # type: ignore
    from PIL import Image, ImageFilter, ImageOps

    img = Image.open(io.BytesIO(image_bytes)).convert("L")
    if img.width < 1200:  # 작은 글씨는 확대하면 인식률이 크게 오름
        ratio = 1200 / img.width
        img = img.resize((1200, int(img.height * ratio)))
    img = ImageOps.autocontrast(img).filter(ImageFilter.SHARPEN)
    # psm 6: 균일한 텍스트 블록(영수증에 적합), preserve_interword_spaces 로 열 간격 유지
    return pytesseract.image_to_string(img, lang="kor+eng", config="--oem 3 --psm 6 -c preserve_interword_spaces=1")


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------
def recognize_receipt(
    image_bytes: Optional[bytes],
    db: Optional[Session] = None,
    client_text: Optional[str] = None,
) -> OcrOutcome:
    catalogs = db.query(CatalogProduct).all() if db is not None else []
    attempts: List[Dict[str, str]] = []
    prepared: Optional[bytes] = None
    mime = "image/jpeg"

    if image_bytes:
        try:
            prepared, mime = prepare_image(image_bytes)
        except InvalidImageError as e:
            return OcrOutcome(False, "none", error_code="invalid_image", message=str(e))

    gemini_raw_text: Optional[str] = None
    if prepared and settings.GEMINI_API_KEY.strip():
        try:
            parsed = call_gemini_vision(prepared, mime)
            gemini_raw_text = parsed.get("raw_text")
            result = gemini_to_result(parsed, db, catalogs)
            if not result["items"] and gemini_raw_text:   # 구조화 실패 시 원문으로 재파싱
                result = parse_receipt_text_rules(gemini_raw_text, db, catalogs=catalogs)
                result["engine"] = f"gemini-text + rule-parser ({settings.GEMINI_MODEL})"
            if result["items"]:
                return OcrOutcome(True, result["engine"], result, raw_text=gemini_raw_text, attempts=attempts)
            attempts.append({"engine": "gemini", "result": "품목 0개"})
        except GeminiError as e:
            logger.warning("Gemini OCR 실패: %s", e)
            attempts.append({"engine": "gemini", "result": str(e)[:200]})
        except Exception as e:  # 예기치 못한 오류도 다음 엔진으로
            logger.exception("Gemini OCR 처리 중 오류")
            attempts.append({"engine": "gemini", "result": f"내부 오류: {e}"[:200]})

    if prepared and tesseract_available():
        try:
            text = run_tesseract(prepared)
            result = parse_receipt_text_rules(text, db, catalogs=catalogs)
            result["engine"] = "tesseract + rule-parser"
            if result["items"]:
                return OcrOutcome(True, result["engine"], result, raw_text=text, attempts=attempts)
            attempts.append({"engine": "tesseract", "result": "품목 0개"})
            gemini_raw_text = gemini_raw_text or text
        except Exception as e:
            logger.exception("Tesseract OCR 오류")
            attempts.append({"engine": "tesseract", "result": str(e)[:200]})

    if client_text and client_text.strip():
        result = parse_receipt_text_rules(client_text, db, catalogs=catalogs)
        result["engine"] = "client-ocr-text + rule-parser"
        if result["items"]:
            return OcrOutcome(True, result["engine"], result, raw_text=client_text, attempts=attempts)
        attempts.append({"engine": "client-text", "result": "품목 0개"})

    if prepared and not attempts:
        return OcrOutcome(
            False, "none", raw_text=None, error_code="no_engine", attempts=attempts,
            message="이미지 인식 엔진이 설정되지 않았어요. .env 에 GEMINI_API_KEY 를 넣거나 Tesseract 를 설치해 주세요.",
        )
    return OcrOutcome(
        False, "none", raw_text=gemini_raw_text or client_text, error_code="unreadable", attempts=attempts,
        message="품목과 금액을 인식하지 못했어요. 영수증 전체가 나오도록 밝은 곳에서 다시 찍거나 직접 입력해 주세요.",
    )
