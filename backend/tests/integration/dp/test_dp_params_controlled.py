"""US5 模組受控清單維護整合測試（#182：DP07 接上受控主檔轉接層）。

受控清單（模組自持表：`DM_CATEGORY` / `DM_FUNC` / `DM_TAG` / `ET_TAG`）與 `DP_PARAM`
並存於同一畫面但走不同資料源。本檔驗 DP 端之**接線與模組過濾**——各模組自身的業務規則
（碼鎖定、soft-retire、「全體」保護）已由各模組之 adapter 測試覆蓋，此處不重測。

比照 `test_dp_params_maintain.py`：多以 service + 真實 DB 直測，另抽樣一條 HTTP 驗 router 接線。
"""

import pytest

from app.core.auth import create_access_token
from app.core.module_admin import module_admin_gate
from app.core.module_assign import module_assign_registry
from app.core.utils import utcnow
from app.dm.bootstrap import register_dm_module
from app.dm.roles.gate import dm_is_module_admin
from app.dp.params.service import ControlledAdminService
from app.dp.users.models import DpUser
from app.et.bootstrap import register_et_module
from app.et.roles.gate import et_is_module_admin

pytestmark = pytest.mark.integration


@pytest.fixture
def modules_registered():
    """確保 ET / DM 之 provider 已註冊——service 層測試不經 app lifespan，不會自動註冊。

    teardown 重新 `register`（**非 unregister**）：`main.py` 啟動即註冊兩模組，「已註冊」
    才是整個執行期的基線；清成未註冊等於留下正式環境從不存在的狀態給後續測試。
    """
    register_et_module()
    register_dm_module()
    yield
    register_et_module()
    register_dm_module()


@pytest.fixture
def admin_gate(modules_registered):
    """註冊可設定的 module_admin_gate stub；回一個 setter，測試指定誰是 ET / DM 管理者。

    teardown 還原 `main.py` 註冊之真實 checker（**非 unregister**）——ET / DM 皆已接線，
    移除會讓後續測試看到「未接線」而全數 fail-closed 403，使閘的狀態變成 test-order 相依。
    與 `test_dp_params_maintain.py` 同一 pattern。
    """

    # 依賴 modules_registered：`register_*_module()` 會一併註冊真實 admin checker，
    # 必須先跑完才輪到本 stub 覆蓋，否則 stub 會被真實 checker 蓋掉。
    def configure(*, et_admins: tuple[str, ...] = (), dm_admins: tuple[str, ...] = ()) -> None:
        async def et_checker(_db, uid):
            return uid in et_admins

        async def dm_checker(_db, uid):
            return uid in dm_admins

        module_admin_gate.register("ET", et_checker)
        module_admin_gate.register("DM", dm_checker)

    yield configure
    module_admin_gate.register("ET", et_is_module_admin)
    module_admin_gate.register("DM", dm_is_module_admin)


def _sections_by_kind(sections, module):
    return {s.kind for s in sections if s.module == module}


async def test_dm管理者可見三類受控清單且標籤依組分區(db, admin_gate):
    """DM 三類受控主檔皆出現；標籤依 `DM_TAG_GROUP` 拆成多個分區（組名來自模組，非 DP 硬編碼）。"""
    admin_gate(dm_admins=("dmadmin",))

    sections = await ControlledAdminService().list_visible(db, "dmadmin")

    assert _sections_by_kind(sections, "DM") == {"CATEGORY", "FUNC", "TAG"}
    tag_sections = [s for s in sections if s.module == "DM" and s.kind == "TAG"]
    assert len(tag_sections) > 1, "標籤須依標籤組拆分區，否則畫面無法分「可見對象 / 檢索標籤」"
    assert all(s.group_code and s.group_name for s in tag_sections), "分區須帶組代碼與組名"
    # 非 TAG 類無子分組
    assert all(s.group_code is None for s in sections if s.module == "DM" and s.kind != "TAG")


async def test_模組過濾_et管理者看不到dm受控清單(db, admin_gate):
    """A-strict：模組級項僅該模組管理者可見（伺服器端 enforce，非僅前端過濾）。"""
    admin_gate(et_admins=("etadmin",))

    sections = await ControlledAdminService().list_visible(db, "etadmin")

    assert _sections_by_kind(sections, "ET") == {"TAG"}, "ET 僅受訓單位標籤一類"
    assert not [s for s in sections if s.module == "DM"], "他模組受控清單不可見"


async def test_兩模組管理者同時可見兩邊(db, admin_gate):
    admin_gate(et_admins=("both",), dm_admins=("both",))

    sections = await ControlledAdminService().list_visible(db, "both")

    assert _sections_by_kind(sections, "ET") == {"TAG"}
    assert _sections_by_kind(sections, "DM") == {"CATEGORY", "FUNC", "TAG"}


async def test_無管理者身分者看不到任何受控清單(db, admin_gate):
    """checker 未認可即 fail-closed——不得因 provider 已註冊就列出。"""
    admin_gate()  # 誰都不是管理者

    assert await ControlledAdminService().list_visible(db, "nobody") == []


async def test_未註冊provider之模組不出現(db, admin_gate):
    """即使某模組有管理者 checker，未註冊 provider 仍不得出現（不 500、靜默略過）。"""
    admin_gate(dm_admins=("dmadmin",))
    module_assign_registry.unregister("ZT_ABSENT")

    sections = await ControlledAdminService().list_visible(db, "dmadmin")

    assert not [s for s in sections if s.module == "ZT_ABSENT"]


async def test_http_列受控清單需管理者身分(db, client, admin_gate):
    """抽樣一條 HTTP 驗 router 接線＋授權閘（業務規則由 service 層測試覆蓋）。"""
    admin_gate(dm_admins=("ZTCTRL01",))
    db.add(
        DpUser(
            user_id="ZTCTRL01",
            email="ztctrl01@edms.local",
            pwd_hash="x",
            user_name="受控清單測試",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=utcnow(),
            must_change_pwd=False,
            created_user="seed",
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()

    token = create_access_token(sub="ZTCTRL01", ttl_minutes=15)
    resp = await client.get("/api/dp/params/controlled", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert {s["kind"] for s in body if s["module"] == "DM"} == {"CATEGORY", "FUNC", "TAG"}
    assert all("items" in s and "requires_code" in s for s in body)
