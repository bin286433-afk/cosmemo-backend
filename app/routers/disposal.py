from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, DisposalRecord, CollectionSpot, CatalogProduct, Evaluation
from app.schemas import DisposalCreateRequest
from app.utils.security import get_current_user
from app.routers.vanity import serialize_owned_product

router = APIRouter(tags=["E · 비우기 · 분리배출 · 다음 구매 (DIS/ARC/BUY)"])


@router.post("/owned/{owned_code}/end")
def record_product_end(
    owned_code: str,
    payload: DisposalCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 DIS-01 (/owned/OWN-101/end): 다 썼어요·폐기 기록 저장 후 분리배출 안내로 이동"""
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned_code, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")
    if product.status == "archived":
        raise HTTPException(status_code=409, detail="이미 지난 제품 보관함에 있는 제품이에요.")

    existing = db.query(DisposalRecord).filter(DisposalRecord.owned_product_id == product.id).first()
    if existing:
        existing.reason = payload.reason
        existing.ended_date = payload.ended_date
        existing.remaining_at_end = payload.remaining_at_end
        existing.memo = payload.memo
        record = existing
    else:
        record = DisposalRecord(
            code=f"DISP-{product.code.split('-')[-1]}",
            user_id=current_user.id,
            owned_product_id=product.id,
            reason=payload.reason,
            ended_date=payload.ended_date,
            remaining_at_end=payload.remaining_at_end,
            memo=payload.memo,
            disposal_completed=False,
        )
        db.add(record)

    if payload.remaining_at_end.strip().startswith("0%"):
        product.remaining_percent = 0
    db.commit()
    db.refresh(record)

    return {
        "screen_id": "DIS-01",
        "next_screen": "DIS-02",
        "disposal_code": record.code,
        "owned_code": product.code,
        "reason": record.reason,
        "ended_date": record.ended_date.isoformat(),
        "remaining_at_end": record.remaining_at_end,
    }


@router.get("/disposal/{disposal_code}/guide")
def get_disposal_guide(
    disposal_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 DIS-02 (/disposal/DISP-101/guide): 부위별 재질 분리배출 안내"""
    owned_num = disposal_code.split("-")[-1]
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == f"OWN-{owned_num}", OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="분리배출 안내를 찾을 수 없어요.")

    guide = (
        product.catalog.disposal_guide
        if (product and product.catalog and product.catalog.disposal_guide)
        else [
            {"step": "#1", "part": "본체 · PP 플라스틱", "guide": "잔여물을 닦아낸 뒤 물로 헹궈 주세요."},
            {"step": "#2", "part": "뚜껑 · PP 플라스틱", "guide": "본체에서 분리해 재질별로 배출해요."},
            {"step": "#3", "part": "레이어 · 복합 재질", "guide": "라벨을 떼어내고 접착제까지 닦아요."},
        ]
    )

    return {
        "screen_id": "DIS-02",
        "disposal_code": disposal_code,
        "product": serialize_owned_product(product, db) if product else None,
        "region_notice": "지역마다 배출 기준이 달라요. 거주지 지자체 기준을 먼저 확인해요.",
        "steps": guide,
        "leftover_tip": "내용물이 남았다면 하수구에 바로 흘려보내지 말고 키친타월이나 신문지에 흡수시켜 일반쓰레기로 버려요.",
    }


@router.post("/disposal/{disposal_code}/complete")
def complete_disposal_and_archive(
    disposal_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 DIS-04 (/disposal/DISP-101/complete): 분리배출 완료 및 지난 제품 보관함으로 이동"""
    owned_num = disposal_code.split("-")[-1]
    product = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == f"OWN-{owned_num}", OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="보유 제품을 찾을 수 없어요.")

    if not product.disposal:
        raise HTTPException(status_code=409, detail="먼저 사용 종료 사유를 기록해 주세요. (POST /owned/{code}/end)")

    product.status = "archived"
    product.remaining_percent = 0
    product.disposal.disposal_completed = True

    db.commit()
    db.refresh(product)

    latest_eval = (
        db.query(Evaluation).filter(Evaluation.owned_product_id == product.id)
        .order_by(Evaluation.evaluated_date.desc(), Evaluation.id.desc()).first()
    )
    active_cnt = db.query(OwnedProduct).filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status != "archived").count()
    archived_cnt = db.query(OwnedProduct).filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status == "archived").count()

    return {
        "screen_id": "DIS-04",
        "disposal_code": disposal_code,
        "title": "잘 썼고, 잘 비웠어요",
        "message": f"{product.name}을 지난 제품 보관함으로 옮겼어요. 기록은 사라지지 않아요.",
        "summary": {
            "reason": f"{product.disposal.reason} · 잔량 0%",
            "completed_date": product.disposal.ended_date.isoformat(),
            "evaluation_preserved": f"{latest_eval.rating} · {latest_eval.skin_fit} · 유지됨" if latest_eval else "평가 기록 없음",
            "remaining_active_notice": f"활성 {active_cnt}개 / 지난 제품 {archived_cnt}개",
        },
    }


@router.get("/collection")
def list_collection_spots(
    region: Optional[str] = Query(default=None, description="동네·매장명·키워드 검색 (예: 기흥구)"),
    db: Session = Depends(get_db),
):
    """화면 DIS-03 (/collection?region=example): 공병 수거처 안내 (위치 권한 없이도 수동 검색 가능)"""
    spots = db.query(CollectionSpot).all()
    if region:
        spots = [
            s for s in spots
            if region in s.region or region in s.name or region in s.spot_type
        ]
    return {
        "screen_id": "DIS-03",
        "location_permission_required": False,
        "notice": "방문 전 운영 여부를 확인해 주세요. 지점별 수거 품목과 중단 여부는 매장에 확인해야 해요.",
        "spots": [
            {
                "code": s.code,
                "name": s.name,
                "spot_type": s.spot_type,
                "region": s.region,
                "hours": s.hours,
                "accepted_items": s.accepted_items,
                "note": s.note,
            }
            for s in spots
        ],
    }


@router.get("/archive")
def list_archived_products(
    reason: str = Query(default="all", description="all | 다 썼어요 | 기한 초과 | 맞지 않음"),
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 ARC-01 (/archive): 지난 제품 보관함 조회"""
    archived = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status == "archived")
        .all()
    )
    results = []
    for p in archived:
        disp_reason = p.disposal.reason if p.disposal else "다 썼어요"
        if reason != "all" and reason not in disp_reason:
            continue
        if q and (q.lower() not in p.name.lower() and q.lower() not in p.brand.lower()):
            continue
        item = serialize_owned_product(p, db)
        item["archive_reason"] = disp_reason
        item["ended_date"] = p.disposal.ended_date.isoformat() if p.disposal else None
        results.append(item)

    return {
        "screen_id": "ARC-01",
        "title": "다 쓴 제품이 남긴 나만의 취향.",
        "total_count": len(results),
        "items": results,
    }


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


@router.get("/precheck")
def precheck_before_purchase(
    q: str = Query(default="진정 토너", description="구매 전 검색어 (예: 진정 토너, 달빛 앰플)"),
    search_by: str = Query(default="제품명", description="제품명 | 카테고리 | 주요 성분"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    화면 BUY-01 / STATE-02: 사려는 제품과 '같은 제품 / 비슷한 제품(같은 카테고리+겹치는 성분)'을 내 화장대에서 찾고,
    과거에 맞지 않았던 제품 중 성분이 겹치는 것만 경고합니다.
    """
    q_clean = q.strip()
    q_norm = _norm(q_clean)
    catalogs = db.query(CatalogProduct).all()
    if search_by == "주요 성분":
        matched_cats = [c for c in catalogs if any(q_norm in _norm(i) for i in (c.main_ingredients or []))]
    elif search_by == "카테고리":
        matched_cats = [c for c in catalogs if q_norm == _norm(c.category)]
    else:
        matched_cats = [c for c in catalogs if q_norm in _norm(c.name) or q_norm in _norm(c.brand) or _norm(c.name) in q_norm]
    target = matched_cats[0] if matched_cats else None
    target_ings = set(target.main_ingredients or []) if target else set()

    owned_all = db.query(OwnedProduct).filter(OwnedProduct.user_id == current_user.id).all()
    same, similar = [], []
    for p in owned_all:
        if p.status == "archived":
            continue
        is_same = (target and (p.catalog_id == target.id or (_norm(p.brand) == _norm(target.brand) and _norm(p.name) == _norm(target.name)))) \
            or (not target and (q_norm in _norm(p.name) or q_norm in _norm(p.brand)))
        if is_same:
            same.append(p)
            continue
        shared = sorted(set(p.main_ingredients or []) & target_ings)
        if target and p.category == target.category and shared:
            similar.append((p, shared))

    warnings = []
    for p in owned_all:
        shared = sorted(set(p.main_ingredients or []) & target_ings) if target else []
        for ev in p.evaluations:
            if ev.skin_fit == "맞지 않아요" and (shared or (target and p.category == target.category)):
                warnings.append({
                    "owned_code": p.code, "brand": p.brand, "name": p.name, "rating": ev.rating,
                    "skin_fit": ev.skin_fit, "reactions": ev.reactions, "shared_ingredients": shared,
                    "warning": f"{p.name} · {ev.rating} / {ev.skin_fit}."
                               + (f" {', '.join(shared)} 성분이 겹쳐요. 사기 전에 전체 성분을 확인해요." if shared else " 같은 카테고리 제품이에요."),
                })

    if not target and not same:
        return {
            "screen_id": "STATE-02", "state": "no-results", "query": q,
            "title": "찾는 제품이 아직 없어요",
            "message": f"'{q}'로 찾은 제품과 보유 기록이 없어요. 브랜드명을 빼거나 다른 제품명으로 검색해 보세요.",
            "candidate_catalog": None, "same_owned": [], "similar_owned": [], "mismatched_warnings": [],
        }

    return {
        "screen_id": "BUY-01",
        "query": q,
        "candidate_catalog": {
            "catalog_code": target.code, "brand": target.brand, "name": target.name, "category": target.category,
            "volume": target.volume, "main_ingredients": target.main_ingredients,
        } if target else None,
        "other_candidates": [{"catalog_code": c.code, "brand": c.brand, "name": c.name} for c in matched_cats[1:5]],
        "same_owned": [serialize_owned_product(p, db) for p in same],
        "similar_owned": [serialize_owned_product(p, db) for p in same] + [
            {**serialize_owned_product(p, db), "shared_ingredients": sh} for p, sh in similar
        ],
        "mismatched_warnings": warnings,
    }


@router.get("/precheck/compare")
def compare_candidate_with_owned(
    candidate: str = Query(default="CAT-02", description="구매 고민 중인 카탈로그 코드"),
    owned: str = Query(default="OWN-102", description="비교할 내 보유 제품 코드"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 BUY-02: 구매 후보 vs 보유 제품 나란히 비교 — 같은 제품인지 실제로 판정해 배너 문구 결정"""
    cat = db.query(CatalogProduct).filter(CatalogProduct.code == candidate).first()
    own = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.code == owned, OwnedProduct.user_id == current_user.id)
        .first()
    )
    if not cat or not own:
        raise HTTPException(status_code=404, detail="비교할 제품 정보를 찾을 수 없어요.")

    same = own.catalog_id == cat.id or (_norm(own.brand) == _norm(cat.brand) and _norm(own.name) == _norm(cat.name))
    shared = sorted(set(own.main_ingredients or []) & set(cat.main_ingredients or []))
    status_word = "보관함에 있는" if own.status == "archived" else "이미 사용 중인"
    if same:
        banner = f"{status_word} 같은 제품이에요. 브랜드·제품명이 같아요. 남은 양({own.remaining_percent}%)과 지난 평가를 확인해 보세요."
    elif shared:
        banner = f"비슷한 제품을 가지고 있어요. {', '.join(shared)} 성분이 겹쳐요."
    else:
        banner = "겹치는 주요 성분이 없는 다른 제품이에요."

    own_serialized = serialize_owned_product(own, db)
    return {
        "screen_id": "BUY-02",
        "is_same_product": same,
        "shared_ingredients": shared,
        "banner": banner,
        "candidate": {
            "catalog_code": cat.code, "brand": cat.brand, "name": cat.name, "category": cat.category,
            "volume": cat.volume, "main_ingredients": cat.main_ingredients,
            "remaining_percent": "새 제품", "deadline": "개봉일 등록 예정",
        },
        "owned": own_serialized,
        "disclaimer": "유사 성분은 피부 적합도 점수가 아니에요. 전체 성분·배합·사용 환경은 다를 수 있어요.",
    }
