from datetime import date, datetime
from typing import List, Optional, Any
from pydantic import BaseModel, EmailStr, Field


# --- A. 시작 · 계정 만들기 (AUTH-01 ~ AUTH-06) ---
class SignupRequest(BaseModel):
    email: EmailStr = Field(default="jiyun@example.com")
    password: str = Field(default="cosmemo1234", min_length=8)
    password_confirm: str = Field(default="cosmemo1234")
    nickname: str = Field(default="지윤", min_length=2, max_length=12)
    terms_agreed: bool = True
    privacy_agreed: bool = True
    age_agreed: bool = True
    marketing_agreed: bool = False


class LoginRequest(BaseModel):
    email: EmailStr = Field(default="jiyun@example.com")
    password: str = Field(default="cosmemo1234")


class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(default="jiyun@example.com")


class SkinProfileUpdate(BaseModel):
    skin_type: str = Field(default="복합성", description="건성 | 지성 | 복합성 | 중성 | 잘 모르겠어요")
    skin_concerns: List[str] = Field(default=["건조함", "민감함"])


class PermissionOnboardingUpdate(BaseModel):
    perm_camera: bool = True
    perm_photo: bool = True
    perm_notification: bool = True


# --- C. 영수증 및 화장품 등록 (REG-01 ~ REG-07) ---
class ReceiptItemUpdate(BaseModel):
    item_code: str
    brand: Optional[str] = None
    parsed_name: str
    category: str = "스킨케어"
    quantity: int = 1
    unit_price: int = 0
    is_selected: bool = True
    matched_catalog_code: Optional[str] = None


class ReceiptReviewUpdateRequest(BaseModel):
    store_name: str = "보태닉 스토어"
    purchase_date: date = date(2026, 10, 30)
    total_amount: int = 43300
    items: List[ReceiptItemUpdate]


class OwnedProductCreate(BaseModel):
    brand: str = "라운드리프"
    name: str = "판테놀 세럼"
    category: str = "스킨케어"
    volume: str = "30 ml"
    main_ingredients: List[str] = ["판테놀", "베타인"]
    purchase_date: Optional[date] = date(2026, 10, 29)
    quantity: int = 1
    status: str = "unopened"  # unopened | in_use
    opened_date: Optional[date] = None
    printed_expiry_date: Optional[date] = date(2027, 8, 31)
    pao_months: Optional[int] = 12
    purchase_store: Optional[str] = "올리브영 강남점"
    purchase_price: Optional[int] = 22000
    receipt_code: Optional[str] = "R-031"
    memo: Optional[str] = None
    catalog_code: Optional[str] = None


class OwnedProductUpdate(BaseModel):
    brand: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    volume: Optional[str] = None
    main_ingredients: Optional[List[str]] = None
    purchase_date: Optional[date] = None
    opened_date: Optional[date] = None
    printed_expiry_date: Optional[date] = None
    pao_months: Optional[int] = None
    remaining_percent: Optional[int] = None
    purchase_price: Optional[int] = None
    memo: Optional[str] = None
    idempotency_key: Optional[str] = None


class OpenProductRequest(BaseModel):
    opened_date: date = date(2026, 10, 30)
    pao_months: Optional[int] = 12


# --- D. 개인 평가 (REV-01 ~ REV-02) ---
class EvaluationCreateUpdate(BaseModel):
    rating: float = Field(default=4.0, ge=1.0, le=5.0)
    skin_fit: str = Field(default="잘 맞아요", description="잘 맞아요 | 보통 | 맞지 않아요")
    reactions: List[str] = Field(default=["촉촉해요", "편안해요"])
    repurchase_intent: str = Field(default="네, 있어요", description="네, 있어요 | 고민 중이에요 | 아니요")
    memo: Optional[str] = "저녁에 바르기 좋았어요. 건조함이 덜 느껴져요."
    evaluated_date: date = date(2026, 10, 20)


# --- E. 비우기 · 분리배출 (DIS-01 ~ DIS-04) ---
class DisposalCreateRequest(BaseModel):
    reason: str = Field(default="다 썼어요", description="다 썼어요 | 기한이 지났어요 | 피부에 맞지 않아요")
    ended_date: date = date(2026, 10, 30)
    remaining_at_end: str = "0% · 모두 사용했어요"
    memo: Optional[str] = "끝까지 잘 사용했어요. 공병 씻기 전에 배출 방법 확인."


# --- F. 커뮤니티 (COM-01 ~ COM-03) ---
class CommunityPostCreate(BaseModel):
    post_type: str = Field(default="후기", description="질문 | 추천 | 후기")
    title: str
    body: str
    related_owned_code: Optional[str] = "OWN-101"
    include_quote: bool = True
    include_rating: bool = False
    include_reactions: bool = False
    confirmed_public: bool = True
    is_draft: bool = False


class CommunityCommentCreate(BaseModel):
    body: str


# --- G. 마이 · 알림 설정 · 계정 관리 (MY-01 ~ MY-03) ---
class NotificationSettingUpdate(BaseModel):
    notify_expiry_enabled: bool = True
    notify_expiry_days: List[int] = [30, 7]
    notify_time: str = "09:00"
    notify_seasonal: bool = True
    notify_community: bool = False
    notify_evaluation: bool = True
    marketing_agreed: bool = False


class AccountUpdateRequest(BaseModel):
    nickname: str = Field(default="지윤", min_length=2, max_length=12)
    skin_type: str = "복합성"
    skin_concerns: List[str] = ["건조함", "민감함"]


class AccountDeleteRequest(BaseModel):
    confirm_text: str = Field(description="확인을 위해 '탈퇴' 입력")
    confirmed_irreversible: bool = True
