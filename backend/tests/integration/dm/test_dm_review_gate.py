"""簽核中心入口閘（#250）整合測試：僅 `DM_REVIEWER` 可進入 `/api/dm/reviews/*`。

背景：US6 FR-001 規定簽核中心「僅顯示指定審核者＝當前登入者之項目」，屬**資料過濾**；
「誰能進入本頁」原本未規定，導致管理者 / 編輯者都看得到入口、點進去是空清單。
SA 於 #250 裁示（Q3=A）嚴格只認 `DM_REVIEWER`——**僅具 `DM_ADMIN` 者亦不得進入**。

本檔驗粗粒度入口閘（403 `DM_AUTH_004`）與 `reviewer-access` 入口可見性端點。
既有 `center_service` 的細粒度檢核（`DM_REVIEW_005` 非指定審核者）不在本檔範圍、亦未改動。
"""

import pytest

from app.core.auth import create_access_token
from app.core.utils import utcnow
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser

pytestmark = pytest.mark.integration

_PENDING = "/api/dm/reviews/pending"
_COMPLETED = "/api/dm/reviews/completed"
_ACCESS = "/api/dm/reviewer-access"


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


async def _grant(db, user_id, role):
    db.add(DmUserRole(user_id=user_id, role_code=role, created_user="seed", created_date=utcnow()))
    await db.flush()


async def test_reviewer_can_list_pending(db, client):
    """具 DM_REVIEWER → 待簽核清單 200（AC10）。"""
    await _seed_user(db, "rv1")
    await _grant(db, "rv1", DM_REVIEWER)
    r = await client.get(_PENDING, headers=_headers("rv1"))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.parametrize("role", [DM_ADMIN, DM_EDITOR, DM_VIEWER])
async def test_non_reviewer_forbidden_on_pending(db, client, role):
    """僅具管理者 / 編輯者 / 閱覽者（無審核者）→ 403 DM_AUTH_004（AC7 / AC8 / AC9）。

    改變前為 200 空陣列——入口看得到卻永遠空白，本閘讓語意與可見性一致。
    """
    user_id = f"nr_{role.lower()}"
    await _seed_user(db, user_id)
    await _grant(db, user_id, role)
    r = await client.get(_PENDING, headers=_headers(user_id))
    assert r.status_code == 403
    assert r.json()["error_code"] == "DM_AUTH_004"


async def test_non_reviewer_forbidden_on_completed(db, client):
    """已完成頁籤同受閘管制（AC9）。"""
    await _seed_user(db, "nr_c")
    await _grant(db, "nr_c", DM_ADMIN)
    r = await client.get(_COMPLETED, headers=_headers("nr_c"))
    assert r.status_code == 403 and r.json()["error_code"] == "DM_AUTH_004"


async def test_admin_with_reviewer_role_allowed(db, client):
    """兼具 DM_ADMIN + DM_REVIEWER → 放行（多角色取聯集，管理者加勾審核者即可簽核）。"""
    await _seed_user(db, "both1")
    await _grant(db, "both1", DM_ADMIN)
    await _grant(db, "both1", DM_REVIEWER)
    r = await client.get(_PENDING, headers=_headers("both1"))
    assert r.status_code == 200


async def test_no_dm_role_still_dm_auth_001(db, client):
    """完全無 DM 角色 → 維持既有 403 DM_AUTH_001（模組存取閘先擋，不被新閘蓋掉）。"""
    await _seed_user(db, "outsider")
    r = await client.get(_PENDING, headers=_headers("outsider"))
    assert r.status_code == 403 and r.json()["error_code"] == "DM_AUTH_001"


async def test_pending_requires_auth(client):
    """未帶 token → 401。"""
    r = await client.get(_PENDING)
    assert r.status_code == 401


async def test_obsolete_file_endpoint_not_behind_reviewer_gate(db, client):
    """廢止附件下載**不**掛簽核入口閘：純 DM_ADMIN 須進得了 handler（Security Review 迴歸）。

    該端點授權為「DM_ADMIN 或該送審之指定審核者」（US8 SA 裁示 Q1=C），且供 US10 已廢止
    文件查詢的稽核動線共用。若誤掛 reviewer 閘，管理者會被 DM_AUTH_004 擋在門外、
    service 內的 DM_ADMIN 分支成死碼。

    此處以「不是 DM_AUTH_004」斷言閘的行為——review_id 不存在故預期 404，
    關鍵在於錯誤不能是入口閘的 403。
    """
    await _seed_user(db, "obs_adm")
    await _grant(db, "obs_adm", DM_ADMIN)
    r = await client.get("/api/dm/reviews/999999/obsolete-file", headers=_headers("obs_adm"))
    assert r.status_code != 403, "純 DM_ADMIN 不應被簽核入口閘擋下"
    assert r.json().get("error_code") != "DM_AUTH_004"


async def test_reviewer_access_returns_boolean(db, client):
    """`reviewer-access` 回布林而非 403（比照 admin-access 之語意中性設計）：

    具 DM_REVIEWER → true；僅 DM_ADMIN → false。供側欄逐項閘決定「簽核中心」是否顯示。
    """
    await _seed_user(db, "acc_rv")
    await _grant(db, "acc_rv", DM_REVIEWER)
    await _seed_user(db, "acc_adm")
    await _grant(db, "acc_adm", DM_ADMIN)

    r_yes = await client.get(_ACCESS, headers=_headers("acc_rv"))
    assert r_yes.status_code == 200 and r_yes.json()["can_access"] is True

    r_no = await client.get(_ACCESS, headers=_headers("acc_adm"))
    assert r_no.status_code == 200 and r_no.json()["can_access"] is False
