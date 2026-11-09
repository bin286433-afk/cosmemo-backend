import hashlib
import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from app.config import settings
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import PasswordResetToken, User, _utcnow
from app.schemas import (
    SignupRequest, LoginRequest, PasswordResetRequest, PasswordResetConfirm,
    SkinProfileUpdate, PermissionOnboardingUpdate
)
from app.utils.security import (
    get_password_hash, verify_password, needs_rehash, issue_token_for, get_current_user
)
from app.utils.codes import next_code
from app.utils.deadline import get_today

logger = logging.getLogger("cosmemo.auth")
router = APIRouter(prefix="/auth", tags=["A · 시작 · 계정 만들기 (AUTH)"])


@router.get("/welcome")
def get_welcome_info():
    """화면 AUTH-01 (/welcome): 인트로 안내 정보 반환"""
    return {
        "screen_id": "AUTH-01",
        "title": "나의 화장품을, 끝까지 아끼는 기록.",
        "subtitle": "새로 사기 전에는 기억을, 다 쓴 뒤에는 더 나은 마무리를.",
        "highlights": ["01 간편한 등록", "02 나만의 평가", "03 올바른 비우기"],
        "reference_date": get_today().isoformat(),
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    """화면 AUTH-03 (/auth/signup): 회원가입 및 필수 약관 동의 검증"""
    if payload.password != payload.password_confirm:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않아요.")
    if not (payload.terms_agreed and payload.privacy_agreed and payload.age_agreed):
        raise HTTPException(status_code=400, detail="필수 약관(이용약관, 개인정보 수집·이용, 만 14세 이상)에 동의해 주세요.")

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요.")

    user = User(
        code=next_code(db, User, "USER", start=1, width=2),
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        nickname=payload.nickname,
        terms_agreed=payload.terms_agreed,
        privacy_agreed=payload.privacy_agreed,
        age_agreed=payload.age_agreed,
        marketing_agreed=payload.marketing_agreed,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = issue_token_for(user)
    return {
        "screen_id": "AUTH-03",
        "next_screen": "AUTH-05",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "code": user.code,
            "email": user.email,
            "nickname": user.nickname,
            "marketing_agreed": user.marketing_agreed,
        },
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """화면 AUTH-02 (/auth/login): 이메일 로그인"""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호를 확인해 주세요.",
        )
    if needs_rehash(user.password_hash):  # 예전 SHA-256 해시 → bcrypt 로 자동 교체
        user.password_hash = get_password_hash(payload.password)
        db.commit()

    token = issue_token_for(user)
    return {
        "screen_id": "AUTH-02",
        "next_screen": "HOME-01",
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "code": user.code,
            "email": user.email,
            "nickname": user.nickname,
            "skin_type": user.skin_type,
            "skin_concerns": user.skin_concerns,
        },
    }


@router.post("/password-reset")
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    화면 AUTH-04: 계정 존재 여부와 관계없이 같은 안내를 반환합니다.
    계정이 있으면 30분짜리 재설정 토큰을 만들고, DB에는 해시만 저장합니다.
    메일 발송 서버가 없으므로 링크는 서버 로그에 남기고, DEMO_MODE 에서만 응답에 dev_reset_token 을 포함합니다.
    """
    response = {
        "screen_id": "AUTH-04",
        "email": payload.email,
        "message": "해당 이메일로 가입한 계정이 있다면 재설정 링크가 발송돼요. 스팸함도 확인해 주세요.",
        "link_valid_minutes": settings.PASSWORD_RESET_MINUTES,
        "resend_cooldown_seconds": 60,
    }
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        return response

    recent = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.created_at > _utcnow() - timedelta(seconds=60))
        .first()
    )
    if recent:  # 60초 재발송 제한 (응답은 동일)
        return response

    raw = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=_utcnow() + timedelta(minutes=settings.PASSWORD_RESET_MINUTES),
    ))
    db.commit()
    logger.info("[메일 대체] %s 비밀번호 재설정 링크: /auth/password-reset/confirm?token=%s", user.email, raw)
    if settings.DEMO_MODE:
        response["dev_reset_token"] = raw
    return response


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """재설정 링크의 토큰으로 새 비밀번호 저장 → 모든 기기 로그아웃"""
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(status_code=400, detail="비밀번호가 일치하지 않아요.")
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    rec = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()
    if not rec or rec.used_at or rec.expires_at < _utcnow():
        raise HTTPException(status_code=400, detail="링크가 만료되었거나 이미 사용되었어요. 재설정 메일을 다시 요청해 주세요.")
    user = db.get(User, rec.user_id)
    user.password_hash = get_password_hash(payload.new_password)
    user.token_version = (user.token_version or 0) + 1
    rec.used_at = _utcnow()
    db.commit()
    return {"screen_id": "AUTH-04", "next_screen": "AUTH-02", "message": "새 비밀번호로 저장했어요. 다시 로그인해 주세요."}


@router.put("/onboarding/skin")
def update_onboarding_skin(
    payload: SkinProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 AUTH-05 (/onboarding/skin): 피부 타입 및 관심 고민 저장"""
    current_user.skin_type = payload.skin_type
    current_user.skin_concerns = payload.skin_concerns
    db.commit()
    db.refresh(current_user)
    return {
        "screen_id": "AUTH-05",
        "next_screen": "AUTH-06",
        "skin_type": current_user.skin_type,
        "skin_concerns": current_user.skin_concerns,
        "disclaimer": "의학적 진단이 아니에요. 직접 선택한 정보는 개인 기록을 정리하는 데만 사용해요.",
    }


@router.put("/onboarding/permissions")
def update_onboarding_permissions(
    payload: PermissionOnboardingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """화면 AUTH-06 (/onboarding/permissions): 카메라·사진·알림 선택 권한 저장"""
    current_user.perm_camera = payload.perm_camera
    current_user.perm_photo = payload.perm_photo
    current_user.perm_notification = payload.perm_notification
    db.commit()
    return {
        "screen_id": "AUTH-06",
        "next_screen": "HOME-01",
        "permissions": {
            "camera": current_user.perm_camera,
            "photo": current_user.perm_photo,
            "notification": current_user.perm_notification,
        },
    }
