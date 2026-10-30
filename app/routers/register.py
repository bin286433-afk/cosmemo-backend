from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, CatalogProduct, OwnedProduct, ReceiptDraft, ReceiptItem
from app.schemas import ReceiptReviewUpdateRequest, OwnedProductCreate
from app.utils.security import get_current_user
from app.utils.deadline import calculate_product_deadline
from app.routers.vanity import serialize_owned_product

router = APIRouter(prefix="/register", tags=["C · 영수증에서 내 화장대로 (REG)"])


@router.get("")
def get_register_entry():
    """화면 REG-01 (/register): 새 화장품 등록 시작 화면"""
    return {
        "screen_id": "REG-01",
        "title": "한 장의 영수증으로, 빠짐없이 기억해요.",
        "steps": [
            {"step": "1. 영수증 인식", "desc": "영수증 촬영 또는 사진 선택"},
            {"step": "2. 인식 검토", "desc": "구매일·매장·제품명·수량 확인"},
            {"step": "3. 화장대 반영", "desc": "중복 확인 후 보유 목록에 저장"},
        ],
    }


@router.post("/receipt/upload")
def upload_and_parse_receipt(
    simulate_state: Optional[str] = Query(default=None, description="normal | ocr-failed | missing-brand (STATE-03, STATE-04 재현용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-02, REG-03, STATE-03(글자를 읽기 어려워요), STATE-04(필수 정보 누락)"""
    receipt = db.query(ReceiptDraft).filter(ReceiptDraft.code == "R-031").first()
    if simulate_state == "ocr-failed":
        return {
            "screen_id": "STATE-03",
            "receipt_code": "R-031",
            "state": "ocr-failed",
            "title": "글자를 읽기 어려워요",
            "message": "사진이 흔들리거나 일부가 잘려 있었어요. 입력해 둔 내용은 사라지지 않았어요.",
            "preserved_draft": {
                "receipt_code": "R-031",
                "purchase_date": "2026-10-29",
                "recognized_count": 0,
            },
        }

    if simulate_state == "missing-brand":
        return {
            "screen_id": "STATE-04",
            "receipt_code": "R-031",
            "state": "review-error",
            "error_field": "RI-2.brand",
            "banner": "브랜드 1곳을 확인해 주세요. 누락된 줄만 채우거나 해당 항목을 제외할 수 있어요.",
            "items": [
                {
                    "item_code": "RI-1",
                    "brand": "라운드리프",
                    "parsed_name": "수분 장벽 크림",
                    "quantity": 1,
                    "unit_price": 18000,
                    "status": "확인 완료",
                },
                {
                    "item_code": "RI-2",
                    "brand": "",
                    "parsed_name": "판테놀 세럼",
                    "quantity": 1,
                    "unit_price": 22000,
                    "status": "필수 정보 누락 (브랜드 입력 필요)",
                },
            ],
        }

    return {
        "screen_id": "REG-03",
        "next_screen": "REG-04",
        "receipt_code": receipt.code if receipt else "R-031",
        "status": "completed_ocr",
        "recognized_summary": {
            "store_name": "보태닉 스토어",
            "purchase_date": "2026-10-30",
            "cosmetic_items_count": 2,
            "excluded_items_count": 1,
        },
    }


@router.get("/receipt/{receipt_code}/review")
def get_receipt_review(
    receipt_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-04 (/register/receipt/R-031/review): 인식 결과 검토"""
    receipt = db.query(ReceiptDraft).filter(ReceiptDraft.code == receipt_code).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="영수증 초안을 찾을 수 없어요.")

    return {
        "screen_id": "REG-04",
        "receipt_code": receipt.code,
        "store_name": receipt.store_name,
        "purchase_date": receipt.purchase_date.isoformat() if receipt.purchase_date else "2026-10-30",
        "total_amount": receipt.total_amount,
        "items": [
            {
                "item_code": item.code,
                "raw_name": item.raw_name,
                "brand": item.brand,
                "parsed_name": item.parsed_name,
                "category": item.category,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "is_cosmetic": item.is_cosmetic,
                "is_selected": item.is_selected,
                "matched_catalog_code": item.matched_catalog_code,
            }
            for item in receipt.items
        ],
    }


@router.put("/receipt/{receipt_code}/review")
def update_receipt_review(
    receipt_code: str,
    payload: ReceiptReviewUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-04 & REG-05: 영수증 인식 항목 수정 및 카탈로그 매칭 저장"""
    receipt = db.query(ReceiptDraft).filter(ReceiptDraft.code == receipt_code).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="영수증 초안을 찾을 수 없어요.")

    receipt.store_name = payload.store_name
    receipt.purchase_date = payload.purchase_date
    receipt.total_amount = payload.total_amount

    item_map = {i.code: i for i in receipt.items}
    for upd in payload.items:
        if upd.item_code in item_map:
            target = item_map[upd.item_code]
            target.brand = upd.brand
            target.parsed_name = upd.parsed_name
            target.category = upd.category
            target.quantity = upd.quantity
            target.unit_price = upd.unit_price
            target.is_selected = upd.is_selected
            target.matched_catalog_code = upd.matched_catalog_code

    db.commit()
    return {
        "screen_id": "REG-04",
        "next_screen": "REG-07",
        "receipt_code": receipt.code,
        "selected_count": sum(1 for i in receipt.items if i.is_selected),
    }


@router.get("/catalog/match")
def search_catalog_for_matching(
    q: str = Query(default="판테놀 세럼", description="제품명 또는 브랜드 검색"),
    db: Session = Depends(get_db),
):
    """화면 REG-05 (/register/receipt/R-031/match/RI-2): 카탈로그 후보 검색 및 매칭"""
    q_lower = q.lower()
    candidates = (
        db.query(CatalogProduct)
        .filter(
            (CatalogProduct.name.ilike(f"%{q_lower}%"))
            | (CatalogProduct.brand.ilike(f"%{q_lower}%"))
        )
        .all()
    )
    return {
        "screen_id": "REG-05",
        "query": q,
        "candidates": [
            {
                "catalog_code": c.code,
                "brand": c.brand,
                "name": c.name,
                "category": c.category,
                "volume": c.volume,
                "main_ingredients": c.main_ingredients,
                "default_pao_months": c.default_pao_months,
            }
            for c in candidates
        ],
    }


@router.get("/confirm")
def confirm_before_save(
    receipt_code: Optional[str] = Query(default="R-031"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-07 (/register/confirm?draft=R-031): 저장 전 이미 보유한 동일 제품 중복 여부 안내"""
    existing_cream = (
        db.query(OwnedProduct)
        .filter(
            OwnedProduct.user_id == current_user.id,
            OwnedProduct.name == "수분 장벽 크림",
            OwnedProduct.status != "archived",
        )
        .first()
    )
    return {
        "screen_id": "REG-07",
        "receipt_code": receipt_code,
        "duplicate_notice": "같은 제품도 기록할 수 있어요! 구매일과 개봉일이 다르면 새 보유 기록(예: 미개봉)으로 구분해 저장해요.",
        "already_owned": serialize_owned_product(existing_cream, db) if existing_cream else None,
        "to_be_added": [
            {
                "brand": "라운드리프",
                "name": "수분 장벽 크림",
                "purchase_date": "2026-10-30",
                "quantity": 1,
                "initial_status": "unopened (OWN-104 생성 예정)",
                "matched_catalog_code": "CAT-01",
            },
            {
                "brand": "라운드리프",
                "name": "판테놀 세럼",
                "purchase_date": "2026-10-30",
                "quantity": 1,
                "initial_status": "unopened (OWN-103 생성 예정)",
                "matched_catalog_code": "CAT-03",
            },
        ],
    }


@router.post("/manual", status_code=201)
def register_product_manual(
    payload: OwnedProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REG-06 (/register/manual) 및 REG-08 (/register/complete): 제품 직접 등록 및 화장대 반영 완료"""
    catalog = None
    if payload.catalog_code:
        catalog = db.query(CatalogProduct).filter(CatalogProduct.code == payload.catalog_code).first()

    next_num = 101 + db.query(OwnedProduct).count()
    new_code = f"OWN-{next_num}"

    deadline, basis = calculate_product_deadline(
        status=payload.status,
        opened_date=payload.opened_date,
        printed_expiry_date=payload.printed_expiry_date,
        pao_months=payload.pao_months,
    )

    new_owned = OwnedProduct(
        code=new_code,
        user_id=current_user.id,
        catalog_id=catalog.id if catalog else None,
        brand=payload.brand,
        name=payload.name,
        category=payload.category,
        volume=payload.volume,
        main_ingredients=payload.main_ingredients,
        status=payload.status,
        purchase_date=payload.purchase_date,
        opened_date=payload.opened_date,
        printed_expiry_date=payload.printed_expiry_date,
        pao_months=payload.pao_months,
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
