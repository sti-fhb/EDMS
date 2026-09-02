"""指定審核者下拉之帳號狀態過濾（#250 AC12，SA Q2=A）整合測試。

原本 `list_reviewers` 只濾 `DP_USER.DELETED`，未濾 `STATUS` / `LOCKED_UNTIL`——已停用、
永遠登不進系統的帳號只要仍具 `DM_REVIEWER`（停用不清角色）就會出現在送簽下拉，選中後
該送審無人可審、只能靠撰寫者撤回。本檔驗停用 / 鎖定中者不再出現。

**範圍**：只堵「新產生」的卡死。「送審當下正常、事後才被停用」之在途送審不在此處理
（SA Q2=A 明確排除，維持 US9 撰寫者撤回機制）。
"""

from datetime import timedelta

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.roles.authz import DM_EDITOR, DM_REVIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_URL = "/api/dm/reviewers"


def _headers(sub):
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _seed_user(db, user_id, *, status="ACTIVE", locked_until=None):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=f"用戶{user_id}",
            status=status,
            locked_until=locked_until,
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def test_reviewers_excludes_disabled_and_locked(db, client):
    """停用 / 鎖定中的審核者不出現；正常審核者與鎖定已逾時者仍出現。"""
    await _seed_user(db, "rv_author")
    await _grant(db, "rv_author", DM_EDITOR)

    await _seed_user(db, "rv_ok")
    await _grant(db, "rv_ok", DM_REVIEWER)
    await _seed_user(db, "rv_off", status="DISABLED")
    await _grant(db, "rv_off", DM_REVIEWER)
    await _seed_user(db, "rv_lock", locked_until=utcnow() + timedelta(hours=1))
    await _grant(db, "rv_lock", DM_REVIEWER)
    # 鎖定已逾時＝已自動解鎖，仍應可被指定（不可誤以 LOCKED_UNTIL 非空判定）
    await _seed_user(db, "rv_exp", locked_until=utcnow() - timedelta(minutes=1))
    await _grant(db, "rv_exp", DM_REVIEWER)

    r = await client.get(_URL, headers=_headers("rv_author"))
    assert r.status_code == 200
    ids = {item["user_id"] for item in r.json()}
    assert "rv_ok" in ids, "正常審核者應出現在下拉"
    assert "rv_exp" in ids, "鎖定已逾時者已自動解鎖，應出現在下拉"
    assert "rv_off" not in ids, "已停用帳號登不進系統，不應可被指定為審核者"
    assert "rv_lock" not in ids, "鎖定中帳號登不進系統，不應可被指定為審核者"
