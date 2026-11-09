"""
C · 영수증에서 내 화장대로 (REG-01 ~ REG-08, STATE-03, STATE-04, STATE-06)

[원본 대비 주요 수정]
 1) 이미지 업로드 시 OCR 엔진이 없으면 '샘플 영수증(R-031) 결과'를 성공처럼 돌려주던 문제
    → 실제 실패(STATE-03)로 응답하고, 이미지와 초안은 DB에 보존해 재시도(/retry) 가능
 2) 품목을 하나도 못 읽어도 status=completed_ocr 로 시드 초안을 반환하던 문제 → STATE-03
 3) 업로드 파일 크기/형식 검증, 이미지 파일 디스크 저장(uploads/), image_url·원문·엔진·신뢰도 저장
 4) 같은 영수증 사진 재업로드 감지 (sha256) → 기존 초안 재사용 (STATE-06 중복 저장 방지)
 5) 영수증 조회/수정/반영 API에 사용자 소유 검사 추가 (다른 사용자의 영수증 접근 차단)
 6) 화장대 반영(commit)을 두 번 호출하면 제품이 중복 생성되던 문제 → 멱등 처리
 7) commit 시 모든 제품에 2027-08-31 기한·'라운드리프' 브랜드가 하드코딩되던 문제 → 실제 값/계산 사용
 8) 중복 보유 안내(confirm)가 '수분 장벽 크림' 하나만 하드코딩 검사하던 문제 → 품목별 실제 검사
 9) Gemini 호출(최대 수십 초)이 async 함수 안에서 이벤트 루프를 막던 문제 → 스레드풀에서 실행
10) 코드 채번을 count() 기반 → 최대 번호 + 1 (삭제 후 코드 충돌 방지)
"""
import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import CatalogProduct, OwnedProduct, ReceiptDraft, ReceiptItem, User, _utcnow
from app.routers.vanity import serialize_owned_product
from app.schemas import OwnedProductCreate, ReceiptReviewUpdateRequest
from app.utils.codes import next_code
from app.utils.deadline import calculate_product_deadline, get_today
from app.utils.ocr_engine import (
    ALLOWED_IMAGE_TYPES,
    OcrOutcome,
    parse_receipt_text_rules,
    rank_catalog_candidates,
    recognize_receipt,
)
from app.utils.security import get_current_user

logger = logging.getLogger("cosmemo.register")
router = APIRouter(prefix="/register", tags=["C · 영수증에서 내 화장대로 (REG & 실시간 OCR)"])

DEFAULT_SAMPLE_RECEIPT_TEXT = """보태닉 스토어 강남점
2026.10.30 14:20
라운드리프 수분 장벽 크림 1 18,000
라운드리프 판테놀 세럼 1 22,000
화장솜 1 3,300
합계 43,300원"""


class ReceiptTextParseRequest(BaseModel):
    raw_ocr_text: str = DEFAULT_SAMPLE_RECEIPT_TEXT


# ---------------------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------------------
def _get_user_receipt(db: Session, user: User, receipt_code: str) -> ReceiptDraft:
    receipt = (
        db.query(ReceiptDraft)
        .filter(ReceiptDraft.code == receipt_code, ReceiptDraft.user_id == user.id)
        .first()
    )
    if not receipt:
        raise HTTPException(status_code=404, detail="영수증 초안을 찾을 수 없어요.")
    return receipt


def _review_status(receipt: ReceiptDraft) -> str:
    """선택된 화장품 품목 중 브랜드/제품명이 빠진 것이 있으면 review_error (STATE-04)"""
    for it in receipt.items:
        if it.is_selected and it.is_cosmetic and (not (it.brand or "").strip() or not (it.parsed_name or "").strip()):
            return "review_error"
    return "review"


def _missing_fields(receipt: ReceiptDraft) -> List[str]:
    return [
        f"{it.code}.brand" for it in receipt.items
        if it.is_selected and it.is_cosmetic and not (it.brand or "").strip()
    ]


def serialize_item(i: ReceiptItem) -> dict:
    return {
        "item_code": i.code,
        "raw_name": i.raw_name,
        "brand": i.brand,
        "parsed_name": i.parsed_name,
        "category": i.category,
        "quantity": i.quantity,
        "unit_price": i.unit_price,
        "line_total": i.line_total if i.line_total is not None else (i.unit_price or 0) * (i.quantity or 1),
        "is_cosmetic": i.is_cosmetic,
        "is_selected": i.is_selected,
        "matched_catalog_code": i.matched_catalog_code,
        "match_score": i.match_score,
        "owned_product_code": i.owned_product_code,
        "status": "필수 정보 누락 (브랜드 입력 필요)" if (i.is_cosmetic and i.is_selected and not i.brand) else "확인 완료",
    }


def serialize_receipt(r: ReceiptDraft) -> dict:
    return {
        "receipt_code": r.code,
        "status": r.status,
        "store_name": r.store_name,
        "purchase_date": r.purchase_date.isoformat() if r.purchase_date else None,
        "total_amount": r.total_amount,
        "printed_total": r.printed_total,
        "discount_total": r.discount_total,
        "engine_used": r.ocr_engine,
        "confidence": r.ocr_confidence,
        "warnings": r.ocr_warnings or [],
        "image_url": f"/register/receipt/{r.code}/image" if r.image_url else None,
        "missing_fields": _missing_fields(r),
        "cosmetic_items_count": sum(1 for i in r.items if i.is_cosmetic),
        "excluded_items_count": sum(1 for i in r.items if not i.is_cosmetic),
        "items": [serialize_item(i) for i in r.items],
    }


def _apply_parsed_to_draft(draft: ReceiptDraft, parsed: dict, raw_text: Optional[str], db: Session) -> None:
    """파싱 결과를 초안에 반영 (기존 품목은 교체)."""
    p_date = None
    if parsed.get("purchase_date"):
        try:
            p_date = date.fromisoformat(parsed["purchase_date"])
        except ValueError:
            p_date = None

    draft.store_name = (parsed.get("store_name") or "매장 미확인")[:100]
    draft.purchase_date = p_date            # 모르면 None (예전처럼 2026-10-30 으로 위조하지 않음)
    draft.total_amount = int(parsed.get("total_amount") or 0)
    draft.printed_total = parsed.get("printed_total")
    draft.discount_total = parsed.get("discount_total")
    draft.raw_text = raw_text
    draft.ocr_engine = (parsed.get("engine") or "")[:80]
    draft.ocr_confidence = parsed.get("confidence")
    draft.ocr_warnings = parsed.get("warnings") or []

    draft.items.clear()
    db.flush()
    for idx, item in enumerate(parsed.get("items", []), start=1):
        draft.items.append(ReceiptItem(
            code=f"RI-{idx}",
            raw_name=(item.get("raw_name") or item["parsed_name"])[:200],
            brand=item.get("brand"),
            parsed_name=item["parsed_name"][:200],
            category=item.get("category", "스킨케어"),
            quantity=item.get("quantity", 1),
            unit_price=item.get("unit_price", 0),
            line_total=item.get("line_total"),
            is_cosmetic=item.get("is_cosmetic", True),
            is_selected=item.get("is_selected", True),
            matched_catalog_code=item.get("matched_catalog_code"),
            match_score=item.get("match_score"),
        ))
    db.flush()
    draft.status = _review_status(draft)


def save_parsed_receipt_to_db(
    parsed_data: dict,
    user: User,
    db: Session,
    raw_text: Optional[str] = None,
    image_url: Optional[str] = None,
    image_sha256: Optional[str] = None,
) -> ReceiptDraft:
    """파싱된 영수증 결과를 ReceiptDraft + ReceiptItem 으로 저장 (트랜잭션 1회)."""
    try:
        draft = ReceiptDraft(
            code=next_code(db, ReceiptDraft, "R", start=31, width=3),
            user_id=user.id,
            image_url=image_url,
            image_sha256=image_sha256,
        )
        db.add(draft)
        db.flush()
        _apply_parsed_to_draft(draft, parsed_data, raw_text, db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(draft)
    return draft


def _save_failed_draft(db: Session, user: User, outcome: OcrOutcome, image_url: Optional[str], sha: Optional[str]) -> ReceiptDraft:
    """STATE-03: 인식 실패여도 이미지와 초안은 남겨 두고 재시도·직접 입력으로 이어갈 수 있게 함."""
    draft = ReceiptDraft(
        code=next_code(db, ReceiptDraft, "R", start=31, width=3),
        user_id=user.id,
        store_name="매장 미확인",
        purchase_date=None,
        total_amount=0,
        status="ocr_failed",
        image_url=image_url,
        image_sha256=sha,
        raw_text=outcome.raw_text,
        ocr_engine=outcome.engine,
        ocr_confidence=0.0,
        ocr_warnings=[outcome.message] + [f"{a['engine']}: {a['result']}" for a in outcome.attempts],
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic", "image/heif": ".heif"}


def _store_upload(user: User, data: bytes, sha: str, content_type: str) -> str:
    """원본 이미지를 uploads/<USER>/<sha>.<ext> 로 저장하고 UPLOAD_DIR 기준 상대 경로를 반환.
    영수증은 개인정보(카드 끝자리·매장 위치)가 있어 정적 공개하지 않고, 본인 인증된 API로만 내려줍니다."""
    folder = Path(settings.UPLOAD_DIR) / (user.code or f"user-{user.id}")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha[:32]}{_EXT.get(content_type, '.jpg')}"
    if not path.exists():
        path.write_bytes(data)
    return f"{folder.name}/{path.name}"


def _upload_path(stored: Optional[str]) -> Optional[Path]:
    if not stored:
        return None
    base = Path(settings.UPLOAD_DIR).resolve()
    path = (base / stored.lstrip("/").removeprefix("uploads/")).resolve()
    return path if base in path.parents and path.exists() else None


def _ocr_failed_response(draft: ReceiptDraft, outcome: OcrOutcome) -> dict:
    return {
        "screen_id": "STATE-03",
        "state": "ocr-failed",
        "error_code": outcome.error_code,
        "title": "글자를 읽기 어려워요",
        "message": outcome.message,
        "attempts": outcome.attempts,
        "receipt_code": draft.code,
        "preserved_draft": {
            "receipt_code": draft.code,
            "image_url": draft.image_url,
            "recognized_count": 0,
        },
        "next_actions": [
            {"label": "다시 인식하기", "method": "POST", "path": f"/register/receipt/{draft.code}/retry"},
            {"label": "직접 입력하기", "method": "POST", "path": "/register/manual"},
        ],
    }


def _ocr_success_response(draft: ReceiptDraft, screen_id: str = "REG-03", reused: bool = False) -> dict:
    data = serialize_receipt(draft)
    data.update({
        "screen_id": screen_id,
        "next_screen": "REG-04",
        "state": "review-error" if draft.status == "review_error" else "completed_ocr",
        "reused_existing_draft": reused,
        "recognized_summary": {
            "store_name": draft.store_name,
            "purchase_date": data["purchase_date"],
            "total_amount": draft.total_amount,
            "cosmetic_items_count": data["cosmetic_items_count"],
            "excluded_items_count": data["excluded_items_count"],
        },
    })
    if draft.status == "review_error":
        data["banner"] = "브랜드를 확인해 주세요. 누락된 줄만 채우거나 해당 항목을 제외할 수 있어요."
    return data


# ---------------------------------------------------------------------------
# REG-01 ~ REG-03
# ---------------------------------------------------------------------------
@router.get("")
def get_register_entry():
    """화면 REG-01 (/register): 새 화장품 등록 시작 화면"""
    return {
        "screen_id": "REG-01",
        "title": "한 장의 영수증으로, 빠짐없이 기억해요.",
        "ocr_engines": {
            "gemini_vision": bool(settings.GEMINI_API_KEY.strip()),
            "gemini_model": settings.GEMINI_MODEL if settings.GEMINI_API_KEY.strip() else None,
        },
        "steps": [
            {"step": "1. 영수증 인식", "desc": "영수증 이미지 업로드 또는 OCR 텍스트 자동 파싱"},
            {"step": "2. 인식 검토", "desc": "구매일·매장·제품명·수량 확인 및 비화장품 자동 제외"},
            {"step": "3. 화장대 반영", "desc": "중복 확인 후 보유 목록에 저장"},
        ],
    }


@router.post("/receipt/ocr-text")
def parse_receipt_from_ocr_text(
    payload: ReceiptTextParseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [OCR 텍스트 파싱 API]
    모바일 기기 OCR(iOS Live Text, ML Kit 등)이나 Tesseract로 얻은 영수증 텍스트를 받아
    매장명·구매일·품목·가격·합계·할인을 파싱하고 비화장품 분리 및 카탈로그 매칭 후 DB에 저장합니다.
    """
    parsed = parse_receipt_text_rules(payload.raw_ocr_text, db)
    parsed["engine"] = "client-ocr-text + rule-parser"
    if not parsed["items"]:
        return {
            "screen_id": "STATE-03",
            "state": "ocr-failed",
            "title": "글자를 읽기 어려워요",
            "message": "품목과 금액을 인식하지 못했어요. 영수증 글자를 확인하거나 직접 입력해 주세요.",
            "warnings": parsed["warnings"],
        }
    draft = save_parsed_receipt_to_db(parsed, current_user, db, raw_text=payload.raw_ocr_text)
    return _ocr_success_response(draft, screen_id="REG-04")


@router.post("/receipt/upload")
async def upload_and_parse_receipt(
    file: Optional[UploadFile] = File(default=None, description="영수증 이미지 (.jpg .png .webp) 또는 텍스트 파일"),
    raw_ocr_text: Optional[str] = Form(default=None, description="기기 OCR 텍스트 (이미지와 함께 보내면 엔진 실패 시 대체 사용)"),
    simulate_state: Optional[str] = Query(default=None, description="normal | ocr-failed | missing-brand (STATE-03, STATE-04 재현용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    화면 REG-02, REG-03, STATE-03, STATE-04
    · 이미지: Gemini Vision → (설치 시) Tesseract → raw_ocr_text 순으로 인식. 전부 실패하면 STATE-03.
    · 텍스트 파일 또는 raw_ocr_text 만 전달: 규칙 기반 파서로 바로 분석.
    """
    if simulate_state == "ocr-failed":
        return {
            "screen_id": "STATE-03", "receipt_code": "R-031", "state": "ocr-failed",
            "title": "글자를 읽기 어려워요",
            "message": "사진이 흔들리거나 일부가 잘려 있었어요. 입력해 둔 내용은 사라지지 않았어요.",
            "preserved_draft": {"receipt_code": "R-031", "purchase_date": "2026-10-29", "recognized_count": 0},
        }
    if simulate_state == "missing-brand":
        return {
            "screen_id": "STATE-04", "receipt_code": "R-031", "state": "review-error", "error_field": "RI-2.brand",
            "banner": "브랜드 1곳을 확인해 주세요. 누락된 줄만 채우거나 해당 항목을 제외할 수 있어요.",
            "items": [
                {"item_code": "RI-1", "brand": "라운드리프", "parsed_name": "수분 장벽 크림", "quantity": 1, "unit_price": 18000, "status": "확인 완료"},
                {"item_code": "RI-2", "brand": "", "parsed_name": "판테놀 세럼", "quantity": 1, "unit_price": 22000, "status": "필수 정보 누락 (브랜드 입력 필요)"},
            ],
        }

    if file is None and not (raw_ocr_text and raw_ocr_text.strip()):
        raise HTTPException(status_code=400, detail="영수증 이미지(file) 또는 OCR 텍스트(raw_ocr_text)를 보내 주세요.")

    # --- 텍스트만 온 경우 ---
    if file is None or (file.content_type or "").startswith("text/"):
        text = raw_ocr_text or ""
        if file is not None:
            text = (await file.read()).decode("utf-8", errors="ignore")
        parsed = parse_receipt_text_rules(text, db)
        parsed["engine"] = "client-ocr-text + rule-parser"
        if not parsed["items"]:
            return {
                "screen_id": "STATE-03", "state": "ocr-failed", "title": "글자를 읽기 어려워요",
                "message": "품목과 금액을 인식하지 못했어요. 영수증 글자를 확인하거나 직접 입력해 주세요.",
                "warnings": parsed["warnings"],
            }
        draft = save_parsed_receipt_to_db(parsed, current_user, db, raw_text=text)
        return _ocr_success_response(draft)

    # --- 이미지 ---
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_IMAGE_TYPES and content_type != "application/octet-stream":
        raise HTTPException(status_code=415, detail=f"지원하지 않는 파일 형식이에요 ({content_type}). JPG·PNG·WEBP 사진을 올려 주세요.")
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"사진 용량이 너무 커요. {settings.MAX_UPLOAD_MB}MB 이하로 올려 주세요.")
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일이에요.")

    sha = hashlib.sha256(data).hexdigest()
    # STATE-06: 같은 사진을 다시 올리면 이미 만든 초안을 그대로 돌려줌 (실패 초안은 재시도 허용)
    existing = (
        db.query(ReceiptDraft)
        .filter(ReceiptDraft.user_id == current_user.id, ReceiptDraft.image_sha256 == sha, ReceiptDraft.status != "ocr_failed")
        .order_by(ReceiptDraft.id.desc())
        .first()
    )
    if existing:
        return _ocr_success_response(existing, reused=True)

    image_url = _store_upload(current_user, data, sha, content_type)
    # 외부 API 호출(블로킹)을 스레드풀에서 실행해 다른 요청이 멈추지 않도록 함
    outcome: OcrOutcome = await run_in_threadpool(recognize_receipt, data, db, raw_ocr_text)

    if outcome.error_code == "invalid_image":
        raise HTTPException(status_code=422, detail=outcome.message)
    if not outcome.ok:
        draft = _save_failed_draft(db, current_user, outcome, image_url, sha)
        return _ocr_failed_response(draft, outcome)

    draft = save_parsed_receipt_to_db(outcome.data, current_user, db, raw_text=outcome.raw_text, image_url=image_url, image_sha256=sha)
    return _ocr_success_response(draft)


@router.post("/receipt/{receipt_code}/retry")
async def retry_receipt_ocr(
    receipt_code: str,
    raw_ocr_text: Optional[str] = Form(default=None, description="재시도 시 함께 쓸 기기 OCR 텍스트(선택)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """STATE-03 '다시 인식하기': 보관해 둔 원본 이미지로 OCR을 다시 실행해 같은 초안을 갱신합니다."""
    receipt = _get_user_receipt(db, current_user, receipt_code)
    if receipt.status == "completed":
        raise HTTPException(status_code=409, detail="이미 화장대에 반영된 영수증이에요.")
    path = _upload_path(receipt.image_url)
    data = path.read_bytes() if path else None
    if data is None and not raw_ocr_text:
        raise HTTPException(status_code=400, detail="다시 인식할 원본 이미지가 없어요. 사진을 새로 올려 주세요.")

    outcome: OcrOutcome = await run_in_threadpool(recognize_receipt, data, db, raw_ocr_text)
    if not outcome.ok:
        receipt.ocr_warnings = [outcome.message] + [f"{a['engine']}: {a['result']}" for a in outcome.attempts]
        db.commit()
        return _ocr_failed_response(receipt, outcome)
    _apply_parsed_to_draft(receipt, outcome.data, outcome.raw_text, db)
    db.commit()
    db.refresh(receipt)
    return _ocr_success_response(receipt)


@router.get("/receipt/{receipt_code}/image")
def get_receipt_image(
    receipt_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """REG-04 검토 화면에서 원본 영수증 사진 보기 (본인 영수증만)"""
    receipt = _get_user_receipt(db, current_user, receipt_code)
    path = _upload_path(receipt.image_url)
    if not path:
        raise HTTPException(status_code=404, detail="저장된 영수증 사진이 없어요.")
    return FileResponse(path)


# ---------------------------------------------------------------------------
# REG-04 ~ REG-05 검토 · 매칭
# ---------------------------------------------------------------------------
@router.get("/receipt/{receipt_code}/review")
def get_receipt_review(
    receipt_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-04 (/register/receipt/R-031/review): 인식 결과 검토"""
    receipt = _get_user_receipt(db, current_user, receipt_code)
    data = serialize_receipt(receipt)
    data["screen_id"] = "STATE-04" if receipt.status == "review_error" else "REG-04"
    return data


@router.put("/receipt/{receipt_code}/review")
def update_receipt_review(
    receipt_code: str,
    payload: ReceiptReviewUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-04 & REG-05: 영수증 인식 항목 수정 및 카탈로그 매칭 저장"""
    receipt = _get_user_receipt(db, current_user, receipt_code)
    if receipt.status == "completed":
        raise HTTPException(status_code=409, detail="이미 화장대에 반영된 영수증은 수정할 수 없어요. 제품 상세에서 고쳐 주세요.")

    receipt.store_name = payload.store_name
    receipt.purchase_date = payload.purchase_date
    receipt.total_amount = payload.total_amount

    item_map = {i.code: i for i in receipt.items}
    unknown = [u.item_code for u in payload.items if u.item_code not in item_map]
    if unknown:
        raise HTTPException(status_code=422, detail=f"영수증에 없는 품목 코드예요: {', '.join(unknown)}")

    for upd in payload.items:
        target = item_map[upd.item_code]
        if upd.matched_catalog_code:
            cat = db.query(CatalogProduct).filter(CatalogProduct.code == upd.matched_catalog_code).first()
            if not cat:
                raise HTTPException(status_code=422, detail=f"카탈로그 코드 {upd.matched_catalog_code}를 찾을 수 없어요.")
            target.match_score = 1.0  # 사용자가 직접 확정
        target.brand = (upd.brand or "").strip() or None
        target.parsed_name = upd.parsed_name
        target.category = upd.category
        target.quantity = upd.quantity
        target.unit_price = upd.unit_price
        target.line_total = upd.unit_price * upd.quantity
        target.is_selected = upd.is_selected
        target.matched_catalog_code = upd.matched_catalog_code

    receipt.status = _review_status(receipt)
    if "user-reviewed" not in (receipt.ocr_engine or ""):
        receipt.ocr_engine = f"{receipt.ocr_engine or 'manual'} + user-reviewed"[:80]
    db.commit()
    db.refresh(receipt)
    return {
        "screen_id": "STATE-04" if receipt.status == "review_error" else "REG-04",
        "next_screen": "REG-04" if receipt.status == "review_error" else "REG-07",
        "receipt_code": receipt.code,
        "status": receipt.status,
        "missing_fields": _missing_fields(receipt),
        "selected_count": sum(1 for i in receipt.items if i.is_selected),
    }


@router.get("/catalog/match")
def search_catalog_for_matching(
    q: str = Query(default="판테놀 세럼", description="제품명 또는 브랜드 검색"),
    brand: Optional[str] = Query(default=None, description="알고 있는 브랜드(선택)"),
    db: Session = Depends(get_db),
):
    """화면 REG-05: 카탈로그 후보 검색 — 부분 일치 + 유사도 점수 순 정렬 (띄어쓰기·용량 표기 차이 허용)"""
    like = f"%{q.strip()}%"
    direct = db.query(CatalogProduct).filter(CatalogProduct.name.ilike(like) | CatalogProduct.brand.ilike(like)).all()
    ranked = rank_catalog_candidates(db, brand, q, limit=5)
    seen, candidates = set(), []
    for c, score in [(c, 1.0) for c in direct] + ranked:
        if c.code in seen:
            continue
        seen.add(c.code)
        candidates.append({
            "catalog_code": c.code, "brand": c.brand, "name": c.name, "category": c.category,
            "volume": c.volume, "main_ingredients": c.main_ingredients,
            "default_pao_months": c.default_pao_months, "score": round(score, 3),
        })
    return {"screen_id": "REG-05", "query": q, "candidates": candidates}


# ---------------------------------------------------------------------------
# REG-07 ~ REG-08 확인 · 반영
# ---------------------------------------------------------------------------
def _find_same_owned(db: Session, user: User, brand: Optional[str], name: str, catalog_id: Optional[int]):
    q = db.query(OwnedProduct).filter(OwnedProduct.user_id == user.id, OwnedProduct.status != "archived")
    norm = lambda s: (s or "").replace(" ", "").lower()  # noqa: E731
    for p in q.all():
        if catalog_id and p.catalog_id == catalog_id:
            return p
        if norm(p.name) == norm(name) and (not brand or norm(p.brand) == norm(brand)):
            return p
    return None


@router.get("/confirm")
def confirm_before_save(
    receipt_code: str = Query(default="R-031"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-07: 저장 전, 품목별로 이미 보유 중인 같은 제품이 있는지 안내"""
    receipt = _get_user_receipt(db, current_user, receipt_code)
    cat_ids = {c.code: c.id for c in db.query(CatalogProduct).all()}

    to_be_added, duplicates = [], []
    for item in receipt.items:
        if not (item.is_selected and item.is_cosmetic):
            continue
        same = _find_same_owned(db, current_user, item.brand, item.parsed_name, cat_ids.get(item.matched_catalog_code))
        entry = {
            "item_code": item.code,
            "brand": item.brand,
            "name": item.parsed_name,
            "purchase_date": receipt.purchase_date.isoformat() if receipt.purchase_date else None,
            "quantity": item.quantity,
            "unit_price": item.unit_price,
            "matched_catalog_code": item.matched_catalog_code,
            "already_owned_code": same.code if same else None,
        }
        to_be_added.append(entry)
        if same:
            duplicates.append(serialize_owned_product(same, db))

    return {
        "screen_id": "REG-07",
        "receipt_code": receipt.code,
        "status": receipt.status,
        "can_commit": receipt.status == "review" and bool(to_be_added),
        "missing_fields": _missing_fields(receipt),
        "duplicate_notice": "같은 제품도 기록할 수 있어요! 구매일과 개봉일이 다르면 새 보유 기록(예: 미개봉)으로 구분해 저장해요." if duplicates else None,
        "already_owned": duplicates[0] if duplicates else None,   # (하위 호환) 첫 번째 중복
        "already_owned_list": duplicates,
        "to_be_added": to_be_added,
    }


@router.post("/receipt/{receipt_code}/commit", status_code=201)
def commit_receipt_items_to_vanity(
    receipt_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-07 → REG-08: 선택된 화장품 품목을 내 화장대(OwnedProduct)에 일괄 추가 (한 번만 반영)"""
    receipt = _get_user_receipt(db, current_user, receipt_code)

    if receipt.status == "completed":
        # 멱등 처리: 두 번 눌러도 제품이 두 번 생기지 않음 (STATE-06)
        codes = [i.owned_product_code for i in receipt.items if i.owned_product_code]
        products = db.query(OwnedProduct).filter(OwnedProduct.code.in_(codes), OwnedProduct.user_id == current_user.id).all()
        return {
            "screen_id": "REG-08", "title": "이미 화장대에 반영된 영수증이에요",
            "receipt_code": receipt.code, "already_committed": True,
            "added_count": 0, "created_products": [serialize_owned_product(p, db) for p in products],
        }
    if receipt.status == "ocr_failed":
        raise HTTPException(status_code=409, detail="인식에 실패한 영수증이에요. 다시 인식하거나 직접 입력해 주세요.")
    missing = _missing_fields(receipt)
    if missing:
        raise HTTPException(status_code=422, detail={
            "screen_id": "STATE-04", "message": "브랜드가 비어 있는 품목이 있어요. 채우거나 선택 해제해 주세요.",
            "missing_fields": missing,
        })

    selected = [i for i in receipt.items if i.is_selected and i.is_cosmetic]
    if not selected:
        raise HTTPException(status_code=422, detail="화장대에 추가할 화장품 품목을 1개 이상 선택해 주세요.")

    created = []
    try:
        for item in selected:
            cat = None
            if item.matched_catalog_code:
                cat = db.query(CatalogProduct).filter(CatalogProduct.code == item.matched_catalog_code).first()
            pao = cat.default_pao_months if cat else None
            deadline, basis = calculate_product_deadline("unopened", None, None, pao)
            owned = OwnedProduct(
                code=next_code(db, OwnedProduct, "OWN", start=101, width=3),
                user_id=current_user.id,
                catalog_id=cat.id if cat else None,
                brand=item.brand,
                name=item.parsed_name,
                category=item.category or (cat.category if cat else "스킨케어"),
                volume=cat.volume if cat else None,
                main_ingredients=(cat.main_ingredients if cat else []) or [],
                status="unopened",
                purchase_date=receipt.purchase_date,
                opened_date=None,
                printed_expiry_date=None,   # 인쇄 기한은 영수증에 없음 → 사용자가 제품 상세에서 입력
                pao_months=pao,
                calculated_deadline=deadline,
                deadline_basis=basis,
                remaining_percent=100,
                purchase_store=receipt.store_name,
                purchase_price=item.unit_price,
                quantity=item.quantity,
                receipt_code=receipt.code,
                memo=f"영수증({receipt.code}) 인식으로 등록한 제품",
            )
            db.add(owned)
            db.flush()
            item.owned_product_code = owned.code
            created.append(owned)

        receipt.status = "completed"
        receipt.committed_at = _utcnow()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "screen_id": "REG-08",
        "title": "화장대가 조금 더 선명해졌어요",
        "receipt_code": receipt.code,
        "added_count": len(created),
        "created_products": [serialize_owned_product(p, db) for p in created],
        "next_hint": "제품 용기에 인쇄된 사용 기한을 입력하면 더 정확한 기한 알림을 받을 수 있어요.",
    }


@router.post("/manual", status_code=201)
def register_product_manual(
    payload: OwnedProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-06 (/register/manual) 및 REG-08: 제품 직접 등록 및 화장대 반영 완료"""
    catalog = None
    if payload.catalog_code:
        catalog = db.query(CatalogProduct).filter(CatalogProduct.code == payload.catalog_code).first()
        if not catalog:
            raise HTTPException(status_code=422, detail=f"카탈로그 코드 {payload.catalog_code}를 찾을 수 없어요.")

    status = "in_use" if payload.opened_date else payload.status
    pao = payload.pao_months if payload.pao_months is not None else (catalog.default_pao_months if catalog else None)
    deadline, basis = calculate_product_deadline(status, payload.opened_date, payload.printed_expiry_date, pao)

    new_owned = OwnedProduct(
        code=next_code(db, OwnedProduct, "OWN", start=101, width=3),
        user_id=current_user.id,
        catalog_id=catalog.id if catalog else None,
        brand=payload.brand,
        name=payload.name,
        category=payload.category,
        volume=payload.volume,
        main_ingredients=payload.main_ingredients,
        status=status,
        purchase_date=payload.purchase_date,
        opened_date=payload.opened_date,
        printed_expiry_date=payload.printed_expiry_date,
        pao_months=pao,
        calculated_deadline=deadline,
        deadline_basis=basis,
        remaining_percent=100,
        purchase_store=payload.purchase_store,
        purchase_price=payload.purchase_price,
        quantity=payload.quantity,
        receipt_code=payload.receipt_code,
        memo=payload.memo,
    )
    db.add(new_owned)
    db.commit()
    db.refresh(new_owned)
    return {
        "screen_id": "REG-08",
        "title": "화장대가 조금 더 선명해졌어요",
        "created_product": serialize_owned_product(new_owned, db),
    }
