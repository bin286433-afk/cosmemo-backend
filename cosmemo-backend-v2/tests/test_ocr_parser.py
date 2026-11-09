import pytest

from app.database import SessionLocal
from app.models import CatalogProduct
from app.utils.ocr_engine import best_catalog_match, parse_receipt_text_rules, extract_date
from datetime import date


@pytest.fixture(scope="module")
def db(client):  # client fixture가 시드 데이터를 만들어 둠
    s = SessionLocal()
    yield s
    s.close()


CASES = [
    ("기본 샘플",
     "보태닉 스토어 강남점\n2026.10.30 14:20\n라운드리프 수분 장벽 크림 1 18,000\n라운드리프 판테놀 세럼 1 22,000\n화장솜 1 3,300\n합계 43,300원",
     "2026-10-30", 43300, [("라운드리프", "수분 장벽 크림", 1, 18000, "CAT-01"), ("라운드리프", "판테놀 세럼", 1, 22000, "CAT-03"), (None, None, 1, 3300, None)]),
    ("단가 수량 금액", "올리브영 강남점\n2026-10-02\n토리든 다이브인 세럼 18,000 2 36,000\n합계 36,000",
     "2026-10-02", 36000, [("토리든", "다이브인 세럼", 2, 18000, None)]),
    ("할인 줄", "올리브영\n2026.10.02\n라운드랩 독도 토너 15,000\n할인 -3,000\n합계 12,000",
     "2026-10-02", 12000, [("라운드랩", "독도 토너", 1, 15000, None)]),
    ("한글 날짜", "시코르\n2026년 10월 2일\n롬앤 쥬시 래스팅 틴트 1 13,000",
     "2026-10-02", 13000, [("롬앤", "쥬시 래스팅 틴트", 1, 13000, None)]),
    ("두 줄 + 바코드 + 2자리 연도",
     "올리브영 명동점\n26.10.02 13:22\n[토리든]다이브인 세럼 50ml\n8809876543210\n18,000 1 18,000\n아누아 어성초 토너 x2 50,000\n합 계 68,000\n카드승인 68,000",
     "2026-10-02", 68000, [("토리든", "다이브인 세럼 50ml", 1, 18000, None), ("아누아", "어성초 토너", 2, 25000, None)]),
    ("금액이 단가였던 영수증(합계로 보정)", "올리브영\n2026.10.01\n모닝듀 진정 토너 2 15,000\n합계 30,000",
     "2026-10-01", 30000, [("모닝듀", "진정 토너", 2, 15000, "CAT-02")]),
    ("전각 숫자", "올리브영\n２０２６．１０．０３\n클리오 킬커버 쿠션 １ ３２，０００원\n결제금액 ₩32,000",
     "2026-10-03", 32000, [("클리오", "킬커버 쿠션", 1, 32000, None)]),
]


@pytest.mark.parametrize("name,text,exp_date,exp_total,exp_items", CASES, ids=[c[0] for c in CASES])
def test_receipt_formats(db, name, text, exp_date, exp_total, exp_items):
    r = parse_receipt_text_rules(text, db)
    assert r["purchase_date"] == exp_date
    assert r["total_amount"] == exp_total
    assert len(r["items"]) == len(exp_items)
    for got, (brand, pname, qty, unit, cat) in zip(r["items"], exp_items):
        if pname:
            assert got["brand"] == brand and got["parsed_name"] == pname
        assert (got["quantity"], got["unit_price"], got["matched_catalog_code"]) == (qty, unit, cat)


def test_non_cosmetic_excluded(db):
    r = parse_receipt_text_rules(CASES[0][1], db)
    cotton = r["items"][2]
    assert cotton["is_cosmetic"] is False and cotton["is_selected"] is False and cotton["category"] == "소품"


def test_unreadable_returns_no_items(db):
    r = parse_receipt_text_rules("흐릿함\n???\n0 0", db)
    assert r["items"] == [] and r["confidence"] == 0.0


def test_total_mismatch_warns(db):
    r = parse_receipt_text_rules("올리브영\n2026.10.01\n토리든 다이브인 세럼 1 18,000\n합계 20,000", db)
    assert any("합계" in w for w in r["warnings"])
    assert r["confidence"] < 1.0


def test_future_and_invalid_dates_rejected():
    assert extract_date("2026.13.40", date(2026, 11, 9)) is None
    assert extract_date("2027.01.01", date(2026, 11, 9)) is None
    assert extract_date("TEL 02-123-4567", date(2026, 11, 9)) is None
    assert extract_date("사업자 123-45-67890", date(2026, 11, 9)) is None


@pytest.mark.parametrize("brand,name,expected", [
    ("아누아", "판테놀 세럼", None),           # 브랜드가 다르면 매칭 금지
    (None, "세럼", None),                      # 단어 하나로는 매칭 금지
    (None, "판테놀 세럼", "CAT-03"),
    ("라운드리프", "수분장벽크림 50ml 기획", "CAT-01"),  # 띄어쓰기·용량·기획 문구 무시
])
def test_catalog_matching(db, brand, name, expected):
    m, _ = best_catalog_match(db.query(CatalogProduct).all(), brand, name)
    assert (m.code if m else None) == expected
