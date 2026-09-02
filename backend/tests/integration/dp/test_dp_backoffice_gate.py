"""DP 後台授權閘（#250 AC4~AC6）整合測試：六項功能限「ET 或 DM 任一模組管理者」。

背景：DP 後台六項功能之操作者於 spec 皆明寫為「作為 ET 或 DM 管理者」——
使用者管理（spec_us4）/ 系統參數（us5）/ 權限管理（us7）/ 通知範本（us9）/
操作記錄（us10）/ 排程總覽（us11）。但實作長期只掛 `get_jwt_payload`（僅認證），
任何登入者都能讀寫後台。本檔驗 `require_any_module_admin` 落地後的授權行為。

門檻是「任一」：只具 ET 管理者者仍可進入（後台為兩模組共用）。
"""

import pytest

from app.core.auth import create_access_token
from app.core.module_admin import module_admin_gate
from app.core.utils import utcnow
from app.dm.roles.gate import dm_is_module_admin
from app.dp.users.models import DpUser
from app.et.roles.gate import et_is_module_admin

pytestmark = pytest.mark.integration

# 各後台 router 的代表性 GET 端點（一 router 一條，抽樣即可——閘掛在 router-level）
_BACKOFFICE_ENDPOINTS = [
    "/api/dp/users",
    "/api/dp/params",
    "/api/dp/notify/templates",
    "/api/dp/audit/logs",
    "/api/dp/schedules",
    "/api/dp/roles/modules",
]


def _headers(sub):
    return {"Authorization": f"Bearer {create_access_token(sub=sub, ttl_minutes=15)}"}


async def _seed_user(db, user_id):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@e.com",
            pwd_hash="x",
            user_name=f"用戶{user_id}",
            pwd_changed_date=utcnow(),
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def _always(_db, _user_id):
    return True


async def _never(_db, _user_id):
    return False


@pytest.fixture
def restore_gates():
    """teardown 還原 main.py 註冊之真實 checker（ET / DM 皆已接線，unregister 會讓後續測試看到未接線狀態）。"""
    yield
    module_admin_gate.register("ET", et_is_module_admin)
    module_admin_gate.register("DM", dm_is_module_admin)


@pytest.mark.parametrize("url", _BACKOFFICE_ENDPOINTS)
async def test_non_admin_forbidden(db, client, restore_gates, url):
    """非 ET 且非 DM 管理者 → 403 DP_AUTH_006（AC5）。"""
    await _seed_user(db, "bo_none")
    module_admin_gate.register("ET", _never)
    module_admin_gate.register("DM", _never)
    r = await client.get(url, headers=_headers("bo_none"))
    assert r.status_code == 403, f"{url} 應擋下非管理者"
    assert r.json()["error_code"] == "DP_AUTH_006"


@pytest.mark.parametrize("url", _BACKOFFICE_ENDPOINTS)
async def test_dm_admin_allowed(db, client, restore_gates, url):
    """DM 管理者 → 放行並正常回應（AC6）。

    斷言 200 而非「非 403」：後者會讓 500（授權以外的錯誤）被誤判為通過。
    六個端點皆為無參數 GET，正常情況應可回 200。
    """
    await _seed_user(db, "bo_dm")
    module_admin_gate.register("ET", _never)
    module_admin_gate.register("DM", _always)
    r = await client.get(url, headers=_headers("bo_dm"))
    assert r.status_code == 200, f"{url} 應放行 DM 管理者（回 {r.status_code}）"


async def test_et_admin_only_still_allowed(db, client, restore_gates):
    """僅具 ET 管理者（DM 非管理者）→ 仍可進入後台（門檻為「任一」，AC6）。"""
    await _seed_user(db, "bo_et")
    module_admin_gate.register("ET", _always)
    module_admin_gate.register("DM", _never)
    r = await client.get("/api/dp/users", headers=_headers("bo_et"))
    assert r.status_code == 200


async def test_backoffice_requires_token(client):
    """未帶 token → 401（認證仍先於授權）。"""
    r = await client.get("/api/dp/users")
    assert r.status_code == 401


async def test_profile_not_gated(db, client, restore_gates):
    """個人資料維護不受後台閘管制——spec_us8 之操作者為「已登入的使用者」，非管理者。"""
    await _seed_user(db, "bo_self")
    module_admin_gate.register("ET", _never)
    module_admin_gate.register("DM", _never)
    r = await client.get("/api/dp/user/me", headers=_headers("bo_self"))
    assert r.status_code == 200
