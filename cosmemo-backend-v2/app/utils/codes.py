"""
화면용 식별 코드(OWN-109, EVAL-106, P-05, R-032 ...) 채번 도우미.

[보완] 기존 코드는 `101 + db.query(Model).count()` 처럼 '행 개수'로 번호를 만들었습니다.
→ 중간 레코드를 하나 삭제하면 개수가 줄어 이미 존재하는 코드가 다시 만들어지고,
  code 컬럼이 UNIQUE 라서 IntegrityError(500)가 발생했습니다.
  (예: 게시글 P-02 삭제 후 새 글 작성 → 'P-04' 중복 → 서버 오류. 실제로 재현됨)
→ 이제는 같은 접두사를 가진 코드 중 '가장 큰 번호 + 1'을 사용합니다.
"""
import re
from typing import Type

from sqlalchemy.orm import Session


def next_code(db: Session, model: Type, prefix: str, start: int = 1, width: int = 2) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    max_num = start - 1
    for (code,) in db.query(model.code).filter(model.code.like(f"{prefix}-%")).all():
        m = pattern.match(code or "")
        if m:
            max_num = max(max_num, int(m.group(1)))
    # 아직 flush 되지 않은 같은 세션 내 신규 객체도 고려 (일괄 등록 시 중복 방지)
    for obj in db.new:
        if isinstance(obj, model):
            m = pattern.match(getattr(obj, "code", "") or "")
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{max_num + 1:0{width}d}"
