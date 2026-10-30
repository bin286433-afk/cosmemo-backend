from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, Evaluation, CommunityPost, CommunityComment
from app.schemas import CommunityPostCreate, CommunityCommentCreate
from app.utils.security import get_current_user
from app.routers.vanity import serialize_owned_product

router = APIRouter(tags=["F · 부가 기능 · 추천 · 계절 케어 · 커뮤니티 (REC/SEA/COM)"])


@router.get("/recommendations")
def get_personal_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 REC-01 (/recommendations): 내 기록 기반 추천 우선 제시 + 커뮤니티 참고 예시 분리"""
    owned_list = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id)
        .all()
    )
    toner = next((p for p in owned_list if p.code == "OWN-102"), None)
    bad_gel = next((p for p in owned_list if p.code == "OWN-098"), None)

    return {
        "screen_id": "REC-01",
        "title": "유행보다, 나에게 남은 좋은 기록.",
        "primary_recommendation": {
            "badge": "MY RECORD FIRST",
            "product": serialize_owned_product(toner, db) if toner else None,
            "reason": "10.15 평가에서 재구매 의향을 남겼어요. 아직 60% 남아 있어 먼저 보유 제품을 확인해요.",
        },
        "evidence_used": {
            "satisfaction": "최근 평가와 재구매 의향 (5.0 · 잘 맞아요)",
            "skin_profile": f"직접 선택한 {current_user.skin_type} · {', '.join(current_user.skin_concerns)}",
            "mismatched_history": f"{bad_gel.name} · 2.0 / 맞지 않아요 · 따가웠어요" if bad_gel else "없음",
            "disclaimer": "성분만으로 안전성이나 피부 적합도를 예측하지 않아요.",
        },
        "insufficient_record_rule": "기록이 충분하지 않을 때는 '추천을 준비하고 있어요'로 표시하고 내 평가를 먼저 안내해요.",
        "community_reference_example": {
            "name": "소프트 클렌징 밤",
            "average_rating": 4.2,
            "review_count": 12,
            "notice": "예시 후기 12건 · 실제 서비스 집계치가 아니에요. 개인별 반응은 다를 수 있어요.",
        },
    }


@router.get("/seasonal/{season}")
def get_seasonal_care_guide(
    season: str = "autumn",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 SEA-01 (/seasonal/autumn): 계절별 케어 안내 및 관련 보유 제품 연결"""
    cream = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.code == "OWN-101")
        .first()
    )
    return {
        "screen_id": "SEA-01",
        "season": season,
        "title": "찬 바람이 불면, 루틴도 천천히.",
        "why_shown": f"선택한 관심사 '{', '.join(current_user.skin_concerns)}'과 보유 제품에 기록된 판테놀·세라마이드를 기준으로 정리했어요.",
        "tips": [
            {
                "step": "01 · 보습 관련 성분을 확인해요",
                "body": "판테놀·히알루론산·세라마이드는 보습 제품에서 자주 볼 수 있어요. 성분명 하나보다 실제 사용감과 내 기록을 함께 확인해요.",
            },
            {
                "step": "02 · 변화를 메모해요",
                "body": "건조함이나 불편함이 느껴졌다면 사용 시점과 함께 기록해요. 여러 제품을 동시에 바꾸기보다 변화를 구별해 보세요.",
            },
        ],
        "related_owned_products": [serialize_owned_product(cream, db)] if cream else [],
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
        .order_by(CommunityPost.id.asc())
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
                "author_nickname": p.user.nickname if p.user else "지윤",
                "created_label": p.created_label,
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
    post = db.query(CommunityPost).filter(CommunityPost.code == post_code).first()
    if not post:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없어요.")

    return {
        "screen_id": "COM-02",
        "code": post.code,
        "post_type": post.post_type,
        "title": post.title,
        "body": post.body,
        "author_nickname": post.user.nickname if post.user else "지윤",
        "created_label": post.created_label,
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
                "created_label": c.created_label,
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

    next_num = 1 + db.query(CommunityPost).count()
    post = CommunityPost(
        code=f"P-{next_num:02d}",
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
        created_label="2026.10.30 11:00",
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

    next_num = 1 + db.query(CommunityComment).count()
    comment = CommunityComment(
        code=f"C-{next_num:02d}",
        post_id=post.id,
        user_id=current_user.id,
        author_nickname=current_user.nickname,
        body=payload.body,
        created_label="10.30 11:10",
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "code": comment.code,
        "author_nickname": comment.author_nickname,
        "body": comment.body,
        "created_label": comment.created_label,
    }
