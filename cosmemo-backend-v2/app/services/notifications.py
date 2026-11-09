"""
알림 생성 서비스 (NOTI-01, MY-02)

사용자 알림 설정(notify_expiry_days = [30, 7, 0], notify_time, notify_seasonal, notify_evaluation)에 따라
알림함에 넣을 알림을 만듭니다. 스케줄러가 주기적으로 호출하고, 같은 알림은 dedupe_key 로 한 번만 생성됩니다.

▸ 사용 기한: '단계' 방식 — 남은 일수(d)가 설정값 이하로 처음 들어가는 단계마다 1회
    예) 설정 [30, 7, 0], d=13 → '30일' 단계 알림 1회. d=6 이 되면 '7일' 단계 알림 1회. d=0 '당일', d<0 '기한 지남'
    → 서버가 며칠 꺼져 있다 켜져도 놓친 단계를 따라잡음 (정확히 'd==7' 인 날만 보내는 방식의 약점 보완)
    → 개봉일·PAO 를 수정해 기한이 바뀌면 키에 기한이 포함되어 있으므로 새 기한 기준으로 다시 알림
▸ 계절 안내: 계절이 바뀌면 연·계절당 1회
▸ 평가 기록: 개봉 후 EVALUATION_REMINDER_DAYS 일이 지났는데 평가가 없는 제품마다 1회
▸ 푸시: 이 서버에는 FCM/APNs 연동이 없어 send_push() 가 로그만 남깁니다. (OS 알림 권한이 있는 사용자만 대상)
"""
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Evaluation, Notification, OwnedProduct, RevokedToken, User, _utcnow
from app.utils.codes import next_code
from app.utils.deadline import compute_d_day, get_today
from app.utils.seasons import SEASONS, season_of
from app.utils.timeutil import now_local

logger = logging.getLogger("cosmemo.notifications")


def send_push(user: User, noti: Notification) -> None:
    """실제 푸시 연동 지점. FCM 등을 붙일 때 이 함수만 바꾸면 됩니다."""
    logger.info("[푸시 대체] %s ← %s", user.email, noti.title)


def _md(d: date) -> str:
    return d.strftime("%m.%d")


def _expiry_stage(d_day: int, thresholds: List[int]) -> Optional[str]:
    if d_day < 0:
        return "expired"
    for t in sorted(set(int(x) for x in thresholds if int(x) >= 0)):
        if d_day <= t:
            return str(t)
    return None


def _candidates(db: Session, user: User, today: date) -> List[dict]:
    out: List[dict] = []
    active = (
        db.query(OwnedProduct)
        .filter(OwnedProduct.user_id == user.id, OwnedProduct.status != "archived")
        .all()
    )

    if user.notify_expiry_enabled:
        thresholds = user.notify_expiry_days or [30, 7]
        for p in active:
            if not p.calculated_deadline:
                continue
            d = compute_d_day(p.calculated_deadline, today)
            stage = _expiry_stage(d, thresholds)
            if stage is None:
                continue
            if stage == "expired":
                title = f"{p.name} 기한이 지났어요"
                body = f"{_md(p.calculated_deadline)} 기한이 지났어요. 사용을 중단하고 분리배출을 확인해 주세요."
                path = f"/owned/{p.code}/end"
            elif d == 0:
                title = f"{p.name}, 오늘이 사용 기한이에요"
                body = "오늘까지 사용하고, 다 쓰지 못했다면 비우기·분리배출을 준비해요."
                path = f"/owned/{p.code}"
            else:
                title = f"{p.name}, {d}일 남았어요"
                body = f"내 기록의 적용 기한은 {_md(p.calculated_deadline)}예요. 개봉일과 남은 양을 확인해요."
                path = f"/owned/{p.code}"
            out.append({
                "category": "사용 기한", "title": title, "body": body, "target_path": path,
                "related_owned_code": p.code,
                "dedupe_key": f"EXP:{p.code}:{p.calculated_deadline.isoformat()}:{stage}",
            })

    if user.notify_seasonal:
        season = season_of(today)
        cfg = SEASONS[season]
        concerns = ", ".join(user.skin_concerns or []) or "피부"
        out.append({
            "category": "계절 안내",
            "title": f"{cfg['label']}이 왔어요, 내 루틴을 살펴봐요",
            "body": f"{concerns} 관심 프로필과 보유 성분을 기준으로 {cfg['label']} 안내를 준비했어요.",
            "target_path": f"/seasonal/{season}",
            "related_owned_code": None,
            # 겨울(12~2월)은 해를 넘기므로 12월이 속한 해로 묶음
            "dedupe_key": f"SEA:{today.year - 1 if today.month in (1, 2) else today.year}:{season}",
        })

    if user.notify_evaluation:
        cutoff = today - timedelta(days=settings.EVALUATION_REMINDER_DAYS)
        for p in active:
            if p.status != "in_use" or not p.opened_date or p.opened_date > cutoff:
                continue
            has_eval = db.query(Evaluation.id).filter(Evaluation.owned_product_id == p.id).first()
            if has_eval:
                continue
            out.append({
                "category": "평가 기록",
                "title": f"{p.name}은 어땠나요?",
                "body": "사용 경험을 나만의 기록으로 남겨요. 평가는 기본 비공개예요.",
                "target_path": f"/owned/{p.code}/evaluation/edit",
                "related_owned_code": p.code,
                "dedupe_key": f"EVAL:{p.code}",
            })
    return out


def generate_for_user(db: Session, user: User, today: Optional[date] = None) -> List[Notification]:
    """해당 사용자에게 새로 생길 알림을 만들어 저장하고 반환 (이미 보낸 알림은 건너뜀)."""
    today = today or get_today()
    existing = {
        k for (k,) in db.query(Notification.dedupe_key)
        .filter(Notification.user_id == user.id, Notification.dedupe_key.isnot(None)).all()
    }
    created: List[Notification] = []
    for c in _candidates(db, user, today):
        if c["dedupe_key"] in existing:
            continue
        noti = Notification(code=next_code(db, Notification, "N", start=1, width=2), user_id=user.id, **c)
        db.add(noti)
        try:
            db.flush()
        except IntegrityError:  # 동시에 두 스케줄러가 돈 경우
            db.rollback()
            continue
        existing.add(c["dedupe_key"])
        created.append(noti)
    db.commit()
    if user.perm_notification:
        for n in created:
            send_push(user, n)
            n.push_sent = True
        db.commit()
    return created


def _due_now(user: User, now: datetime) -> bool:
    """실제 날짜 모드에서는 사용자가 정한 알림 시각(notify_time) 이후에만 생성. 시연 기준일 모드에서는 항상."""
    if settings.REFERENCE_DATE.strip():
        return True
    try:
        hh, mm = (int(x) for x in (user.notify_time or "09:00").split(":"))
    except ValueError:
        hh, mm = 9, 0
    return (now.hour, now.minute) >= (hh, mm)


def run_notification_job(db: Session) -> dict:
    """스케줄러 1회 실행: 전체 사용자 알림 생성 + 만료된 로그아웃 토큰 정리"""
    now = now_local()
    total = 0
    for user in db.query(User).all():
        if _due_now(user, now):
            total += len(generate_for_user(db, user))
    purged = db.query(RevokedToken).filter(RevokedToken.expires_at < _utcnow()).delete()
    db.commit()
    logger.info("알림 작업 완료: 새 알림 %d건, 만료 토큰 정리 %d건", total, purged)
    return {"created": total, "purged_tokens": purged}
