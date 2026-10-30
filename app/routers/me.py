from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, OwnedProduct, Evaluation, Notification, CommunityPost
from app.schemas import NotificationSettingUpdate, AccountUpdateRequest, AccountDeleteRequest
from app.utils.security import get_current_user

router = APIRouter(tags=["G · 마이 · 알림 환경 · 개인정보 (MY/NOTI)"])


@router.get("/notifications")
def list_notifications(
    category: str = Query(default="전체", description="전체 | 사용 기한 | 계절 안내 | 평가 기록"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 NOTI-01 (/notifications): 알림함 조회"""
    notis = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.id.asc())
        .all()
    )
    unread_count = sum(1 for n in notis if not n.is_read)
    if category != "전체":
        notis = [n for n in notis if n.category == category]

    return {
        "screen_id": "NOTI-01",
        "unread_count": unread_count,
        "items": [
            {
                "code": n.code,
                "category": n.category,
                "title": n.title,
                "body": n.body,
                "target_path": n.target_path,
                "related_owned_code": n.related_owned_code,
                "is_read": n.is_read,
                "created_label": n.created_label,
            }
            for n in notis
        ],
    }


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 NOTI-01 ('모두 읽음으로 표시')"""
    notis = db.query(Notification).filter(Notification.user_id == current_user.id, Notification.is_read == False).all()
    for n in notis:
        n.is_read = True
    db.commit()
    return {"screen_id": "NOTI-01", "unread_count": 0, "message": "모든 알림을 읽음으로 표시했어요."}


@router.get("/me")
def get_my_page(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 MY-01 (/me): 마이페이지 요약(내 화장대 6, 지난 제품 2, 평가한 제품 4)"""
    active_count = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status != "archived")
        .count()
    )
    archived_count = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == current_user.id, OwnedProduct.status == "archived")
        .count()
    )
    evaluated_product_count = (
        db.query(Evaluation.owned_product_id)
        .filter(Evaluation.user_id == current_user.id)
        .distinct()
        .count()
    )
    my_posts_count = (
        db.query(CommunityPost)
        .filter(CommunityPost.user_id == current_user.id, CommunityPost.is_draft == False)
        .count()
    )

    return {
        "screen_id": "MY-01",
        "profile": {
            "code": current_user.code,
            "nickname": current_user.nickname,
            "email": current_user.email,
            "skin_type": current_user.skin_type,
            "skin_concerns": current_user.skin_concerns,
        },
        "stats": {
            "active_vanity_count": active_count,
            "archived_count": archived_count,
            "evaluated_product_count": evaluated_product_count,
            "my_posts_count": my_posts_count,
        },
        "privacy_notice": "내 기록의 주인은 나예요. 개인 평가는 기본 비공개로 저장돼요.",
    }


@router.get("/me/notifications")
def get_my_notification_settings(
    current_user: User = Depends(get_current_user),
):
    """화면 MY-02 (/me/notifications): 알림 환경 설정 조회"""
    return {
        "screen_id": "MY-02",
        "os_notification_permission": current_user.perm_notification,
        "notify_expiry_enabled": current_user.notify_expiry_enabled,
        "notify_expiry_days": current_user.notify_expiry_days,
        "notify_time": current_user.notify_time,
        "notify_seasonal": current_user.notify_seasonal,
        "notify_community": current_user.notify_community,
        "notify_evaluation": current_user.notify_evaluation,
        "marketing_agreed": current_user.marketing_agreed,
    }


@router.put("/me/notifications")
def update_my_notification_settings(
    payload: NotificationSettingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 MY-02 (/me/notifications): 사용 기한 알림(30일/7일/당일), 선택 알림, 마케팅 수신 분리 저장"""
    current_user.notify_expiry_enabled = payload.notify_expiry_enabled
    current_user.notify_expiry_days = payload.notify_expiry_days
    current_user.notify_time = payload.notify_time
    current_user.notify_seasonal = payload.notify_seasonal
    current_user.notify_community = payload.notify_community
    current_user.notify_evaluation = payload.notify_evaluation
    current_user.marketing_agreed = payload.marketing_agreed
    db.commit()
    return {
        "screen_id": "MY-02",
        "message": "알림 설정이 저장되었어요.",
        "settings": payload.model_dump(),
    }


@router.put("/me/account")
def update_my_account(
    payload: AccountUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 MY-03 (/me/account): 닉네임 및 피부 프로필 변경 저장"""
    current_user.nickname = payload.nickname
    current_user.skin_type = payload.skin_type
    current_user.skin_concerns = payload.skin_concerns
    db.commit()
    return {
        "screen_id": "MY-03",
        "message": "프로필 변경 사항이 저장되었어요.",
        "profile": {
            "email": current_user.email,
            "nickname": current_user.nickname,
            "skin_type": current_user.skin_type,
            "skin_concerns": current_user.skin_concerns,
        },
    }


@router.post("/me/logout")
def logout_current_device():
    """화면 MY-03 ('이 기기에서 로그아웃할까요?'): 계정 데이터는 유지하고 기기 세션만 종료"""
    return {
        "screen_id": "MY-03",
        "next_screen": "AUTH-02",
        "message": "로그아웃되었어요. 저장한 화장품과 평가는 계정에 안전하게 남아 있어요.",
    }


@router.delete("/me/account")
def delete_my_account(
    payload: AccountDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 MY-03 ('계정과 기록을 삭제할까요?'): '탈퇴' 문구 및 체크박스 확인 후 전체 데이터 영구 삭제"""
    if payload.confirm_text.strip() != "탈퇴" or not payload.confirmed_irreversible:
        raise HTTPException(
            status_code=400,
            detail="확인을 위해 '탈퇴'를 정확히 입력하고 복구 불가 안내에 체크해 주세요.",
        )

    db.delete(current_user)
    db.commit()
    return {
        "screen_id": "MY-03",
        "next_screen": "AUTH-01",
        "message": "계정과 모든 기록이 영구 삭제되었어요.",
    }


@router.get("/permissions")
def get_permission_fallback_state(
    state: str = Query(default="denied"),
    current_user: User = Depends(get_current_user),
):
    """화면 STATE-07 (/permissions?state=denied): 카메라·푸시 권한 거부 시 대체 경로 안내"""
    return {
        "screen_id": "STATE-07",
        "state": state,
        "camera_permission": {
            "status": "거부됨 · 기기 설정에서 변경",
            "fallback_action": "선택한 영수증 사진 불러오기 또는 권한 없이 직접 등록(/register/manual)",
        },
        "push_permission": {
            "status": "거부됨 · 앱 수신 설정과 별개",
            "fallback_action": "알림함과 기한 관리 화면(/notifications, /deadlines)은 계속 이용할 수 있어요.",
        },
    }
