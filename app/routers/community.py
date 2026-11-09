from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, Evaluation, CommunityPost, CommunityComment
from app.schemas import CommunityPostCreate, CommunityCommentCreate
from app.utils.security import get_current_user
from app.routers.vanity import serialize_owned_product
from app.utils.codes import next_code
from app.utils.deadline import get_today
from app.utils.seasons import SEASONS, season_of
from app.utils.timeutil import format_label
from app.services.recommendations import build_recommendations, community_reference, seasonal_products

router = APIRouter(tags=["F · 부가 기능 · 추천 · 계절 케어 · 커뮤니티 (REC/SEA/COM)"])


@router.get("/recommendations")
def get_personal_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REC-01 (/recommendations): 내 평가 기록으로 점수를 매겨 추천 (시드 제품 코드에 의존하지 않음)"""
    ser = lambda p: serialize_owned_product(p, db)  # noqa: E731
    rec = build_recommendations(db, current_user, ser)
    rec.update({
        "screen_id": "REC-01",
        "title": "유행보다, 나에게 남은 좋은 기록.",
        "insufficient_record_rule": "기록이 충분하지 않을 때는 '추천을 준비하고 있어요'로 표시하고 내 평가를 먼저 안내해요.",
        "community_reference": community_reference(db),
    })
    return rec


@router.get("/seasonal/{season}")
def get_seasonal_care_guide(
    season: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 SEA-01 (/seasonal/autumn | spring | summer | winter | current): 계절별 안내 + 해당 성분이 있는 내 보유 제품"""
    key = season_of(get_today()) if season == "current" else season
    if key not in SEASONS:
        raise HTTPException(status_code=404, detail="season 은 spring · summer · autumn · winter · current 중 하나예요.")
    cfg = SEASONS[key]
    related = seasonal_products(db, current_user, cfg["ingredients"])
    matched_ings = sorted({i for _, hits in related for i in hits})
    concerns = [c for c in (current_user.skin_concerns or [])]
    why = (
        f"선택한 관심사 '{', '.join(concerns)}'과 " if concerns else ""
    ) + (f"보유 제품에 기록된 {'·'.join(matched_ings)}을 기준으로 정리했어요." if matched_ings
         else f"{cfg['label']}에 자주 보는 성분이 내 화장대에는 아직 없어요. 새로 사기 전에 내 기록부터 확인해요.")
    return {
        "screen_id": "SEA-01",
        "season": key,
        "season_label": cfg["label"],
        "title": cfg["title"],
        "why_shown": why,
        "profile_match": [c for c in concerns if c in cfg["focus_concerns"]],
        "tips": cfg["tips"],
        "related_owned_products": [{**serialize_owned_product(p, db), "matched_ingredients": hits} for p, hits in related],
        "medical_disclaimer": "일반적인 정보 안내예요. 진단이나 치료를 위한 안내가 아니며 개인별 반응은 다를 수 있어요.",
    }


@router.get("/community")
def list_community_posts(
    type: str = Query(default="all", description="all | 질문 | 추천 | 후기"),
    q: Optional[str] = Query(default=None, description="궁금한 제품이나 이야기 검색"),
    db: Session = Depends(get_db),
):
    """화면 COM-01 (/community?type=all): 공개 작성된 커뮤니티 게시글 목록 조회"""
    posts = (
        db.query(CommunityPost)
        .filter(CommunityPost.is_draft == False)
        .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
        .all()
    )
    if type != "all":
        posts = [p for p in posts if p.post_type == type]
    if q:
        q_low = q.lower()
        posts = [p for p in posts if q_low in p.title.lower() or q_low in p.body.lower()]

    return {
        "screen_id": "COM-01",
        "title": "가볍게 묻고, 경험을 나누어요.",
        "privacy_notice": "비공개 개인 평가는 자동으로 공개되지 않아요.",
        "items": [
            {
                "code": p.code,
                "post_type": p.post_type,
                "title": p.title,
                "excerpt": p.body[:80],
                "author_nickname": p.user.nickname if p.user else "탈퇴한 사용자",
                "created_label": p.created_label or format_label(p.created_at),
                "comment_count": len(p.comments),
                "like_count": p.like_count,
            }
            for p in posts
        ],
    }


@router.get("/community/{post_code}")
def get_community_post_detail(
    post_code: str,
    db: Session = Depends(get_db),
):
    """화면 COM-02 (/community/P-01): 게시글 상세 및 댓글 조회"""
    post = db.query(CommunityPost).filter(CommunityPost.code == post_code, CommunityPost.is_draft == False).first()  # noqa: E712
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없어요.")

    return {
        "screen_id": "COM-02",
        "code": post.code,
        "post_type": post.post_type,
        "title": post.title,
        "body": post.body,
        "author_nickname": post.user.nickname if post.user else "탈퇴한 사용자",
        "created_label": post.created_label or format_label(post.created_at),
        "shared_quote": post.shared_quote,
        "shared_rating": post.shared_rating,
        "shared_reactions": post.shared_reactions,
        "related_product_summary": post.related_product_summary,
        "like_count": post.like_count,
        "comments": [
            {
                "code": c.code,
                "author_nickname": c.author_nickname,
                "body": c.body,
                "created_label": c.created_label or format_label(c.created_at),
            }
            for c in post.comments
        ],
    }


@router.post("/community", status_code=201)
def create_community_post(
    payload: CommunityPostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 COM-03 (/community/new?evaluation=EVAL-101): 내 비공개 평가에서 선택한 항목만 공개 게시"""
    if not payload.is_draft and not payload.confirmed_public:
        raise HTTPException(status_code=400, detail="공개 범위 확인 체크박스에 동의해 주세요.")

    product_summary = None
    shared_quote = None
    shared_rating = None
    shared_reactions = []

    if payload.related_owned_code:
        owned = (
            db.query(OwnedProduct)
            .filter(OwnedProduct.code == payload.related_owned_code, OwnedProduct.user_id == current_user.id)
            .first()
        )
        if owned:
            product_summary = {
                "brand": owned.brand,
                "name": owned.name,
                "volume": owned.volume,
                "category": owned.category,
            }
            latest_eval = (
                db.query(Evaluation)
                .filter(Evaluation.owned_product_id == owned.id)
                .order_by(Evaluation.evaluated_date.desc())
                .first()
            )
            if latest_eval:
                if payload.include_quote:
                    shared_quote = latest_eval.memo
                if payload.include_rating:
                    shared_rating = latest_eval.rating
                if payload.include_reactions:
                    shared_reactions = latest_eval.reactions

    post = CommunityPost(
        code=next_code(db, CommunityPost, "P", start=1, width=2),
        user_id=current_user.id,
        post_type=payload.post_type,
        title=payload.title,
        body=payload.body,
        related_owned_code=payload.related_owned_code,
        related_product_summary=product_summary,
        shared_quote=shared_quote,
        shared_rating=shared_rating,
        shared_reactions=shared_reactions,
        is_draft=payload.is_draft,
        created_label=None,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return {
        "screen_id": "COM-03",
        "next_screen": "COM-02",
        "message": "선택한 범위만 커뮤니티에 공개되었어요. 원래 개인 평가의 비공개 설정은 바뀌지 않아요.",
        "post_code": post.code,
    }


@router.delete("/community/{post_code}")
def delete_community_post(
    post_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 COM-02 ('이 글을 삭제할까요?'): 게시글 삭제(원본 개인 평가는 유지됨)"""
    post = (
        db.query(CommunityPost)
        .filter(CommunityPost.code == post_code, CommunityPost.user_id == current_user.id)
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="삭제할 게시글을 찾을 수 없어요.")
    db.delete(post)
    db.commit()
    return {
        "deleted_code": post_code,
        "message": "게시글이 삭제되었어요. 원본 비공개 개인 평가는 그대로 유지돼요.",
    }


@router.post("/community/{post_code}/comments", status_code=201)
def create_comment(
    post_code: str,
    payload: CommunityCommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 COM-02 하단 댓글 등록"""
    post = db.query(CommunityPost).filter(CommunityPost.code == post_code).first()
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없어요.")

    comment = CommunityComment(
        code=next_code(db, CommunityComment, "C", start=1, width=2),
        post_id=post.id,
        user_id=current_user.id,
        author_nickname=current_user.nickname,
        body=payload.body,
        created_label=None,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "code": comment.code,
        "author_nickname": comment.author_nickname,
        "body": comment.body,
        "created_label": format_label(comment.created_at),
    }
