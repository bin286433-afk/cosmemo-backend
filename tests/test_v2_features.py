"""v2: 알림 스케줄러 · 기록 기반 추천 · 계절 케어 · 로그아웃/비밀번호 재설정 · 구매 전 체크"""
from datetime import date, timedelta

from app.database import SessionLocal
from app.models import RevokedToken, _utcnow
from app.services.notifications import _expiry_stage, run_notification_job

TODAY = date(2026, 10, 30)  # conftest 의 REFERENCE_DATE


def _product(client, h, name, opened: date, pao: int, **kw):
    body = {"brand": "테스트", "name": name, "category": "스킨케어", "main_ingredients": kw.pop("ings", ["판테놀"]),
            "status": "in_use", "opened_date": opened.isoformat(), "printed_expiry_date": None, "pao_months": pao,
            "catalog_code": None, **kw}
    r = client.post("/register/manual", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["created_product"]["code"]


# ---------------- 알림 ----------------
def test_expiry_stage_rules():
    th = [30, 7, 0]
    assert [_expiry_stage(d, th) for d in (40, 30, 13, 7, 5, 0, -1)] == [None, "30", "30", "7", "7", "0", "expired"]


def test_notifications_generated_once_per_stage(client, auth_header):
    h = auth_header("noti@example.com")
    # 개봉 2026-05-12 + 6개월 = 11-12 → D-13 (30일 단계)
    code = _product(client, h, "알림 크림", date(2026, 5, 12), 6)
    items = client.get("/notifications", headers=h).json()["items"]
    expiry = [n for n in items if n["related_owned_code"] == code and n["category"] == "사용 기한"]
    assert len(expiry) == 1 and "13일 남았어요" in expiry[0]["title"]
    assert any(n["category"] == "계절 안내" and "가을" in n["title"] for n in items)
    assert any(n["category"] == "평가 기록" and n["related_owned_code"] == code for n in items)  # 개봉 14일+ 평가 없음

    # 다시 열어도 중복 생성 안 됨
    again = client.post("/notifications/run", headers=h).json()
    assert again["created"] == 0

    # 개봉일을 바꿔 D-5 가 되면 '7일' 단계 알림이 새로 생김
    client.put(f"/owned/{code}", json={"opened_date": "2026-05-04"}, headers=h)   # +6개월 = 11-04 → D-5
    created = client.post("/notifications/run", headers=h).json()
    assert created["created"] == 1 and "5일 남았어요" in created["items"][0]["title"]

    # 평가를 남긴 제품은 다음 평가 권유가 나오지 않고, 단일 읽음 처리
    n_code = created["items"][0]["code"]
    r = client.post(f"/notifications/{n_code}/read", headers=h).json()
    assert r["is_read"] is True and r["target_path"] == f"/owned/{code}"


def test_expired_and_settings_respected(client, auth_header):
    h = auth_header("noti2@example.com")
    client.put("/me/notifications", json={"notify_expiry_enabled": True, "notify_expiry_days": [7], "notify_time": "09:00",
                                          "notify_seasonal": False, "notify_community": False, "notify_evaluation": False,
                                          "marketing_agreed": False}, headers=h)
    _product(client, h, "지난 토너", date(2026, 1, 1), 6)       # 07-01 기한 → 지남
    _product(client, h, "여유 세럼", date(2026, 9, 1), 12)      # 2027-09-01 → 해당 없음
    _product(client, h, "13일 크림", date(2026, 5, 12), 6)      # D-13 이지만 설정이 [7] 이라 아직 아님
    items = client.get("/notifications", headers=h).json()["items"]
    assert [n["title"] for n in items] == ["지난 토너 기한이 지났어요"]


def test_scheduler_job_purges_expired_tokens(client):
    db = SessionLocal()
    db.add(RevokedToken(jti="old-jti", user_id=1, expires_at=_utcnow() - timedelta(days=1)))
    db.commit()
    result = run_notification_job(db)
    assert result["purged_tokens"] >= 1
    assert not db.query(RevokedToken).filter(RevokedToken.jti == "old-jti").first()
    db.close()


# ---------------- 로그아웃 · 비밀번호 재설정 ----------------
def _login(client, email, pw="password123"):
    r = client.post("/auth/login", json={"email": email, "password": pw})
    return {"Authorization": f"Bearer {r.json()['access_token']}"} if r.status_code == 200 else None


def test_logout_revokes_only_this_device(client, auth_header):
    auth_header("logout@example.com")
    a, b = _login(client, "logout@example.com"), _login(client, "logout@example.com")
    assert client.post("/me/logout", headers=a).status_code == 200
    assert client.get("/me", headers=a).status_code == 401
    assert client.get("/me", headers=b).status_code == 200
    assert client.post("/me/logout-all", headers=b).status_code == 200
    assert client.get("/me", headers=b).status_code == 401
    assert client.post("/me/logout").status_code == 401        # 토큰 없이 로그아웃 불가


def test_password_reset_flow(client, auth_header):
    auth_header("reset@example.com")
    old = _login(client, "reset@example.com")
    unknown = client.post("/auth/password-reset", json={"email": "nobody@example.com"}).json()
    r = client.post("/auth/password-reset", json={"email": "reset@example.com"}).json()
    assert r["message"] == unknown["message"] and "dev_reset_token" not in unknown
    token = r["dev_reset_token"]
    ok = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "newpass999", "new_password_confirm": "newpass999"})
    assert ok.status_code == 200
    assert _login(client, "reset@example.com", "newpass999") is not None
    assert _login(client, "reset@example.com") is None
    assert client.get("/me", headers=old).status_code == 401              # 기존 토큰 무효
    reuse = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "again1234", "new_password_confirm": "again1234"})
    assert reuse.status_code == 400


# ---------------- 추천 · 계절 ----------------
def test_recommendations_from_records(client):
    r = client.get("/recommendations").json()
    assert r["state"] == "ready"
    assert r["primary_recommendation"]["product"]["code"] == "OWN-102"     # 5.0 · 잘 맞아요 · 재구매 · 60% 남음
    assert any(c["code"] == "OWN-099" for c in r["repurchase_candidates"])  # 다 쓴 5.0 제품
    assert any(w["ingredient"] == "에탄올" for w in r["watch_ingredients"])  # 맞지 않았던 젤에만 있던 성분


def test_recommendations_insufficient(client, auth_header):
    h = auth_header("newbie@example.com")
    r = client.get("/recommendations", headers=h).json()
    assert r["state"] == "insufficient-records" and r["primary_recommendation"] is None


def test_seasonal(client):
    cur = client.get("/seasonal/current").json()
    assert cur["season"] == "autumn" and cur["related_owned_products"]
    win = client.get("/seasonal/winter").json()
    assert all(p["matched_ingredients"] for p in win["related_owned_products"])
    assert client.get("/seasonal/rainy").status_code == 404
    assert client.get("/home").json()["seasonal_note"]["target_path"] == "/seasonal/autumn"


# ---------------- 구매 전 체크 · 커뮤니티 ----------------
def test_precheck_and_compare(client):
    r = client.get("/precheck", params={"q": "진정 토너"}).json()
    assert [p["code"] for p in r["same_owned"]] == ["OWN-102"]
    assert any(w["owned_code"] == "OWN-098" and "병풀추출물" in w["shared_ingredients"] for w in r["mismatched_warnings"])
    same = client.get("/precheck/compare", params={"candidate": "CAT-02", "owned": "OWN-102"}).json()
    diff = client.get("/precheck/compare", params={"candidate": "CAT-05", "owned": "OWN-102"}).json()
    assert same["is_same_product"] is True and diff["is_same_product"] is False
    assert client.get("/precheck", params={"q": "무지개 앰플"}).json()["screen_id"] == "STATE-02"


def test_community_labels_and_reference(client):
    r = client.post("/community", json={"title": "토너 후기", "body": "좋아요", "related_owned_code": "OWN-102",
                                         "include_rating": True}).json()
    detail = client.get(f"/community/{r['post_code']}").json()
    assert detail["shared_rating"] == 5.0 and detail["created_label"].startswith("오늘")
    ref = client.get("/recommendations").json()["community_reference"]
    assert ref and ref["name"] == "진정 토너" and ref["review_count"] >= 1
