from datetime import date
from typing import Optional, Tuple
import calendar

REFERENCE_TODAY = date(2026, 10, 30)  # UI 시안 기준일 (2026.10.30)


def add_months(sourcedate: date, months: int) -> date:
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def calculate_product_deadline(
    status: str,
    opened_date: Optional[date],
    printed_expiry_date: Optional[date],
    pao_months: Optional[int],
) -> Tuple[Optional[date], str]:
    """
    화면 EXP-01 ('어떤 날짜를 기준으로 하나요?') 규칙 구현:
    1) 미개봉 제품은 PAO를 계산하지 않으며, 인쇄 사용기한이 있으면 그 날짜를 표시.
    2) 개봉일 + 확인한 PAO 개월수로 PAO 기한을 계산.
    3) 인쇄 사용기한과 개봉일+PAO 둘 다 알면 더 이른 날을 사용.
    4) 하나만 알면 그 날짜만 표시하고, 둘 다 모르면 None('미확인')으로 분류.
    """
    if status == "unopened" or not opened_date:
        if printed_expiry_date:
            return printed_expiry_date, "개봉 전 인쇄 사용 기한 기준"
        return None, "기한 확인 필요 · 미개봉"

    pao_deadline = add_months(opened_date, pao_months) if (opened_date and pao_months) else None

    if printed_expiry_date and pao_deadline:
        if pao_deadline <= printed_expiry_date:
            return pao_deadline, f"{opened_date.strftime('%Y.%m.%d')} + PAO {pao_months}개월 (더 이른 날짜 적용)"
        else:
            return printed_expiry_date, f"인쇄 사용 기한 ({printed_expiry_date.strftime('%Y.%m.%d')}) 적용 (더 이른 날짜)"
    elif pao_deadline:
        return pao_deadline, f"{opened_date.strftime('%Y.%m.%d')} + PAO {pao_months}개월"
    elif printed_expiry_date:
        return printed_expiry_date, f"인쇄 사용 기한 ({printed_expiry_date.strftime('%Y.%m.%d')}) 기준 (PAO 미등록)"
    else:
        return None, "기한 확인 필요 · PAO 미등록"


def compute_d_day(deadline: Optional[date], today: date = REFERENCE_TODAY) -> Optional[int]:
    if not deadline:
        return None
    return (deadline - today).days
