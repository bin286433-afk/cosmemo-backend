from app.utils import ocr_engine

SAMPLE = "올리브영 강남점\n2026.10.29\n라운드리프 수분 장벽 크림 1 18,000\n달빛 앰플 1 22,000\n화장솜 1 3,300\n합계 43,300"


def test_ocr_typo_still_matches_catalog(client):
    r = client.post("/register/receipt/ocr-text", json={"raw_ocr_text": "올리브영\n2026.10.29\n판테놀 세러엄 1 22,000"}).json()
    it = r["items"][0]
    assert it["matched_catalog_code"] == "CAT-03" and it["brand"] == "라운드리프"   # 브랜드를 카탈로그에서 채움


def test_text_receipt_full_flow(client):
    r = client.post("/register/receipt/upload", data={"raw_ocr_text": SAMPLE})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "review_error"     # '달빛 앰플' 브랜드 미확인
    code = body["receipt_code"]
    assert body["missing_fields"] == ["RI-2.brand"]

    # 브랜드 비어 있으면 반영 불가 (STATE-04)
    assert client.post(f"/register/receipt/{code}/commit").status_code == 422

    items = [{k: i[k] for k in ("item_code", "brand", "parsed_name", "category", "quantity", "unit_price", "is_selected", "matched_catalog_code")}
             for i in body["items"]]
    items[1].update(brand="퓨어포레")
    items[2]["category"] = "소품"
    r = client.put(f"/register/receipt/{code}/review", json={"store_name": "올리브영 강남점", "purchase_date": "2026-10-29", "total_amount": 43300, "items": items})
    assert r.json()["status"] == "review"

    conf = client.get("/register/confirm", params={"receipt_code": code}).json()
    assert conf["can_commit"] is True
    assert {d["code"] for d in conf["already_owned_list"]} >= {"OWN-101"}   # 이미 가진 수분 장벽 크림

    first = client.post(f"/register/receipt/{code}/commit").json()
    assert first["added_count"] == 2
    p = first["created_products"][0]
    assert p["printed_expiry_date"] is None and p["status"] == "unopened"    # 2027-08-31 하드코딩 제거
    assert p["purchase_date"] == "2026-10-29"

    again = client.post(f"/register/receipt/{code}/commit").json()        # 멱등
    assert again["already_committed"] is True and again["added_count"] == 0
    assert len(again["created_products"]) == 2


def test_image_without_engine_is_honest_failure(client, receipt_png):
    img = receipt_png(1)
    r = client.post("/register/receipt/upload", files={"file": ("r.png", img, "image/png")})
    body = r.json()
    assert body["screen_id"] == "STATE-03" and body["error_code"] == "no_engine"
    code = body["receipt_code"]
    review = client.get(f"/register/receipt/{code}/review").json()
    assert review["status"] == "ocr_failed" and review["items"] == []
    assert client.get(f"/register/receipt/{code}/image").status_code == 200   # 사진 보존

    # 재시도 + 기기 OCR 텍스트로 복구
    r = client.post(f"/register/receipt/{code}/retry", data={"raw_ocr_text": SAMPLE})
    assert r.json()["receipt_code"] == code and len(r.json()["items"]) == 3


def test_image_with_gemini_and_duplicate_upload(client, receipt_png, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake = {
        "raw_text": "모닝듀 진정 토너 2 30,000",
        "store_name": "올리브영 홍대점", "purchase_date": "2026-10-28", "printed_total": 30000, "discount_total": 0,
        "items": [{"raw_name": "모닝듀 진정 토너", "brand": "모닝듀", "product_name": "진정 토너", "quantity": 2,
                   "unit_price": 15000, "line_total": 30000, "is_cosmetic": True}],
    }
    calls = []
    monkeypatch.setattr(ocr_engine, "call_gemini_vision", lambda b, m: calls.append(1) or fake)
    img = receipt_png(2)
    r1 = client.post("/register/receipt/upload", files={"file": ("r.jpg", img, "image/png")}).json()
    assert r1["engine_used"].startswith("gemini") and r1["items"][0]["matched_catalog_code"] == "CAT-02"
    assert r1["total_amount"] == 30000 and r1["confidence"] == 1.0

    r2 = client.post("/register/receipt/upload", files={"file": ("r.jpg", img, "image/png")}).json()
    assert r2["reused_existing_draft"] is True and r2["receipt_code"] == r1["receipt_code"]
    assert len(calls) == 1                                      # 같은 사진은 API 재호출 안 함


def test_gemini_error_falls_back_to_client_text(client, receipt_png, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    def boom(b, m):
        raise ocr_engine.GeminiError("HTTP 429 할당량 초과")
    monkeypatch.setattr(ocr_engine, "call_gemini_vision", boom)
    r = client.post("/register/receipt/upload", files={"file": ("r.png", receipt_png(3), "image/png")}, data={"raw_ocr_text": SAMPLE}).json()
    assert r["engine_used"].startswith("client-ocr-text") and len(r["items"]) == 3


def test_upload_validation(client):
    assert client.post("/register/receipt/upload", files={"file": ("x.png", b"\x89PNG broken", "image/png")}).status_code == 422
    assert client.post("/register/receipt/upload", files={"file": ("x.pdf", b"%PDF", "application/pdf")}).status_code == 415
    assert client.post("/register/receipt/upload").status_code == 400
    big = b"0" * (10 * 1024 * 1024 + 10)
    assert client.post("/register/receipt/upload", files={"file": ("x.jpg", big, "image/jpeg")}).status_code == 413


def test_other_users_receipt_is_hidden(client, auth_header):
    h = auth_header("other@example.com")
    assert client.get("/register/receipt/R-031/review", headers=h).status_code == 404
    assert client.post("/register/receipt/R-031/commit", headers=h).status_code == 404
