"""
SQLAlchemy 엔진 / 세션 / 경량 마이그레이션.

[보완]
1) SQLite는 기본적으로 외래키(FOREIGN KEY) 제약을 검사하지 않습니다.
   → 연결할 때마다 PRAGMA foreign_keys=ON 을 켜서 고아 레코드(주인 없는 평가·영수증 품목)를 막습니다.
2) WAL 모드 + busy_timeout: 업로드(OCR) 요청과 조회 요청이 겹칠 때 'database is locked' 오류를 줄입니다.
3) Base.metadata.create_all()은 '없는 테이블'만 만들고 기존 테이블에 새 컬럼을 추가하지 않습니다.
   → ensure_schema()가 모델에는 있는데 DB에는 없는 컬럼을 ALTER TABLE로 추가합니다.
     (기존 cosmemo.db 를 지우지 않아도 새 OCR 컬럼들이 생깁니다.)
"""
import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger("cosmemo.db")

IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 15} if IS_SQLITE else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_schema() -> None:
    """모델에 새로 추가된 컬럼을 기존 테이블에 반영하는 간단한 마이그레이션 (nullable 컬럼만)."""
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col_type}'))
                logger.info("마이그레이션: %s.%s 컬럼 추가", table.name, col.name)
