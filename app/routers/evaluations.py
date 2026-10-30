from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, Evaluation
from app.schemas import EvaluationCreateUpdate
from app.utils.security import get_current_user
from app.utils.deadline import REFERENCE_TODAY
from app.routers.vanity import serialize_owned_product

router = APIRouter(tags=["D · 개인 평가 · 사용 기한 · 알림 (REV/EXP/NOTI)"])


@router.get("/evaluations")
def get_product_evaluations(
    owned: str = Query(default="OWN-101", description="보유 제품 코드 (예: OWN-101)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REV-02 (/evaluations?owned=OWN-101): 제품별 내 평가 이력 타임라인 조회"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    evals = (
        db.query(Evaluation)
        .filter(Evaluation.owned_product_id == product.id)
        .order_by(Evaluation.evaluated_date.desc(), Evaluation.id.desc())
        .all()
    )
    latest = evals[0] if evals else None

    return {
        "screen_id": "REV-02",
        "product": serialize_owned_product(product, db),
        "summary": {
            "latest_rating": latest.rating if latest else None,
            "latest_skin_fit": latest.skin_fit if latest else None,
            "repurchase_intent": latest.repurchase_intent if latest else None,
            "total_count": len(evals),
            "visibility": "모두 비공개",
        },
        "timeline": [
            {
                "code": e.code,
                "rating": e.rating,
                "skin_fit": e.skin_fit,
                "reactions": e.reactions,
                "repurchase_intent": e.repurchase_intent,
                "memo": e.memo,
                "evaluated_date": e.evaluated_date.isoformat(),
                "is_public": e.is_public,
            }
            for e in evals
        ],
    }


@router.post("/owned/{owned_code}/evaluation")
def save_evaluation(
    owned_code: str,
    payload: EvaluationCreateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REV-01 (/owned/OWN-101/evaluation/edit): 개인 평가 비공개 저장"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    next_num = 101 + db.query(Evaluation).count()
    ev = Evaluation(
        code=f"EVAL-{next_num}",
        user_id=current_user.id,
        owned_product_id=product.id,
        rating=payload.rating,
        skin_fit=payload.skin_fit,
        reactions=payload.reactions,
        repurchase_intent=payload.repurchase_intent,
        memo=payload.memo,
        evaluated_date=payload.evaluated_date,
        is_public=False,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    return {
        "screen_id": "REV-01",
        "next_screen": "REV-02",
        "message": "이 평가는 나만 볼 수 있도록 비공개로 저장되었어요.",
        "evaluation": {
            "code": ev.code,
            "rating": ev.rating,
            "skin_fit": ev.skin_fit,
            "reactions": ev.reactions,
            "repurchase_intent": ev.repurchase_intent,
            "memo": ev.memo,
            "evaluated_date": ev.evaluated_date.isoformat(),
            "is_public": ev.is_public,
        },
    }


@router.get("/deadlines")
def get_deadlines_management(
    tab: str = Query(default="within30", description="expired | within30 | later | unknown"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 EXP-01 (/deadlines?tab=within30): 기한 초과 / 30일 이내 / 이후 / 미확인 분류"""
    active_products = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status != "archived")
        .all()
    )
    items = [serialize_owned_product(p, db) for p in active_products]

    expired = [i for i in items if i["status"] == "expired" or (i["d_day"] is not None and i["d_day"] < 0)]
    within30 = [i for i in items if i["status"] != "expired" and i["d_day"] is not None and 0 <= i["d_day"] <= 30]
    later = [i for i in items if i["status"] != "expired" and i["d_day"] is not None and i["d_day"] > 30]
    unknown = [i for i in items if i["calculated_deadline"] is None]

    tab_map = {
        "expired": expired,
        "within30": within30,
        "later": later,
        "unknown": unknown,
    }

    return {
        "screen_id": "EXP-01",
        "reference_date": REFERENCE_TODAY.isoformat(),
        "total_active": len(items),
        "counts": {
            "expired": len(expired),
            "within30": len(within30),
            "later": len(later),
            "unknown": len(unknown),
        },
        "current_tab": tab,
        "items": tab_map.get(tab, within30),
        "unknown_items_preview": unknown,
        "calculation_rule_note": "① 인쇄 사용 기한 ② 개봉일 + 확인한 PAO 중 둘 다 알면 더 이른 날을 사용해요. 미개봉 제품은 PAO를 계산하지 않아요.",
    }
