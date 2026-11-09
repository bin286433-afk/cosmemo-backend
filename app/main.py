from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import Base, engine, SessionLocal
from app.seed import seed_initial_data
from app.routers import auth, vanity, register, evaluations, disposal, community, me


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_initial_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description=(
        "코스메모(Cosmetic+Memo) 기획안 및 화면 설계도(A~H, 총 8장)를 100% 반영한 백엔드 API 서버입니다.\n"
        "- A · 시작 · 계정 만들기 (AUTH-01 ~ AUTH-06)\n"
        "- B · 홈 · 내 화장대 · 제품 관리 (HOME-01, VAN-01~02, PROD-01~04)\n"
        "- C · 영수증에서 내 화장대로 (REG-01 ~ REG-08)\n"
        "- D · 개인 평가 · 사용 기한 · 알림 (REV-01~02, EXP-01, NOTI-01)\n"
        "- E · 비우기 · 분리배출 · 다음 구매 (DIS-01~04, ARC-01, BUY-01~02)\n"
        "- F · 부가 기능 · 추천 · 계절 케어 · 커뮤니티 (REC-01, SEA-01, COM-01~03)\n"
        "- G · 마이 · 알림 환경 · 개인정보 (MY-01 ~ MY-03)\n"
        "- H · 공통 · 예외 상태 (STATE-01 ~ STATE-08)"
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API v1 프리픽스 및 화면 하단 라우트(/home, /vanity, /owned/...) 양쪽 모두 지원
for prefix in [settings.API_V1_STR, ""]:
    app.include_router(auth.router, prefix=prefix)
    app.include_router(vanity.router, prefix=prefix)
    app.include_router(register.router, prefix=prefix)
    app.include_router(evaluations.router, prefix=prefix)
    app.include_router(disposal.router, prefix=prefix)
    app.include_router(community.router, prefix=prefix)
    app.include_router(me.router, prefix=prefix)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "CosMemo Backend", "reference_date": "2026-10-30"}


from pathlib import Path
from fastapi.responses import HTMLResponse

@app.get("/app", response_class=HTMLResponse, tags=["iOS & Web App Demo"])
def serve_mobile_demo_app():
    """아이폰(iOS)·아이패드·브라우저에서 http://<PC_IP>:8000/app 접속 시 코스메모 웹앱 화면을 바로 렌더링합니다."""
    html_file = Path(__file__).resolve().parent.parent / "cosmemo_demo_app.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>cosmemo_demo_app.html 파일을 프로젝트 루트에 배치해 주세요.</h1>")
