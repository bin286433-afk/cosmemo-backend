"""
프로젝트 환경 설정.

[보완] 기존 코드는 os.getenv()만 사용해서 .env 파일을 전혀 읽지 않았습니다.
→ .env에 GEMINI_API_KEY를 넣어도 서버가 키를 모르는 상태였음.
pydantic-settings의 BaseSettings로 바꿔 프로젝트 루트의 .env를 자동으로 읽습니다.
"""
from datetime import date
from pathlib import Path
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # cosmemo-backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "CosMemo API (코스메모 백엔드)"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "cosmemo-super-secret-jwt-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    DATABASE_URL: str = f"sqlite:///{(BASE_DIR / 'cosmemo.db').as_posix()}"
    CORS_ORIGINS: str = "*"

    # 데모 모드: 토큰 없이 호출하면 시드 사용자(지윤)로 동작 (시연 편의용)
    # 실제 배포 시 DEMO_MODE=false 로 두면 토큰이 필수가 됩니다.
    DEMO_MODE: bool = True
    # 시연 기준일. 비워두면(REFERENCE_DATE="") 서버의 실제 오늘 날짜를 사용합니다.
    REFERENCE_DATE: str = "2026-10-30"

    # --- 시간대 / 스케줄러 ---
    TZ_OFFSET_HOURS: int = 9                 # 한국 표준시(KST, 서머타임 없음)
    SCHEDULER_ENABLED: bool = True           # 서버 안에서 주기적으로 알림 생성
    SCHEDULER_INTERVAL_MINUTES: int = 60
    EVALUATION_REMINDER_DAYS: int = 14       # 개봉 후 N일 지나도 평가가 없으면 기록 권유 알림
    PASSWORD_RESET_MINUTES: int = 30

    # --- OCR ---
    GEMINI_API_KEY: str = ""
    # gemini-1.5-flash 는 이미 서비스 종료된 모델이라 호출 시 404가 납니다.
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_TIMEOUT_SECONDS: int = 30
    # 로컬 Tesseract OCR 사용 여부 (pytesseract + tesseract(kor) 설치 시에만 동작)
    ENABLE_TESSERACT: bool = True
    UPLOAD_DIR: str = str(BASE_DIR / "uploads")
    MAX_UPLOAD_MB: int = 10
    # 카탈로그 자동 매칭 최소 점수 (0~1). 낮추면 매칭이 늘고 오매칭도 늘어납니다.
    CATALOG_MATCH_THRESHOLD: float = 0.62

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()] or ["*"]

    def reference_today(self) -> date:
        if self.REFERENCE_DATE.strip():
            try:
                return date.fromisoformat(self.REFERENCE_DATE.strip())
            except ValueError:
                pass
        return date.today()


settings = Settings()
