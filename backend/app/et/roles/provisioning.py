"""ET 預設角色授予（module-callbacks §2；SRVET002）。

由平台 DP 於**帳號建立當下**呼叫（US2 自助註冊 verify / US4 邀請啟用，共用副作用見
`app/dp/user/activation.py`）。DP 端已接線並在等待 ET 註冊。

**失敗語意與讀取型 checker 相反**：`is_module_admin` / `has_any_role` 為 fail-closed
（例外回 False）；本函式**失敗必須向上傳播**——授予失敗即為壞帳號（該使用者進不了
ET），須讓 DP 之帳號建立整筆交易回滾。故此處不捕捉例外。
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.constants import ROLE_STUDENT
from app.et.roles.models import EtUserRole

_SYSTEM_USER = "SYSTEM"


async def grant_default_student_role(db: AsyncSession, user_id: str) -> None:
    """於同交易內授予使用者 ET「學員」角色；受訓單位標籤預設「未指派」。

    **冪等**：已存在該角色（無論啟用與否）時不重複寫入、不報錯——重跑驗證信 /
    重寄邀請等情境會重複觸發本函式。
    """
    existing = await db.scalar(select(EtUserRole).where(EtUserRole.user_id == user_id, EtUserRole.role == ROLE_STUDENT))
    if existing is not None:
        return

    db.add(
        EtUserRole(
            user_id=user_id,
            role=ROLE_STUDENT,
            is_active=True,
            created_user=_SYSTEM_USER,
            created_date=datetime.now(timezone.utc),
            deleted=0,
        )
    )
    await db.flush()
