"""
비밀번호 해싱 · JWT · 현재 사용자 조회

[보완]
1) 비밀번호: SECRET_KEY 를 붙인 SHA-256 한 번 → bcrypt (사용자별 salt + 느린 해시)
   - SHA-256은 GPU로 초당 수십억 번 대입 가능하고, SECRET_KEY 가 바뀌면 모든 사용자가 로그인 불가.
   - 기존 DB의 SHA-256 해시도 로그인은 되도록 호환하고, 로그인 성공 시 bcrypt 로 자동 교체(rehash).
2) 토큰 없이 요청하면 무조건 첫 번째 사용자(지윤)로 처리하던 동작 → DEMO_MODE=true 일 때만 허용.
3) 로그아웃: 토큰 jti 를 revoked_tokens 에 기록(이 기기), token_version 증가(모든 기기)
4) 회원 탈퇴처럼 되돌릴 수 없는 작업은 데모 모드에서도 실제 토큰을 요구 (get_authenticated_user).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import RevokedToken, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)


def _legacy_sha256(password: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{password}".encode("utf-8")).hexdigest()


def get_password_hash(password: str) -> str:
    # bcrypt 는 72바이트까지만 사용 → 한글 비밀번호(글자당 3바이트)를 고려해 SHA-256 으로 먼저 압축
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    if hashed_password.startswith("$2"):
        digest = hashlib.sha256(plain_password.encode("utf-8")).hexdigest().encode("ascii")
        try:
            return bcrypt.checkpw(digest, hashed_password.encode("ascii"))
        except ValueError:
            return False
    return hmac.compare_digest(_legacy_sha256(plain_password), hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    return not (hashed_password or "").startswith("$2")


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None, token_version: int = 0) -> str:
    """jti(토큰 고유 ID)와 ver(사용자 토큰 버전)를 넣어 로그아웃 시 무효화할 수 있게 함."""
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    claims = {"sub": str(subject), "exp": expire, "jti": secrets.token_hex(16), "ver": int(token_version or 0)}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def issue_token_for(user: User) -> str:
    return create_access_token(user.email, token_version=user.token_version or 0)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def revoke_token(db: Session, token: str, user: User) -> None:
    payload = decode_token(token)
    jti = payload.get("jti")
    if not jti or db.query(RevokedToken).filter(RevokedToken.jti == jti).first():
        return
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc).replace(tzinfo=None)
    db.add(RevokedToken(jti=jti, user_id=user.id, expires_at=exp))
    db.commit()


def _expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "STATE-08",
            "message": "로그인이 만료되었어요. 안전하게 계속하려면 다시 로그인해 주세요. 작성 중이던 내용은 버리지 않고 보관했어요.",
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_token(token: str, db: Session) -> User:
    if token == "expired":          # STATE-08 시연용
        raise _expired()
    try:
        payload = decode_token(token)
    except JWTError:
        raise _expired()
    email = payload.get("sub")
    user = db.query(User).filter(User.email == email).first() if email else None
    if not user:                    # 탈퇴했거나 존재하지 않는 계정의 토큰
        raise _expired()
    if int(payload.get("ver", 0)) != int(user.token_version or 0):   # 전체 로그아웃·비밀번호 변경 이후 토큰
        raise _expired()
    jti = payload.get("jti")
    if jti and db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first():  # 이 기기에서 로그아웃한 토큰
        raise _expired()
    return user


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    토큰이 있으면 해당 사용자. 토큰이 없으면
      - DEMO_MODE=true  : 시드 사용자(USER-01, 지윤) — 시연·Swagger 테스트 편의
      - DEMO_MODE=false : 401
    STATE-08(세션 만료)은 Authorization: Bearer expired 로 재현할 수 있습니다.
    """
    if token:
        return _user_from_token(token, db)
    if not settings.DEMO_MODE:
        raise HTTPException(status_code=401, detail="로그인이 필요해요.", headers={"WWW-Authenticate": "Bearer"})
    user = db.query(User).filter(User.code == "USER-01").first() or db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다.")
    return user


def get_authenticated_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """데모 모드와 관계없이 반드시 유효한 토큰이 필요한 작업용 (회원 탈퇴 등)."""
    if not token:
        raise HTTPException(status_code=401, detail="이 작업은 로그인한 상태에서만 할 수 있어요.", headers={"WWW-Authenticate": "Bearer"})
    return _user_from_token(token, db)


def get_token(token: Optional[str] = Depends(oauth2_scheme)) -> Optional[str]:
    return token
