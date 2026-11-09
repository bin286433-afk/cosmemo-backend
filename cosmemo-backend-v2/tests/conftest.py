"""테스트용 임시 DB/업로드 폴더를 쓰도록 환경변수를 app import 전에 설정합니다."""
import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="cosmemo-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{Path(_TMP, 'test.db').as_posix()}",
    "UPLOAD_DIR": str(Path(_TMP, "uploads")),
    "GEMINI_API_KEY": "",
    "ENABLE_TESSERACT": "false",
    "DEMO_MODE": "true",
    "REFERENCE_DATE": "2026-10-30",
    "SCHEDULER_ENABLED": "false",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def receipt_png():
    """흰 바탕에 글자가 있는 그럴듯한 영수증 이미지 (Pillow로 생성)."""
    from PIL import Image, ImageDraw
    def make(seed: int = 0) -> bytes:
        img = Image.new("RGB", (600, 900), "white")
        d = ImageDraw.Draw(img)
        for i in range(12):
            d.text((40, 40 + i * 60), f"LINE {i} {seed} 18,000", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    return make


@pytest.fixture()
def auth_header(client):
    def make(email: str, nickname: str = "테스터") -> dict:
        r = client.post("/auth/signup", json={
            "email": email, "password": "password123", "password_confirm": "password123", "nickname": nickname,
        })
        assert r.status_code in (201, 409), r.text
        r = client.post("/auth/login", json={"email": email, "password": "password123"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return make
