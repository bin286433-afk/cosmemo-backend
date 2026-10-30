from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.schemas import (
    SignupRequest, LoginRequest, PasswordResetRequest,
    SkinProfileUpdate, PermissionOnboardingUpdate
)
from app.utils.security import (
    get_password_hash, verify_password, create_access_token, get_current_user
)

router = APIRouter(prefix="/auth", tags=["A · 시작 · 계정 만들기 (AUTH)"])


@router.get("/welcome")
def get_welcome_info():
    """화면 AUTH-01 (/welcome): 인트로 안내 정보 반환"""
    return {
        "screen_id": "AUTH-01",
        "title": "나의 화장품을, 끝까지 아끼는 기록.",
        "subtitle": "새로 사기 전에는 기억을, 다 쓴 뒤에는 더 나은 마무리를.",
        "highlights": ["01 간편한 등록", "02 나만의 평가", "03 올바른 비우기"],
        "reference_date": "2026-10-30",
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

    count = db.query(User).count() + 1
    user = User(
        code=f"USER-{count:02d}",
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

    token = create_access_token(user.email)
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

    token = create_access_token(user.email)
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
def request_password_reset(payload: PasswordResetRequest):
    """화면 AUTH-04 (/auth/password-reset): 계정 존재 여부를 노출하지 않고 동일한 안내 반환"""
    return {
        "screen_id": "AUTH-04",
        "email": payload.email,
        "message": "해당 이메일로 가입한 계정이 있다면 재설정 링크가 발송돼요. 스팸함도 확인해 주세요.",
        "link_valid_minutes": 30,
        "resend_cooldown_seconds": 60,
    }


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
