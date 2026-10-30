from datetime import datetime, timedelta
from typing import Optional
import hashlib
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)


def get_password_hash(password: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{password}".encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return get_password_hash(plain_password) == hashed_password


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode = {"sub": str(subject), "exp": expire}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    JWT 토큰이 있으면 해당 사용자를 반환하고,
    로컬 프론트엔드 연동 테스트 편의를 위해 토큰이 없을 때는 기본 시드 사용자(USER-01, 지윤)를 반환합니다.
    STATE-08(세션 만료 테스트)은 Authorization: Bearer expired 로 재현할 수 있습니다.
    """
    if token == "expired":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "STATE-08",
                "message": "로그인이 만료되었어요. 안전하게 계속하려면 다시 로그인해 주세요. 작성 중이던 내용은 버리지 않고 보관했어요.",
            },
        )
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email: str = payload.get("sub")
            if email:
                user = db.query(User).filter(User.email == email).first()
                if user:
                    return user
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "STATE-08",
                    "message": "로그인이 만료되었어요. 다시 로그인해 주세요.",
                },
            )
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    return user
