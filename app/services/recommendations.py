"""
내 기록 기반 추천(REC-01) · 계절 케어(SEA-01)

원칙 (기획안 'MY RECORD FIRST')
 1) 광고·유행이 아니라 내 평가(만족도·피부 궁합·재구매 의향)로 점수를 매긴다.
 2) 같은 점수면 '이미 가지고 있고 남은 양이 있는 제품'을 먼저 — 새로 사기 전에 있는 것부터.
 3) 맞지 않았던 제품의 성분 중, 잘 맞았던 제품에는 없는 성분을 '확인할 성분'으로 보여준다(판단이 아닌 참고).
 4) 평가가 하나도 없으면 추천하지 않고 '추천을 준비하고 있어요' 상태를 돌려준다.
"""
from collections import defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import CatalogProduct, CommunityPost, Evaluation, OwnedProduct, User

FIT_SCORE = {"잘 맞아요": 0.5, "보통": 0.0, "맞지 않아요": -2.0}
REPURCHASE_SCORE = {"네, 있어요": 1.0, "고민 중이에요": 0.3, "아니요": -1.0}


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def latest_evaluations(db: Session, user: User) -> List[Tuple[OwnedProduct, Evaluation]]:
    rows = []
    for p in db.query(OwnedProduct).filter(OwnedProduct.user_id == user.id).all():
        ev = (
            db.query(Evaluation).filter(Evaluation.owned_product_id == p.id)
            .order_by(Evaluation.evaluated_date.desc(), Evaluation.id.desc()).first()
        )
        if ev:
            rows.append((p, ev))
    return rows


def score(ev: Evaluation) -> float:
    return float(ev.rating) + REPURCHASE_SCORE.get(ev.repurchase_intent, 0) + FIT_SCORE.get(ev.skin_fit, 0)


def build_recommendations(db: Session, user: User, serialize) -> dict:
    rows = latest_evaluations(db, user)
    good = [(p, e) for p, e in rows if e.skin_fit != "맞지 않아요" and e.rating >= 4.0]
    bad = [(p, e) for p, e in rows if e.skin_fit == "맞지 않아요" or e.rating <= 2.0]

    if not good:
        return {
            "state": "insufficient-records",
            "title": "추천을 준비하고 있어요",
            "message": "만족도 4점 이상인 평가가 쌓이면 내 기록을 바탕으로 추천해요. 먼저 사용 중인 제품을 평가해 보세요.",
            "primary_recommendation": None,
            "repurchase_candidates": [],
            "watch_ingredients": [],
            "catalog_suggestions": [],
            "evaluation_targets": [
                serialize(p) for p in db.query(OwnedProduct)
                .filter(OwnedProduct.user_id == user.id, OwnedProduct.status == "in_use").all()
            ][:3],
        }

    def rank_key(pe):
        p, e = pe
        in_hand = p.status != "archived" and (p.remaining_percent or 0) > 0
        return (score(e), in_hand, e.evaluated_date)

    good.sort(key=rank_key, reverse=True)
    top_p, top_e = good[0]
    if top_p.status != "archived" and (top_p.remaining_percent or 0) > 0:
        reason = (f"{top_e.evaluated_date.strftime('%m.%d')} 평가에서 {top_e.rating:.1f}점 · {top_e.skin_fit}"
                  f"{' · 재구매 의향' if top_e.repurchase_intent == '네, 있어요' else ''}을 남겼어요. "
                  f"아직 {top_p.remaining_percent}% 남아 있어 새로 사기 전에 이 제품부터 확인해요.")
    else:
        reason = f"다 쓴 제품 중 {top_e.rating:.1f}점 · {top_e.skin_fit}으로 기록한 제품이에요. 다시 구매를 고려해 볼 만해요."

    repurchase = [
        {**serialize(p), "latest_rating": e.rating, "skin_fit": e.skin_fit}
        for p, e in good if p.status == "archived" and e.repurchase_intent == "네, 있어요"
    ]

    good_ings = {i for p, _ in good for i in (p.main_ingredients or [])}
    watch: Dict[str, List[str]] = defaultdict(list)
    for p, _ in bad:
        for ing in p.main_ingredients or []:
            if ing not in good_ings:
                watch[ing].append(p.name)

    owned_keys = {(_norm(p.brand), _norm(p.name)) for p, _ in rows} | {
        (_norm(p.brand), _norm(p.name)) for p in db.query(OwnedProduct).filter(OwnedProduct.user_id == user.id).all()
    }
    suggestions = []
    for c in db.query(CatalogProduct).all():
        if (_norm(c.brand), _norm(c.name)) in owned_keys:
            continue
        ings = set(c.main_ingredients or [])
        shared = sorted(ings & good_ings)
        if shared and not (ings & set(watch)):
            suggestions.append({
                "catalog_code": c.code, "brand": c.brand, "name": c.name, "category": c.category,
                "shared_ingredients": shared,
                "note": f"잘 맞았던 제품과 {', '.join(shared)} 성분이 겹쳐요.",
            })

    return {
        "state": "ready",
        "primary_recommendation": {"badge": "MY RECORD FIRST", "product": serialize(top_p), "reason": reason},
        "repurchase_candidates": repurchase,
        "watch_ingredients": [
            {"ingredient": k, "from_products": v, "note": "맞지 않았던 제품에만 있던 성분이에요. 원인이라는 뜻은 아니에요."}
            for k, v in watch.items()
        ],
        "catalog_suggestions": suggestions[:3],
        "evidence_used": {
            "satisfaction": f"최근 평가와 재구매 의향 ({top_e.rating:.1f} · {top_e.skin_fit})",
            "skin_profile": f"직접 선택한 {user.skin_type} · {', '.join(user.skin_concerns or []) or '고민 미선택'}",
            "mismatched_history": ", ".join(f"{p.name} · {e.rating:.1f} / {e.skin_fit}" for p, e in bad) or "없음",
            "disclaimer": "성분만으로 안전성이나 피부 적합도를 예측하지 않아요.",
        },
    }


def community_reference(db: Session) -> Optional[dict]:
    """커뮤니티에 '별점 공개'로 올라온 글을 제품별로 실제 집계 (예시 숫자를 지어내지 않음)."""
    agg: Dict[str, List[float]] = defaultdict(list)
    for post in db.query(CommunityPost).filter(CommunityPost.is_draft == False, CommunityPost.shared_rating.isnot(None)).all():  # noqa: E712
        name = (post.related_product_summary or {}).get("name")
        if name:
            agg[name].append(float(post.shared_rating))
    if not agg:
        return None
    name, ratings = max(agg.items(), key=lambda kv: (len(kv[1]), sum(kv[1]) / len(kv[1])))
    return {
        "name": name,
        "average_rating": round(sum(ratings) / len(ratings), 1),
        "review_count": len(ratings),
        "notice": f"별점을 공개한 커뮤니티 글 {len(ratings)}건의 평균이에요. 개인별 반응은 다를 수 있어요.",
    }


def seasonal_products(db: Session, user: User, keywords: List[str]) -> List[Tuple[OwnedProduct, List[str]]]:
    out = []
    for p in db.query(OwnedProduct).filter(OwnedProduct.user_id == user.id, OwnedProduct.status != "archived").all():
        hits = [ing for ing in (p.main_ingredients or []) if any(k in ing for k in keywords)]
        if hits:
            out.append((p, hits))
    out.sort(key=lambda x: (-len(x[1]), x[0].calculated_deadline or date.max))
    return out
