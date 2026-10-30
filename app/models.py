from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Date, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., USER-01
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(50), nullable=False)

    # 피부 프로필 (AUTH-05, MY-01, MY-03)
    skin_type = Column(String(30), default="미설정")  # 건성, 지성, 복합성, 중성, 잘 모르겠어요
    skin_concerns = Column(JSON, default=list)        # ["건조함", "민감함", "번들거림", "피부결"]

    # 약관 동의 및 권한 설정 (AUTH-03, AUTH-06, MY-02)
    terms_agreed = Column(Boolean, default=True)
    privacy_agreed = Column(Boolean, default=True)
    age_agreed = Column(Boolean, default=True)
    marketing_agreed = Column(Boolean, default=False)

    perm_camera = Column(Boolean, default=True)
    perm_photo = Column(Boolean, default=True)
    perm_notification = Column(Boolean, default=True)

    # 알림 환경 설정 (MY-02)
    notify_expiry_enabled = Column(Boolean, default=True)
    notify_expiry_days = Column(JSON, default=lambda: [30, 7])  # [30, 7, 0]
    notify_time = Column(String(10), default="09:00")
    notify_seasonal = Column(Boolean, default=True)
    notify_community = Column(Boolean, default=False)
    notify_evaluation = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owned_products = relationship("OwnedProduct", back_populates="user", cascade="all, delete-orphan")
    receipts = relationship("ReceiptDraft", back_populates="user", cascade="all, delete-orphan")
    evaluations = relationship("Evaluation", back_populates="user", cascade="all, delete-orphan")
    disposals = relationship("DisposalRecord", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("CommunityPost", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("CommunityComment", back_populates="user", cascade="all, delete-orphan")


class CatalogProduct(Base):
    __tablename__ = "catalog_products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., CAT-01
    brand = Column(String(100), index=True, nullable=False)
    name = Column(String(200), index=True, nullable=False)
    category = Column(String(50), index=True, nullable=False)  # 스킨케어, 색조, 향수
    volume = Column(String(50), default="50 ml")
    main_ingredients = Column(JSON, default=list)  # ["판테놀", "세라마이드 NP"]
    default_pao_months = Column(Integer, default=12)
    disposal_guide = Column(JSON, default=list)    # 부위별 재질 및 분리배출 가이드 (DIS-02)


class OwnedProduct(Base):
    __tablename__ = "owned_products"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., OWN-101
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    catalog_id = Column(Integer, ForeignKey("catalog_products.id"), nullable=True)

    brand = Column(String(100), index=True, nullable=False)
    name = Column(String(200), index=True, nullable=False)
    category = Column(String(50), index=True, nullable=False)  # 스킨케어, 색조, 향수
    volume = Column(String(50), default="50 ml")
    main_ingredients = Column(JSON, default=list)

    # 상태: unopened(미개봉), in_use(사용 중), expired(기한 초과), archived(지난 제품 보관함)
    status = Column(String(30), default="unopened", index=True)
    purchase_date = Column(Date, nullable=True)
    opened_date = Column(Date, nullable=True)
    printed_expiry_date = Column(Date, nullable=True)  # 인쇄 사용기한
    pao_months = Column(Integer, nullable=True)        # 개봉 후 사용기한 (개월, 미확인 시 None)
    calculated_deadline = Column(Date, nullable=True)  # 계산된 최종 사용기한 (EXP-01 규칙 적용)
    deadline_basis = Column(String(100), nullable=True)

    remaining_percent = Column(Integer, default=100)   # 남은 양 (%)
    purchase_store = Column(String(100), nullable=True)
    purchase_price = Column(Integer, nullable=True)
    quantity = Column(Integer, default=1)
    receipt_code = Column(String(30), nullable=True)   # e.g., R-008, R-031
    memo = Column(Text, nullable=True)

    # STATE-06: 중복 저장 방지용 멱등성 키 및 초안 보관
    last_idempotency_key = Column(String(100), nullable=True)
    draft_payload = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="owned_products")
    catalog = relationship("CatalogProduct")
    evaluations = relationship("Evaluation", back_populates="owned_product", cascade="all, delete-orphan")
    disposal = relationship("DisposalRecord", back_populates="owned_product", uselist=False, cascade="all, delete-orphan")


class ReceiptDraft(Base):
    __tablename__ = "receipt_drafts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., R-031
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    store_name = Column(String(100), default="보태닉 스토어")
    purchase_date = Column(Date, nullable=True)
    total_amount = Column(Integer, default=0)
    # 상태: processing, review, review_error, ocr_failed, completed
    status = Column(String(30), default="review")
    image_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="receipts")
    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), index=True)  # e.g., RI-1, RI-2, RI-3
    receipt_id = Column(Integer, ForeignKey("receipt_drafts.id"), nullable=False, index=True)
    raw_name = Column(String(200), nullable=False)
    brand = Column(String(100), nullable=True)
    parsed_name = Column(String(200), nullable=False)
    category = Column(String(50), default="스킨케어")
    quantity = Column(Integer, default=1)
    unit_price = Column(Integer, default=0)
    is_cosmetic = Column(Boolean, default=True)  # 화장품 외 항목 제외 (화장솜 등)
    is_selected = Column(Boolean, default=True)
    matched_catalog_code = Column(String(30), nullable=True)

    receipt = relationship("ReceiptDraft", back_populates="items")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., EVAL-101
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    owned_product_id = Column(Integer, ForeignKey("owned_products.id"), nullable=False, index=True)

    rating = Column(Float, nullable=False)              # 1.0 ~ 5.0
    skin_fit = Column(String(30), nullable=False)       # 잘 맞아요, 보통, 맞지 않아요
    reactions = Column(JSON, default=list)              # ["촉촉해요", "편안해요", "번들거려요", "따가웠어요", "별다른 느낌 없어요"]
    repurchase_intent = Column(String(30), nullable=False)  # 네, 있어요 / 고민 중이에요 / 아니요
    memo = Column(Text, nullable=True)
    evaluated_date = Column(Date, default=date.today)
    is_public = Column(Boolean, default=False)          # 기본 비공개 (REV-01)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="evaluations")
    owned_product = relationship("OwnedProduct", back_populates="evaluations")


class DisposalRecord(Base):
    __tablename__ = "disposal_records"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., DISP-101, ARCH-101
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    owned_product_id = Column(Integer, ForeignKey("owned_products.id"), nullable=False, unique=True)

    reason = Column(String(50), nullable=False)         # 다 썼어요, 기한이 지났어요, 피부에 맞지 않아요
    ended_date = Column(Date, default=date.today)
    remaining_at_end = Column(String(50), default="0% · 모두 사용했어요")
    memo = Column(Text, nullable=True)
    disposal_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="disposals")
    owned_product = relationship("OwnedProduct", back_populates="disposal")


class CollectionSpot(Base):
    __tablename__ = "collection_spots"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., COL-01
    name = Column(String(100), nullable=False)          # 보태닉 공병 회수함, 리필 라운지 수거함
    spot_type = Column(String(50), nullable=False)      # 브랜드 매장 회수함, 리필 스테이션
    region = Column(String(100), index=True, nullable=False)
    hours = Column(String(100), nullable=False)
    accepted_items = Column(String(255), nullable=False)
    note = Column(String(255), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., N-01
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String(30), index=True, nullable=False)  # 사용 기한, 계절 안내, 평가 기록
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    target_path = Column(String(200), nullable=True)
    related_owned_code = Column(String(30), nullable=True)
    is_read = Column(Boolean, default=False)
    created_label = Column(String(50), default="오늘 오전 9:00")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notifications")


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., P-01
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    post_type = Column(String(30), index=True, nullable=False)  # 질문, 추천, 후기
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)

    related_owned_code = Column(String(30), nullable=True)
    related_product_summary = Column(JSON, nullable=True)
    shared_quote = Column(String(255), nullable=True)
    shared_rating = Column(Float, nullable=True)
    shared_reactions = Column(JSON, default=list)

    like_count = Column(Integer, default=0)
    is_draft = Column(Boolean, default=False)
    created_label = Column(String(50), default="2026.10.30 10:20")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="posts")
    comments = relationship("CommunityComment", back_populates="post", cascade="all, delete-orphan")


class CommunityComment(Base):
    __tablename__ = "community_comments"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, index=True)  # e.g., C-01
    post_id = Column(Integer, ForeignKey("community_posts.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    author_nickname = Column(String(50), nullable=False)
    body = Column(Text, nullable=False)
    created_label = Column(String(50), default="10.30 10:40")
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("CommunityPost", back_populates="comments")
    user = relationship("User", back_populates="comments")
