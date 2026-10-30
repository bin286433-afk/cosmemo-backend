from datetime import date
from sqlalchemy.orm import Session
from app.models import (
    User, CatalogProduct, OwnedProduct, ReceiptDraft, ReceiptItem,
    Evaluation, DisposalRecord, CollectionSpot, Notification,
    CommunityPost, CommunityComment
)
from app.utils.security import get_password_hash
from app.utils.deadline import calculate_product_deadline


def seed_initial_data(db: Session):
    if db.query(User).first():
        return

    # 1. 기본 사용자 (지윤, USER-01) - 화면 A, B, G 기준
    user = User(
        code="USER-01",
        email="jiyun@example.com",
        password_hash=get_password_hash("cosmemo1234"),
        nickname="지윤",
        skin_type="복합성",
        skin_concerns=["건조함", "민감함"],
        terms_agreed=True,
        privacy_agreed=True,
        age_agreed=True,
        marketing_agreed=False,
        perm_camera=True,
        perm_photo=True,
        perm_notification=True,
        notify_expiry_enabled=True,
        notify_expiry_days=[30, 7],
        notify_time="09:00",
        notify_seasonal=True,
        notify_community=False,
        notify_evaluation=True,
    )
    db.add(user)
    db.flush()

    # 2. 카탈로그 제품 (CAT-01 ~ CAT-06) - 화면 B, C, E, F 기준
    catalogs = [
        CatalogProduct(
            code="CAT-01",
            brand="라운드리프",
            name="수분 장벽 크림",
            category="스킨케어",
            volume="50 ml",
            main_ingredients=["판테놀", "세라마이드 NP"],
            default_pao_months=6,
            disposal_guide=[
                {
                    "step": "#1",
                    "part": "본체 · PP 플라스틱",
                    "guide": "잔여물을 닦아낸 뒤 물로 헹궈 주세요. 세척 가능한 플라스틱은 플라스틱으로 배출 기준을 확인해요."
                },
                {
                    "step": "#2",
                    "part": "뚜껑 · PP 플라스틱",
                    "guide": "본체에서 분리해요. 안쪽 패킹이 분리되면 떼어내고 별도 재질로 확인해 주세요."
                },
                {
                    "step": "#3",
                    "part": "레이어 · 복합 재질",
                    "guide": "라벨을 떼어내고 접착제까지 닦아요. 분리가 어렵거나 재질이 불분명하면 지역 기준에 따라 폐기해요."
                },
                {
                    "step": "TIP",
                    "part": "펌프형 용기라면?",
                    "guide": "플라스틱·금속 스프링이 섞인 펌프는 일반쓰레기인 경우가 많아요. 지자체 분리배출 안내나 수거처 제휴 조건을 확인해요."
                }
            ],
        ),
        CatalogProduct(
            code="CAT-02",
            brand="모닝듀",
            name="진정 토너",
            category="스킨케어",
            volume="200 ml",
            main_ingredients=["병풀추출물", "판테놀"],
            default_pao_months=12,
            disposal_guide=[
                {"step": "#1", "part": "투명 용기 · PET", "guide": "내용물을 비우고 물로 헹군 뒤 라벨을 제거해 투명 페트 또는 플라스틱으로 배출해요."},
                {"step": "#2", "part": "속캡 및 뚜껑 · PP", "guide": "속캡을 분리해 플라스틱류로 배출해요."}
            ],
        ),
        CatalogProduct(
            code="CAT-03",
            brand="라운드리프",
            name="판테놀 세럼",
            category="스킨케어",
            volume="30 ml",
            main_ingredients=["판테놀", "베타인"],
            default_pao_months=12,
            disposal_guide=[
                {"step": "#1", "part": "스포이드 유리관 · 유리/고무", "guide": "고무 패킹과 유리관, 플라스틱 캡을 각각 분리해 배출해요."},
                {"step": "#2", "part": "본체 · 플라스틱/유리", "guide": "안쪽 잔여물을 닦아내고 재질 표기에 맞춰 배출해요."}
            ],
        ),
        CatalogProduct(
            code="CAT-04",
            brand="누드블룸",
            name="소프트 립 틴트",
            category="색조",
            volume="4 g",
            main_ingredients=["토코페롤", "스쿠알란"],
            default_pao_months=6,
            disposal_guide=[
                {"step": "#1", "part": "팁 브러시 및 소형 용기", "guide": "립 틴트 용기는 세척이 어렵고 복합 재질인 경우가 많아 키친타월로 닦아낸 뒤 일반쓰레기로 배출해요."}
            ],
        ),
        CatalogProduct(
            code="CAT-05",
            brand="메종드보",
            name="우디 가든",
            category="향수",
            volume="30 ml",
            main_ingredients=["에탄올", "향료"],
            default_pao_months=24,
            disposal_guide=[
                {"step": "#1", "part": "남은 향수 액체", "guide": "하수구에 바로 붓지 말고 키친타월이나 신문지에 흡수시켜 일반쓰레기로 버려요."},
                {"step": "#2", "part": "유리 본체 및 금속 노즐", "guide": "금속 스프레이 노즐을 분리한 뒤 유리병만 유리류로 배출해요."}
            ],
        ),
        CatalogProduct(
            code="CAT-06",
            brand="데일리선",
            name="라이트 선크림",
            category="스킨케어",
            volume="50 ml",
            main_ingredients=["징크옥사이드", "나이아신아마이드"],
            default_pao_months=12,
            disposal_guide=[
                {"step": "#1", "part": "튜브 본체 · OTHER/PP", "guide": "튜브를 가위로 잘라 내부 잔여물을 완전히 닦아낸 뒤 배출해요."}
            ],
        ),
    ]
    db.add_all(catalogs)
    db.flush()
    cat_map = {c.code: c for c in catalogs}

    # 3. 내 화장대 보유 제품 6개 + 보관함 2개 (화면 B, D, E, F, G와 정확히 일치)
    owned_specs = [
        # OWN-101: 라운드리프 수분 장벽 크림 (사용 중, 35% 남음, 2026.11.12까지 D-13)
        dict(
            code="OWN-101",
            catalog_id=cat_map["CAT-01"].id,
            brand="라운드리프",
            name="수분 장벽 크림",
            category="스킨케어",
            volume="50 ml",
            main_ingredients=["판테놀", "세라마이드 NP"],
            status="in_use",
            purchase_date=date(2026, 5, 10),
            opened_date=date(2026, 5, 12),
            printed_expiry_date=date(2027, 4, 30),
            pao_months=6,
            remaining_percent=35,
            purchase_store="올리브영 강남점",
            purchase_price=18000,
            receipt_code="R-008",
            memo="저녁 루틴에 사용. 마지막 사용량을 확인했어요.",
        ),
        # OWN-102: 모닝듀 진정 토너 (사용 중, 60% 남음, 2027.03.01까지)
        dict(
            code="OWN-102",
            catalog_id=cat_map["CAT-02"].id,
            brand="모닝듀",
            name="진정 토너",
            category="스킨케어",
            volume="200 ml",
            main_ingredients=["병풀추출물", "판테놀"],
            status="in_use",
            purchase_date=date(2026, 2, 25),
            opened_date=date(2026, 3, 1),
            printed_expiry_date=date(2027, 8, 30),
            pao_months=12,
            remaining_percent=60,
            purchase_store="보태닉 스토어",
            purchase_price=15000,
            receipt_code="R-003",
            memo="아침저녁 스킨케어 첫 단계로 사용 중.",
        ),
        # OWN-103: 라운드리프 판테놀 세럼 (미개봉, 인쇄기한 2027.08.31)
        dict(
            code="OWN-103",
            catalog_id=cat_map["CAT-03"].id,
            brand="라운드리프",
            name="판테놀 세럼",
            category="스킨케어",
            volume="30 ml",
            main_ingredients=["판테놀", "베타인"],
            status="unopened",
            purchase_date=date(2026, 10, 29),
            opened_date=None,
            printed_expiry_date=date(2027, 8, 31),
            pao_months=12,
            remaining_percent=100,
            purchase_store="올리브영 강남점",
            purchase_price=22000,
            receipt_code="R-031",
            memo="세일 기간에 미리 구매해 둔 세럼.",
        ),
        # OWN-104: 누드블룸 소프트 립 틴트 (기한 초과, 2026.10.20 기한 지남, 20% 남음)
        dict(
            code="OWN-104",
            catalog_id=cat_map["CAT-04"].id,
            brand="누드블룸",
            name="소프트 립 틴트",
            category="색조",
            volume="4 g",
            main_ingredients=["토코페롤", "스쿠알란"],
            status="expired",
            purchase_date=date(2026, 4, 15),
            opened_date=date(2026, 4, 20),
            printed_expiry_date=date(2027, 4, 15),
            pao_months=6,
            remaining_percent=20,
            purchase_store="올리브영 명동점",
            purchase_price=13000,
            receipt_code="R-002",
            memo="색상은 예쁘지만 개봉 후 6개월이 지나 사용 중단.",
        ),
        # OWN-105: 메종드보 우디 가든 (사용 중, 향수, 80% 남음, 2028.01.10까지)
        dict(
            code="OWN-105",
            catalog_id=cat_map["CAT-05"].id,
            brand="메종드보",
            name="우디 가든",
            category="향수",
            volume="30 ml",
            main_ingredients=["에탄올", "향료"],
            status="in_use",
            purchase_date=date(2026, 1, 5),
            opened_date=date(2026, 1, 10),
            printed_expiry_date=date(2028, 12, 31),
            pao_months=24,
            remaining_percent=80,
            purchase_store="시코르 강남역점",
            purchase_price=58000,
            receipt_code="R-001",
            memo="가을·겨울에 잘 어울리는 우디 향수.",
        ),
        # OWN-106: 데일리선 라이트 선크림 (사용 중, 50% 남음, 기한 확인 필요 · PAO 미등록)
        dict(
            code="OWN-106",
            catalog_id=cat_map["CAT-06"].id,
            brand="데일리선",
            name="라이트 선크림",
            category="스킨케어",
            volume="50 ml",
            main_ingredients=["징크옥사이드", "나이아신아마이드"],
            status="in_use",
            purchase_date=date(2026, 7, 1),
            opened_date=date(2026, 7, 5),
            printed_expiry_date=None,
            pao_months=None,
            remaining_percent=50,
            purchase_store="온라인몰",
            purchase_price=16000,
            receipt_code=None,
            memo="단상자를 버려서 PAO 표기를 확인해야 함.",
        ),
        # ARCH-102 (보관함 1): 그린더마 시카 진정 젤 (피부에 맞지 않아요 · 2026.08.15)
        dict(
            code="OWN-098",
            catalog_id=None,
            brand="그린더마",
            name="시카 진정 젤",
            category="스킨케어",
            volume="100 ml",
            main_ingredients=["병풀추출물", "에탄올"],
            status="archived",
            purchase_date=date(2026, 7, 20),
            opened_date=date(2026, 7, 22),
            printed_expiry_date=date(2027, 7, 20),
            pao_months=12,
            remaining_percent=70,
            purchase_store="올리브영",
            purchase_price=14000,
            receipt_code=None,
            memo="바르고 나서 볼 쪽이 따가워 사용 중단.",
        ),
        # ARCH-103 (보관함 2): 퓨어포레 소프트 클렌징 밤 (다 썼어요 · 2026.09.28)
        dict(
            code="OWN-099",
            catalog_id=None,
            brand="퓨어포레",
            name="소프트 클렌징 밤",
            category="스킨케어",
            volume="100 ml",
            main_ingredients=["호호바씨오일", "판테놀"],
            status="archived",
            purchase_date=date(2026, 6, 10),
            opened_date=date(2026, 6, 12),
            printed_expiry_date=date(2027, 6, 10),
            pao_months=12,
            remaining_percent=0,
            purchase_store="보태닉 스토어",
            purchase_price=19000,
            receipt_code=None,
            memo="세정력이 순하고 눈 시림이 없어 끝까지 다 씀.",
        ),
    ]

    owned_objs = {}
    for spec in owned_specs:
        deadline, basis = calculate_product_deadline(
            status=spec["status"],
            opened_date=spec["opened_date"],
            printed_expiry_date=spec["printed_expiry_date"],
            pao_months=spec["pao_months"],
        )
        obj = OwnedProduct(
            user_id=user.id,
            calculated_deadline=deadline,
            deadline_basis=basis,
            **spec
        )
        db.add(obj)
        db.flush()
        owned_objs[spec["code"]] = obj

    # 4. 개인 평가 기록 (화면 D: REV-01, REV-02 및 화면 F: REC-01)
    evaluations = [
        # 수분 장벽 크림 최근 평가 (EVAL-101)
        Evaluation(
            code="EVAL-101",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-101"].id,
            rating=4.0,
            skin_fit="잘 맞아요",
            reactions=["촉촉해요", "편안해요"],
            repurchase_intent="네, 있어요",
            memo="저녁에 바르기 좋았어요. 건조함이 덜 느껴져요.",
            evaluated_date=date(2026, 10, 20),
            is_public=False,
        ),
        # 수분 장벽 크림 이전 평가 (EVAL-100)
        Evaluation(
            code="EVAL-100",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-101"].id,
            rating=3.0,
            skin_fit="보통",
            reactions=["촉촉해요"],
            repurchase_intent="고민 중이에요",
            memo="아직 사용 초기라 조금 더 써보려고 해요.",
            evaluated_date=date(2026, 6, 2),
            is_public=False,
        ),
        # 모닝듀 진정 토너 평가 (EVAL-102 - 추천 화면 REC-01 기준 5.0 잘 맞아요)
        Evaluation(
            code="EVAL-102",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-102"].id,
            rating=5.0,
            skin_fit="잘 맞아요",
            reactions=["촉촉해요", "편안해요"],
            repurchase_intent="네, 있어요",
            memo="10.15 평가에서 재구매 의향을 남겼어요. 무난하고 속건조를 잘 잡아줘요.",
            evaluated_date=date(2026, 10, 15),
            is_public=False,
        ),
        # 시카 진정 젤 평가 (EVAL-103 - 2.0 맞지 않아요 · 따가웠어요)
        Evaluation(
            code="EVAL-103",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-098"].id,
            rating=2.0,
            skin_fit="맞지 않아요",
            reactions=["따가웠어요"],
            repurchase_intent="아니요",
            memo="바른 직후 따가움이 느껴져서 사용을 중단했어요.",
            evaluated_date=date(2026, 8, 15),
            is_public=False,
        ),
        # 소프트 클렌징 밤 평가 (EVAL-104 - 5.0 잘 맞아요)
        Evaluation(
            code="EVAL-104",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-099"].id,
            rating=5.0,
            skin_fit="잘 맞아요",
            reactions=["촉촉해요", "편안해요"],
            repurchase_intent="네, 있어요",
            memo="세안 후 당김이 없어서 다음에도 재구매하고 싶어요.",
            evaluated_date=date(2026, 9, 28),
            is_public=False,
        ),
    ]
    db.add_all(evaluations)

    # 5. 지난 제품 보관함 폐기/종료 기록 (화면 E: ARC-01)
    disposals = [
        DisposalRecord(
            code="ARCH-102",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-098"].id,
            reason="피부에 맞지 않아요",
            ended_date=date(2026, 8, 15),
            remaining_at_end="70% 남음",
            memo="자극이 있어 바디용으로 전환 후 정리.",
            disposal_completed=True,
        ),
        DisposalRecord(
            code="ARCH-103",
            user_id=user.id,
            owned_product_id=owned_objs["OWN-099"].id,
            reason="다 썼어요",
            ended_date=date(2026, 9, 28),
            remaining_at_end="0% · 모두 사용했어요",
            memo="PP 용기 세척 후 플라스틱 분리배출 완료.",
            disposal_completed=True,
        ),
    ]
    db.add_all(disposals)

    # 6. 영수증 초안 (화면 C: REG-02 ~ REG-05, R-031)
    receipt = ReceiptDraft(
        code="R-031",
        user_id=user.id,
        store_name="보태닉 스토어",
        purchase_date=date(2026, 10, 30),
        total_amount=43300,
        status="review",
    )
    db.add(receipt)
    db.flush()

    receipt_items = [
        ReceiptItem(
            code="RI-1",
            receipt_id=receipt.id,
            raw_name="수분 장벽 크림 18,000",
            brand="라운드리프",
            parsed_name="수분 장벽 크림",
            category="스킨케어",
            quantity=1,
            unit_price=18000,
            is_cosmetic=True,
            is_selected=True,
            matched_catalog_code="CAT-01",
        ),
        ReceiptItem(
            code="RI-2",
            receipt_id=receipt.id,
            raw_name="판테놀 세럼 22,000",
            brand="라운드리프",
            parsed_name="판테놀 세럼",
            category="스킨케어",
            quantity=1,
            unit_price=22000,
            is_cosmetic=True,
            is_selected=True,
            matched_catalog_code="CAT-03",
        ),
        ReceiptItem(
            code="RI-3",
            receipt_id=receipt.id,
            raw_name="화장솜 3,300",
            brand=None,
            parsed_name="화장솜 · 화장품 외 상품",
            category="소품",
            quantity=1,
            unit_price=3300,
            is_cosmetic=False,
            is_selected=False,
            matched_catalog_code=None,
        ),
    ]
    db.add_all(receipt_items)

    # 7. 공병 수거처 (화면 E: DIS-03)
    spots = [
        CollectionSpot(
            code="COL-01",
            name="보태닉 공병 회수함",
            spot_type="예시 A · 브랜드 매장 회수함",
            region="기흥구 예시동 · 지점 미정",
            hours="10:00~20:30 · 휴무일 확인",
            accepted_items="빈 화장품 유리·플라스틱 본체(색조·샘플 제외 예시)",
            note="지점 위치·수거 품목·혜택 종료 여부 확인 필요",
        ),
        CollectionSpot(
            code="COL-02",
            name="리필 라운지 수거함",
            spot_type="예시 B · 리필 가능 여부 확인 필요",
            region="기흥구 예시로 · 지점 미정",
            hours="세척 상태와 라벨 제거 여부, 캡·내용물 제외 안내",
            accepted_items="세척 완료된 투명 PET 및 PP 화장품 용기",
            note="운영 시간·수거 중단 여부 확인 필요",
        ),
    ]
    db.add_all(spots)

    # 8. 알림함 (화면 D: NOTI-01)
    notifications = [
        Notification(
            code="N-01",
            user_id=user.id,
            category="사용 기한",
            title="수분 장벽 크림, 13일 남았어요",
            body="내 기록의 적용 기한은 11.12예요. 개봉일과 남은 양을 확인해요.",
            target_path="/owned/OWN-101",
            related_owned_code="OWN-101",
            is_read=False,
            created_label="오늘 오전 9:00",
        ),
        Notification(
            code="N-02",
            user_id=user.id,
            category="사용 기한",
            title="소프트 립 틴트 기한이 지났어요",
            body="10.20 기한이 지났어요. 사용을 중단하고 분리배출을 확인해 주세요.",
            target_path="/owned/OWN-104/end",
            related_owned_code="OWN-104",
            is_read=False,
            created_label="오늘 오전 9:00",
        ),
        Notification(
            code="N-03",
            user_id=user.id,
            category="계절 안내",
            title="건조한 계절, 내 루틴을 살펴봐요",
            body="건조함 관심 프로필과 보유 성분을 기준으로 안내를 준비했어요.",
            target_path="/seasonal/autumn",
            related_owned_code="OWN-101",
            is_read=False,
            created_label="어제 오후 6:00",
        ),
        Notification(
            code="N-04",
            user_id=user.id,
            category="평가 기록",
            title="라이트 선크림은 어땠나요?",
            body="사용 경험을 나만의 기록으로 남겨요.",
            target_path="/owned/OWN-106/evaluation/edit",
            related_owned_code="OWN-106",
            is_read=True,
            created_label="10.20",
        ),
    ]
    db.add_all(notifications)

    # 9. 커뮤니티 게시글 & 댓글 (화면 F: COM-01, COM-02, COM-03)
    post1 = CommunityPost(
        code="P-01",
        user_id=user.id,
        post_type="후기",
        title="수분 장벽 크림, 저녁 루틴에 좋았어요",
        body="저녁에 바르기 편했던 크림이에요. 마지막까지 쓴 뒤 본체와 뚜껑의 재질을 따로 확인했어요. 제 경험이니 참고만 해 주세요.",
        related_owned_code="OWN-101",
        related_product_summary={
            "brand": "라운드리프",
            "name": "수분 장벽 크림",
            "volume": "50 ml",
            "category": "스킨케어",
            "deadline_text": "11.12까지 · D-13",
        },
        shared_quote="저녁에 바르기 좋았어요.",
        shared_rating=None,
        shared_reactions=[],
        like_count=3,
        is_draft=False,
        created_label="2026.10.30 10:20",
    )
    post2 = CommunityPost(
        code="P-02",
        user_id=user.id,
        post_type="질문",
        title="펌프가 분리되지 않을 때는 어떻게 하나요?",
        body="본체는 유리인데 펌프 재질을 모르겠어요.",
        related_owned_code=None,
        related_product_summary=None,
        like_count=5,
        is_draft=False,
        created_label="10.30 09:10",
    )
    post3 = CommunityPost(
        code="P-03",
        user_id=user.id,
        post_type="추천",
        title="새 제품 사기 전 화장대부터 확인해요",
        body="비슷한 토너가 있다는 걸 기록 덕분에 알았어요.",
        related_owned_code="OWN-102",
        related_product_summary=None,
        like_count=8,
        is_draft=False,
        created_label="10.29 18:30",
    )
    post4 = CommunityPost(
        code="P-04",
        user_id=user.id,
        post_type="후기",
        title="클렌징 밤 공병을 정리했어요",
        body="뚜껑과 본체 표기를 따로 살펴봤어요.",
        related_owned_code="OWN-099",
        related_product_summary=None,
        like_count=4,
        is_draft=False,
        created_label="10.29 12:05",
    )
    db.add_all([post1, post2, post3, post4])
    db.flush()

    comments = [
        CommunityComment(
            code="C-01",
            post_id=post1.id,
            user_id=user.id,
            author_nickname="초록기록",
            body="분리배출은 지역 기준도 확인해야겠네요. 기록 공유 감사해요!",
            created_label="10.30 10:40",
        ),
        CommunityComment(
            code="C-02",
            post_id=post1.id,
            user_id=user.id,
            author_nickname="지윤",
            body="맞아요. 저도 거주지 안내를 먼저 확인했어요.",
            created_label="10.30 10:55",
        ),
    ]
    db.add_all(comments)
    db.commit()
