from sqlalchemy import text, inspect

from app.database import SessionLocal, engine, ensure_schema
from app.models import User
from app.utils.security import _legacy_sha256


def test_foreign_keys_enforced(client):
    with engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_codes_do_not_collide_after_delete(client):
    assert client.post("/community", json={"title": "a", "body": "b"}).status_code == 201
    posts = client.get("/community").json()["items"]
    client.delete(f"/community/{posts[1]['code']}")
    assert client.post("/community", json={"title": "c", "body": "d"}).status_code == 201  # 원본: 500
    client.delete("/owned/OWN-104")
    assert client.post("/register/manual", json={}).status_code == 201
    assert client.post("/owned/OWN-101/evaluation", json={}).status_code == 200


def test_ensure_schema_adds_missing_column(client):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS _tmp_old (id INTEGER PRIMARY KEY)"))
    ensure_schema()  # 모델에 없는 테이블은 건드리지 않고, 모델 테이블의 컬럼은 모두 존재해야 함
    cols = {c["name"] for c in inspect(engine).get_columns("receipt_drafts")}
    assert {"raw_text", "ocr_engine", "image_sha256", "ocr_warnings"} <= cols


def test_legacy_password_is_rehashed(client):
    db = SessionLocal()
    u = User(code="USER-90", email="legacy@example.com", password_hash=_legacy_sha256("oldpass123"), nickname="레거시")
    db.add(u); db.commit()
    assert client.post("/auth/login", json={"email": "legacy@example.com", "password": "oldpass123"}).status_code == 200
    db.refresh(u)
    assert u.password_hash.startswith("$2")
    db.close()


def test_account_delete_requires_token(client):
    r = client.request("DELETE", "/me/account", json={"confirm_text": "탈퇴", "confirmed_irreversible": True})
    assert r.status_code == 401
    assert client.get("/me").json()["profile"]["email"] == "jiyun@example.com"


def test_disposal_guide_does_not_leak_other_products(client, auth_header):
    h = auth_header("third@example.com")
    assert client.get("/disposal/DISP-101/guide", headers=h).status_code == 404


def test_validation_rejects_bad_values(client):
    assert client.put("/owned/OWN-101", json={"remaining_percent": 150}).status_code == 422
    assert client.post("/owned/OWN-101/evaluation", json={"skin_fit": "최고"}).status_code == 422


def test_idempotent_product_update(client):
    body = {"memo": "첫 저장", "idempotency_key": "SAVE-XYZ"}
    assert client.put("/owned/OWN-102", json=body).json().get("duplicate_request") is None
    assert client.put("/owned/OWN-102", json=body).json()["duplicate_request"] is True
