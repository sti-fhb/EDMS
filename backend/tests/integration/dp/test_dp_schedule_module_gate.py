"""排程編輯需為該 job 所屬模組之管理者（US11 / #325 Security M-2）。

## 這個閘補的是什麼

router-level 的 `require_any_module_admin()` 對**總覽**是對的——唯讀共用項，任一模組
管理者都看得到全部 job。但 `PUT` 會改 `CRON_EXPR` 與 `IS_ENABLED`，而排程驅動的是各模組
的業務批次：DM 管理者能停用 ET 的成績結清、ET 管理者能改 DM 的簽核催辦頻率。

這類缺口特別難察覺——停用一個 job **不會有任何錯誤訊息**，只是那件事從此不再發生。

## 平台自身的排程（`MODULE='DP'`）為何維持共用

`module_admin_gate` 沒有 `DP` 的 checker（平台沒有「DP 管理者」這個角色概念），一律以
所屬模組判定會讓 `SCHDP001` 變成**沒有任何人**能維護。故未註冊 checker 的模組回退為
router-level 的同一組門檻——與本次變更前行為相同。
"""

import pytest

from app.core.auth import create_access_token
from app.core.module_admin import module_admin_gate
from app.core.utils import utcnow
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration


@pytest.fixture
def only_dm_admin():
    """操作者是 DM 管理者、**不是** ET 管理者。"""
    from app.dm.roles.gate import dm_is_module_admin
    from app.et.roles.gate import et_is_module_admin

    async def _yes(_db, _user_id):
        return True

    async def _no(_db, _user_id):
        return False

    module_admin_gate.register("DM", _yes)
    module_admin_gate.register("ET", _no)
    yield
    module_admin_gate.register("DM", dm_is_module_admin)
    module_admin_gate.register("ET", et_is_module_admin)


@pytest.fixture
def only_et_admin():
    """操作者是 ET 管理者、**不是** DM 管理者。"""
    from app.dm.roles.gate import dm_is_module_admin
    from app.et.roles.gate import et_is_module_admin

    async def _yes(_db, _user_id):
        return True

    async def _no(_db, _user_id):
        return False

    module_admin_gate.register("ET", _yes)
    module_admin_gate.register("DM", _no)
    yield
    module_admin_gate.register("ET", et_is_module_admin)
    module_admin_gate.register("DM", dm_is_module_admin)


async def _seed_user(db, user_id="gatecheck"):
    now = utcnow()
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash="x",
            user_name="閘測試者",
            status="ACTIVE",
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
            deleted=0,
        )
    )
    await db.flush()


def _auth(user_id="gatecheck"):
    return {"Authorization": f"Bearer {create_access_token(sub=user_id, ttl_minutes=15)}"}


def _payload(**over):
    return {"job_name": "測試用名稱", "cron_expr": "0 9 * * *", "is_enabled": True, **over}


@pytest.mark.usefixtures("only_dm_admin")
async def test_DM管理者不可編輯ET排程(client, db):
    """停用 SCHET002 等於讓到期關閉與逾期作答結清長期不發生，而畫面上毫無異常。"""
    await _seed_user(db)

    r = await client.put("/api/dp/schedules/SCHET002", json=_payload(is_enabled=False), headers=_auth())

    assert r.status_code == 403
    assert r.json()["error_code"] == "DP_AUTH_006"


@pytest.mark.usefixtures("only_dm_admin")
async def test_DM管理者可編輯DM排程(client, db):
    await _seed_user(db)

    r = await client.put("/api/dp/schedules/SCHDM001", json=_payload(), headers=_auth())

    assert r.status_code == 200, r.text


@pytest.mark.usefixtures("only_et_admin")
async def test_ET管理者可編輯ET排程(client, db):
    await _seed_user(db)

    r = await client.put("/api/dp/schedules/SCHET002", json=_payload(), headers=_auth())

    assert r.status_code == 200, r.text


@pytest.mark.usefixtures("only_et_admin")
async def test_ET管理者不可編輯DM排程(client, db):
    await _seed_user(db)

    r = await client.put("/api/dp/schedules/SCHDM001", json=_payload(), headers=_auth())

    assert r.status_code == 403
    assert r.json()["error_code"] == "DP_AUTH_006"


@pytest.mark.usefixtures("only_dm_admin")
async def test_平台自身排程任一模組管理者皆可編輯(client, db):
    """`MODULE='DP'` 無對應 checker——一律以所屬模組判定會讓它沒有任何人能維護。"""
    await _seed_user(db)

    r = await client.put("/api/dp/schedules/SCHDP001", json=_payload(), headers=_auth())

    assert r.status_code == 200, r.text
