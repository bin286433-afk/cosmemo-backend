from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, Evaluation
from app.schemas import OwnedProductUpdate, OpenProductRequest
from app.utils.security import get_current_user
from app.utils.deadline import calculate_product_deadline, compute_d_day, REFERENCE_TODAY

router = APIRouter(tags=["B · 홈 · 내 화장대 · 제품 관리 (HOME/VAN/PROD)"])


def serialize_owned_product(p: OwnedProduct, db: Session) -> dict:
    d_day = compute_d_day(p.calculated_deadline, REFERENCE_TODAY)
    evals = (
        db.query(Evaluation)
        .filter(Evaluation.owned_product_id == p.id)
        .order_by(Evaluation.evaluated_date.desc(), Evaluation.id.desc())
        .all()
    )
    latest_eval = evals[0] if evals else None

    if p.status == "expired" or (d_day is not None and d_day < 0):
        deadline_badge = f"{p.calculated_deadline.strftime('%m.%d')} 기한 지남 · 사용 중단 안내" if p.calculated_deadline else "기한 초과"
    elif p.status == "unopened":
        deadline_badge = f"미개봉 · 개봉일 미등록 ({p.printed_expiry_date.strftime('%Y.%m.%d')}까지)" if p.printed_expiry_date else "미개봉 · 개봉일 미등록"
    elif p.calculated_deadline and d_day is not None:
        if d_day <= 30:
            deadline_badge = f"{p.calculated_deadline.strftime('%m.%d')}까지 · D-{d_day}"
        else:
            deadline_badge = f"{p.calculated_deadline.strftime('%Y.%m.%d')}까지"
    else:
        deadline_badge = "기한 확인 필요 · PAO 미등록"

    return {
        "code": p.code,
        "catalog_code": p.catalog.code if p.catalog else None,
        "brand": p.brand,
        "name": p.name,
        "category": p.category,
        "volume": p.volume,
        "main_ingredients": p.main_ingredients or [],
        "status": p.status,
        "purchase_date": p.purchase_date.isoformat() if p.purchase_date else None,
        "opened_date": p.opened_date.isoformat() if p.opened_date else None,
        "printed_expiry_date": p.printed_expiry_date.isoformat() if p.printed_expiry_date else None,
        "pao_months": p.pao_months,
        "calculated_deadline": p.calculated_deadline.isoformat() if p.calculated_deadline else None,
        "deadline_basis": p.deadline_basis,
        "d_day": d_day,
        "deadline_badge": deadline_badge,
        "remaining_percent": p.remaining_percent,
        "purchase_store": p.purchase_store,
        "purchase_price": p.purchase_price,
        "receipt_code": p.receipt_code,
        "memo": p.memo,
        "evaluation_count": len(evals),
        "latest_evaluation": {
            "code": latest_eval.code,
            "rating": latest_eval.rating,
            "skin_fit": latest_eval.skin_fit,
            "repurchase_intent": latest_eval.repurchase_intent,
            "memo": latest_eval.memo,
            "evaluated_date": latest_eval.evaluated_date.isoformat(),
        } if latest_eval else None,
    }


@router.get("/home")
def get_home_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 HOME-01 (/home): 대시보드 요약, 먼저 확인할 제품, 기한 임박 루틴, 계절 노트"""
    active_products = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status != "archived")
        .all()
    )
    serialized = [serialize_owned_product(p, db) for p in active_products]

    expired_items = [item for item in serialized if item["status"] == "expired" or (item["d_day"] is not None and item["d_day"] < 0)]
    within_30_items = [item for item in serialized if item["status"] == "in_use" and item["d_day"] is not None and 0 <= item["d_day"] <= 30]
    routine_items = sorted(
        [item for item in serialized if item["status"] == "in_use" and item["calculated_deadline"]],
        key=lambda x: x["calculated_deadline"],
    )[:2]

    return {
        "screen_id": "HOME-01",
        "reference_date": REFERENCE_TODAY.isoformat(),
        "greeting": f"{current_user.nickname}님, 오늘도 나를 아끼는 기록.",
        "summary_counts": {
            "total_active": len(serialized),
            "within_30_days": len(within_30_items),
            "expired": len(expired_items),
        },
        "urgent_alert": expired_items[0] if expired_items else None,
        "upcoming_routine": routine_items,
        "seasonal_note": {
            "season": "가을",
            "title": "건조해지는 계절, 새 제품보다 내 기록부터.",
            "description": f"{', '.join(current_user.skin_concerns)} 관심 프로필과 보유 성분을 기준으로 정리했어요.",
            "target_path": "/seasonal/autumn",
        },
    }


@router.get("/vanity")
def list_vanity_products(
    category: str = Query(default="all", description="all | 스킨케어 | 색조 | 향수"),
    status: str = Query(default="all", description="all | unopened | in_use | expired"),
    ingredient: Optional[str] = Query(default=None, description="예: 판테놀, 병풀추출물, 세라마이드"),
    q: Optional[str] = Query(default=None, description="제품명, 브랜드 또는 성분 검색"),
    sort: str = Query(default="deadline", description="deadline | recent | name"),
    state: Optional[str] = Query(default=None, description="empty | network-error (H 화면 예외 상태 재현용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 VAN-01 (/vanity), VAN-02 (/vanity/filter), STATE-01, STATE-05"""
    if state == "empty":
        return {
            "screen_id": "STATE-01",
            "state": "empty",
            "message": "나의 첫 기록을 기다려요",
            "sub_message": "영수증이 없어도 괜찮아요. 날짜를 모르겠다면 '미등록'으로 남겨 두어도 돼요.",
            "counts": {"all": 0, "스킨케어": 0, "색조": 0, "향수": 0},
            "items": [],
        }

    all_active = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status != "archived")
        .all()
    )
    counts = {
        "all": len(all_active),
        "스킨케어": sum(1 for p in all_active if p.category == "스킨케어"),
        "색조": sum(1 for p in all_active if p.category == "색조"),
        "향수": sum(1 for p in all_active if p.category == "향수"),
    }

    filtered = all_active
    if category != "all":
        filtered = [p for p in filtered if p.category == category]
    if status != "all":
        filtered = [p for p in filtered if p.status == status]
    if ingredient:
        filtered = [
            p for p in filtered
            if any(ingredient in ing for ing in (p.main_ingredients or []))
        ]
    if q:
        q_lower = q.lower()
        filtered = [
            p for p in filtered
            if q_lower in p.name.lower()
            or q_lower in p.brand.lower()
            or any(q_lower in ing.lower() for ing in (p.main_ingredients or []))
        ]

    items = [serialize_owned_product(p, db) for p in filtered]

    if sort == "deadline":
        items.sort(key=lambda x: (x["calculated_deadline"] is None, x["calculated_deadline"] or "9999-12-31"))
    elif sort == "recent":
        items.sort(key=lambda x: x["purchase_date"] or "0000-01-01", reverse=True)
    elif sort == "name":
        items.sort(key=lambda x: x["name"])

    if state == "network-error":
        return {
            "screen_id": "STATE-05",
            "state": "network-error",
            "banner": {
                "title": "연결이 잠시 끊어졌어요",
                "description": "네트워크를 확인하고 다시 시도해 주세요. 직전 상태는 캐시 목록으로 보여드려요.",
                "last_synced_at": "2026.10.29 21:10",
                "read_only": True,
            },
            "counts": counts,
            "items": items[:3],
        }

    return {
        "screen_id": "VAN-01",
        "counts": counts,
        "applied_filters": {
            "category": category,
            "status": status,
            "ingredient": ingredient,
            "q": q,
            "sort": sort,
        },
        "total_filtered": len(items),
        "items": items,
    }


@router.get("/owned/{owned_code}")
def get_owned_product_detail(
    owned_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 PROD-01 (/owned/OWN-101) 및 미개봉 상세 PROD-04 (/owned/OWN-103?status=unopened)"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    same_product_others = (
        db.query(OwnedProduct)
        .filter(
            OwnedProduct.user_id == current_user.id,
            OwnedProduct.name == product.name,
            OwnedProduct.code != product.code,
            OwnedProduct.status != "archived",
        )
        .all()
    )

    data = serialize_owned_product(product, db)
    data["screen_id"] = "PROD-04" if product.status == "unopened" else "PROD-01"
    data["same_product_in_vanity_count"] = len(same_product_others)
    return data


@router.put("/owned/{owned_code}")
def update_owned_product(
    owned_code: str,
    payload: OwnedProductUpdate,
    simulate_state: Optional[str] = Query(default=None, description="retry-pending | session-expired (STATE-06, STATE-08 재현용)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 PROD-02 (/owned/OWN-101/edit), STATE-06 (재시도/초안유지), STATE-08 (세션만료 초안보관)"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    # 초안 데이터 우선 보존 (입력 유실 방지)
    product.draft_payload = payload.model_dump(mode="json", exclude_none=True)
    db.commit()

    if simulate_state == "retry-pending":
        return {
            "screen_id": "STATE-06",
            "state": "retry-pending",
            "idempotency_key": payload.idempotency_key or "SAVE-101",
            "message": "이전 저장 시도가 완료되지 않았어요. 입력은 유지됐고 원래 같은 내용으로 다시 저장 중이에요.",
            "preserved_draft": product.draft_payload,
        }

    if simulate_state == "session-expired":
        raise HTTPException(
            status_code=401,
            detail={
                "screen_id": "STATE-08",
                "state": "session-expired",
                "message": "로그인이 만료되었어요. 작성 중이던 내용은 버리지 않고 보관했어요.",
                "preserved_draft": product.draft_payload,
                "return_to": f"/owned/{owned_code}/edit",
            },
        )

    for field in [
        "brand", "name", "category", "volume", "main_ingredients",
        "purchase_date", "opened_date", "printed_expiry_date",
        "pao_months", "remaining_percent", "purchase_price", "memo"
    ]:
        val = getattr(payload, field)
        if val is not None:
            setattr(product, field, val)

    if product.opened_date and product.status == "unopened":
        product.status = "in_use"

    deadline, basis = calculate_product_deadline(
        status=product.status,
        opened_date=product.opened_date,
        printed_expiry_date=product.printed_expiry_date,
        pao_months=product.pao_months,
    )
    product.calculated_deadline = deadline
    product.deadline_basis = basis
    product.last_idempotency_key = payload.idempotency_key
    product.draft_payload = None

    db.commit()
    db.refresh(product)
    return {
        "screen_id": "PROD-02",
        "message": "제품 정보가 저장되었어요.",
        "product": serialize_owned_product(product, db),
    }


@router.post("/owned/{owned_code}/open")
def register_open_date(
    owned_code: str,
    payload: OpenProductRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 PROD-03 (/owned/OWN-103/open): 미개봉 제품의 개봉일 등록 및 사용기한 자동 계산"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    product.status = "in_use"
    product.opened_date = payload.opened_date
    if payload.pao_months is not None:
        product.pao_months = payload.pao_months

    deadline, basis = calculate_product_deadline(
        status="in_use",
        opened_date=product.opened_date,
        printed_expiry_date=product.printed_expiry_date,
        pao_months=product.pao_months,
    )
    product.calculated_deadline = deadline
    product.deadline_basis = basis
    db.commit()
    db.refresh(product)

    return {
        "screen_id": "PROD-03",
        "message": "개봉일이 저장되었어요. 더 이른 날짜 기준으로 기한 알림을 보내드려요.",
        "product": serialize_owned_product(product, db),
    }


@router.delete("/owned/{owned_code}")
def delete_owned_product(
    owned_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 PROD-01 하단 '이 보유 기록을 삭제할까요?' (단순 오등록 영구 삭제 - 폐기 보관함과 구분)"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    db.delete(product)
    db.commit()
    return {
        "deleted_code": owned_code,
        "message": "보유 기록이 삭제되었어요. 다 쓴 제품은 삭제 대신 '다 썼어요 · 폐기 기록'으로 보관함에 남길 수 있어요.",
    }
