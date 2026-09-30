"""US5 系統參數與清單維護整合測試：前綴過濾 / 值編輯 / 清單維護 / DETAIL_LOCK / 越權 / 即時生效。

多以 ParamAdminService + 真實 DB 直測業務規則與稽核；另抽樣一條 HTTP 驗 router 接線與認證。
前綴過濾（A-strict）以注入 module_admin_gate stub 驗證（ET/DM checker 正式版未就緒，見 SA Q1）。
"""

import json

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dm.roles.gate import dm_is_module_admin
from app.dp.audit.models import DpAuditLog
from app.dp.params.models import DpParamDetail, DpParamMaster
from app.dp.params.schemas import ParamDetailCreate, ParamDetailUpdate
from app.dp.params.service import ParamAdminService, ParamService
from app.dp.users.models import DpUser
from app.et.roles.gate import et_is_module_admin

# 本檔不套 conftest 的 backoffice_admin：已有專用的 `admin_gate` stub（可指定誰是 ET/DM 管理者），
# 且測試會以它覆蓋全域 checker——兩者並用會互相蓋掉。HTTP 測試改以 admin_gate 明確授予（#250）。
pytestmark = pytest.mark.integration

_OP = OperatorInfo(user_id="admin01")


@pytest.fixture
def admin_gate():
    """註冊可設定的 module_admin_gate stub；回一個 setter，測試指定誰是 ET/DM 管理者。"""

    def configure(*, et_admins: tuple[str, ...] = (), dm_admins: tuple[str, ...] = ()) -> None:
        async def et_checker(_db, uid):
            return uid in et_admins

        async def dm_checker(_db, uid):
            return uid in dm_admins

        module_admin_gate.register("ET", et_checker)
        module_admin_gate.register("DM", dm_checker)

    yield configure
    # 還原 main.py 註冊之真實 checker（非 unregister——ET / DM 皆已接線，移除會讓
    # 後續測試看到「未接線」而全數 fail-closed 403，使閘的狀態變成 test-order 相依）
    module_admin_gate.register("ET", et_is_module_admin)
    module_admin_gate.register("DM", dm_is_module_admin)


async def _make_master(
    db, param_id, *, param_type="VALUE", detail_lock=False, name="測試參數", details=(), edit_scope="ADMIN"
):
    """建立測試用主檔 + 明細。

    `edit_scope` 套用於所有明細。#459 之後種子資料已無任何 `READONLY` 項（9 項全改 `HIDDEN`），
    該層級的程式碼路徑只能靠自建資料驗證——**不可因為「沒有真實參數用它」就刪掉那些測試**，
    否則 `READONLY` 會變成沒有測試、壞掉也沒人發現。
    """
    now = utcnow()
    db.add(
        DpParamMaster(
            param_id=param_id,
            param_name=name,
            param_type=param_type,
            detail_lock=detail_lock,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()  # 先落地主檔，滿足 DP_PARAM_D → DP_PARAM_M 外鍵
    for key, value, sort_order, is_enabled in details:
        db.add(
            DpParamDetail(
                param_id=param_id,
                param_key=key,
                param_name=value or key,  # 測試明細名稱：有值用值、否則用碼（僅需非空）
                param_value=value,
                sort_order=sort_order,
                is_enabled=is_enabled,
                edit_scope=edit_scope,
                created_user="seed",
                created_date=now,
            )
        )
    await db.flush()


async def _count_audit(db, target_id, action_type=None):
    stmt = select(func.count()).select_from(DpAuditLog).where(DpAuditLog.target_id == target_id)
    if action_type:
        stmt = stmt.where(DpAuditLog.action_type == action_type)
    return (await db.execute(stmt)).scalar_one()


# ---- 前綴過濾（AC1）----


async def test_list_visible_prefix_filter_et_admin(db, admin_gate):
    admin_gate(et_admins=("etadmin",))  # etadmin 為 ET 管理者、非 DM
    await _make_master(db, "ET_UNIT", param_type="LIST", name="ET 單位", details=[("A", "甲", 1, True)])
    await _make_master(db, "DM_CAT", param_type="LIST", name="DM 分類", details=[("SOP", "程序", 1, True)])

    result = await ParamAdminService().list_visible(db, "etadmin")
    ids = {m.param_id for m in result}
    assert "ET_UNIT" in ids  # 自己模組可見
    assert "DM_CAT" not in ids  # 他模組不可見
    assert "PWD_POLICY" in ids  # 平台級共用（種子）。不用 JWT——#459 起它整組 HIDDEN、不再回傳
    et = next(m for m in result if m.param_id == "ET_UNIT")
    assert et.scope == "ET" and et.details[0].param_key == "A"


async def test_list_visible_non_admin_sees_platform_only(db, admin_gate):
    admin_gate()  # 皆非管理者（等同 fail-closed 過渡態）
    await _make_master(db, "ET_UNIT", param_type="LIST", details=[("A", "甲", 1, True)])
    result = await ParamAdminService().list_visible(db, "plainuser")
    ids = {m.param_id for m in result}
    assert "PWD_POLICY" in ids and "LOGIN" in ids  # 平台級可見
    assert "ET_UNIT" not in ids  # 模組級隱藏


# ---- VALUE 值編輯 + 驗證 + 即時生效（AC2/6/8）----


async def test_update_value_valid_audits_and_takes_effect(db, admin_gate):
    admin_gate()
    await ParamAdminService().update_detail(
        db, param_id="LOGIN", param_key="FAIL_LOCK_COUNT", data=ParamDetailUpdate(param_value="10"), operator=_OP
    )
    # 稽核 UPDATE 一筆
    assert await _count_audit(db, "LOGIN.FAIL_LOCK_COUNT", "UPDATE") == 1
    # SRVDP001 即時讀到新值（同交易、不快取）
    assert await ParamService().get_int_param(db, "LOGIN", "FAIL_LOCK_COUNT", 5) == 10


async def test_update_description_audits_before_after(db, admin_gate):
    """#112：說明（DESCRIPTION）異動寫入稽核前後值——維護頁開放編輯說明之依據。

    平台級 VALUE 明細之說明已由 migration abe854a7da34（#99）回填，故 before 非 None；
    此處以「改動前實際值」比對，避免測試耦合特定種子文字。
    """
    admin_gate()
    seeded = (
        await db.execute(
            select(DpParamDetail.description).where(
                DpParamDetail.param_id == "LOGIN", DpParamDetail.param_key == "FAIL_LOCK_COUNT"
            )
        )
    ).scalar_one()
    assert seeded is not None  # 前提：種子已回填說明

    await ParamAdminService().update_detail(
        db,
        param_id="LOGIN",
        param_key="FAIL_LOCK_COUNT",
        data=ParamDetailUpdate(param_value="10", description="連續失敗幾次後鎖定"),
        operator=_OP,
    )
    log = (
        await db.execute(
            select(DpAuditLog).where(
                DpAuditLog.target_id == "LOGIN.FAIL_LOCK_COUNT", DpAuditLog.action_type == "UPDATE"
            )
        )
    ).scalar_one()
    assert json.loads(log.before_value)["description"] == seeded
    assert json.loads(log.after_value)["description"] == "連續失敗幾次後鎖定"


async def test_update_description_cleared_to_null(db, admin_gate):
    """#112：說明送 null＝清空（前端留白時之語意），回寫 NULL。"""
    admin_gate()
    svc = ParamAdminService()
    await svc.update_detail(
        db, param_id="LOGIN", param_key="FAIL_LOCK_COUNT", data=ParamDetailUpdate(description="先填"), operator=_OP
    )
    result = await svc.update_detail(
        db, param_id="LOGIN", param_key="FAIL_LOCK_COUNT", data=ParamDetailUpdate(description=None), operator=_OP
    )
    assert result.description is None


async def test_update_value_out_of_range_rejected(db, admin_gate):
    admin_gate()
    # CHAR_TYPES 值域 1~4（param_rules）；5 超出上限
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="PWD_POLICY", param_key="CHAR_TYPES", data=ParamDetailUpdate(param_value="5"), operator=_OP
        )
    assert exc.value.status_code == 422 and exc.value.error_code == "DP_PARAM_001"


async def test_update_cross_field_invariant_rejected(db, admin_gate):
    admin_gate()
    # MIN_LEN 種子為 8；把 ADMIN_MIN_LEN 改為 6 (< MIN_LEN) → 跨欄位不一致
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="PWD_POLICY", param_key="ADMIN_MIN_LEN", data=ParamDetailUpdate(param_value="6"), operator=_OP
        )
    assert exc.value.error_code == "DP_PARAM_001"


# ---- LIST 清單維護（AC4）----


async def test_create_rename_disable_list_item(db, admin_gate):
    admin_gate(et_admins=("admin01",))  # 模組級清單維護：operator 為 ET 管理者
    await _make_master(db, "ET_UNIT", param_type="LIST", name="ET 單位")
    svc = ParamAdminService()
    await svc.create_detail(
        db, param_id="ET_UNIT", data=ParamDetailCreate(param_key="EXPORT", param_name="匯出"), operator=_OP
    )
    detail = await svc._repo.get_detail(db, "ET_UNIT", "EXPORT")
    assert detail is not None and detail.is_enabled is True and detail.param_name == "匯出"
    # 改名（改 PARAM_NAME 中文名稱）
    await svc.update_detail(
        db, param_id="ET_UNIT", param_key="EXPORT", data=ParamDetailUpdate(param_name="資料匯出"), operator=_OP
    )
    assert (await svc._repo.get_detail(db, "ET_UNIT", "EXPORT")).param_name == "資料匯出"
    # 停用
    await svc.update_detail(
        db, param_id="ET_UNIT", param_key="EXPORT", data=ParamDetailUpdate(is_enabled=False), operator=_OP
    )
    assert (await svc._repo.get_detail(db, "ET_UNIT", "EXPORT")).is_enabled is False
    # 稽核：1 CREATE + 2 UPDATE
    assert await _count_audit(db, "ET_UNIT.EXPORT", "CREATE") == 1
    assert await _count_audit(db, "ET_UNIT.EXPORT", "UPDATE") == 2


async def test_create_duplicate_key_rejected(db, admin_gate):
    admin_gate(et_admins=("admin01",))
    await _make_master(db, "ET_UNIT", param_type="LIST", details=[("A", "甲", 1, True)])
    svc = ParamAdminService()
    with pytest.raises(AppError) as exc:
        await svc.create_detail(
            db, param_id="ET_UNIT", data=ParamDetailCreate(param_key="A", param_name="重複"), operator=_OP
        )
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_PARAM_005"


async def test_action_type_excluded_from_maintenance(db, admin_gate):
    admin_gate()
    svc = ParamAdminService()
    # 系統 enum ACTION_TYPE 不出現在維護清單
    ids = {m.param_id for m in await svc.list_visible(db, "admin01")}
    assert "ACTION_TYPE" not in ids
    assert "PWD_POLICY" in ids  # 一般平台級參數照常可見
    # 直呼 API 維護 ACTION_TYPE → 404（視為不存在於維護面）
    with pytest.raises(AppError) as exc:
        await svc.create_detail(
            db, param_id="ACTION_TYPE", data=ParamDetailCreate(param_key="X", param_name="測試"), operator=_OP
        )
    assert exc.value.status_code == 404 and exc.value.error_code == "DP_PARAM_004"


async def test_create_on_value_type_rejected(db, admin_gate):
    admin_gate()
    svc = ParamAdminService()
    with pytest.raises(AppError) as exc:
        await svc.create_detail(
            db, param_id="JWT", data=ParamDetailCreate(param_key="FOO", param_name="測試"), operator=_OP
        )
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_PARAM_006"


# ---- DETAIL_LOCK（AC5）----


async def test_detail_lock_blocks_new_code(db, admin_gate):
    admin_gate()
    await _make_master(db, "LOCKED_LIST", param_type="LIST", detail_lock=True, details=[("SOP", "程序", 1, True)])
    with pytest.raises(AppError) as exc:
        await ParamAdminService().create_detail(
            db, param_id="LOCKED_LIST", data=ParamDetailCreate(param_key="NEW", param_name="新"), operator=_OP
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_PARAM_002"


async def test_detail_lock_allows_rename_and_disable(db, admin_gate):
    admin_gate()
    await _make_master(db, "LOCKED_LIST", param_type="LIST", detail_lock=True, details=[("SOP", "程序", 1, True)])
    svc = ParamAdminService()
    # 鎖定清單仍可改名 / 停用既有項（僅碼值鎖定）
    await svc.update_detail(
        db,
        param_id="LOCKED_LIST",
        param_key="SOP",
        data=ParamDetailUpdate(param_name="標準程序", is_enabled=False),
        operator=_OP,
    )
    d = await svc._repo.get_detail(db, "LOCKED_LIST", "SOP")
    assert d.param_name == "標準程序" and d.is_enabled is False


# ---- 越權（AC7）----


async def test_cross_module_update_forbidden(db, admin_gate):
    admin_gate(et_admins=("etadmin",))  # etadmin 非 DM 管理者
    await _make_master(db, "DM_CAT", param_type="LIST", details=[("SOP", "程序", 1, True)])
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db,
            param_id="DM_CAT",
            param_key="SOP",
            data=ParamDetailUpdate(param_value="x"),
            operator=OperatorInfo(user_id="etadmin"),
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_PARAM_003"


async def test_update_missing_param_404(db, admin_gate):
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="NOPE", param_key="X", data=ParamDetailUpdate(param_value="1"), operator=_OP
        )
    assert exc.value.status_code == 404 and exc.value.error_code == "DP_PARAM_004"


async def test_update_no_fields_rejected(db, admin_gate):
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="JWT", param_key="ACCESS_TTL_MIN", data=ParamDetailUpdate(), operator=_OP
        )
    assert exc.value.status_code == 422 and exc.value.error_code == "COMMON_001"


async def test_create_on_missing_param_404(db, admin_gate):
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().create_detail(
            db, param_id="NOPE", data=ParamDetailCreate(param_key="X", param_name="測試"), operator=_OP
        )
    assert exc.value.status_code == 404 and exc.value.error_code == "DP_PARAM_004"


# ---- 維護層級 EDIT_SCOPE（#171）----


async def test_readonly_detail_listed_but_update_rejected(db, admin_gate):
    """READONLY ＝列得出來、但改不動（伺服器端擋，前端不渲染入口只是 UX）。

    #459 之後種子資料已無 READONLY 項，故以自建資料驗證。**兩個斷言缺一不可**：
    只驗「改不動」的話，把 READONLY 誤實作成 HIDDEN 也會通過——那是不同的行為。
    """
    admin_gate()
    await _make_master(db, "ZT_RO", name="唯讀測試參數", details=[("VALUE", "abc", 1, True)], edit_scope="READONLY")

    ids = {m.param_id for m in await ParamAdminService().list_visible(db, "admin01")}
    assert "ZT_RO" in ids  # 列得出來——與 HIDDEN 的分野

    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="ZT_RO", param_key="VALUE", data=ParamDetailUpdate(param_value="10"), operator=_OP
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_PARAM_007"


@pytest.mark.parametrize(
    "payload",
    [
        ParamDetailUpdate(param_value="10"),
        ParamDetailUpdate(param_name="改名"),
        ParamDetailUpdate(description="改說明"),
        ParamDetailUpdate(is_enabled=False),
    ],
    ids=["param_value", "param_name", "description", "is_enabled"],
)
async def test_readonly_detail_rejects_every_field(db, admin_gate, payload):
    """D2：READONLY ＝整列唯讀，四個可編輯欄位逐一皆須擋下。

    `is_enabled` 尤其不可漏——`ParamService.get_param_value()` 對停用明細回 None，呼叫端
    隨即 fallback 到程式碼裡的預設值。能停用就等於繞過 READONLY 改變了系統實際採用的值，
    而畫面上那一列的「值」看起來沒被動過（正是本 issue 要防的 #170 形狀）。
    """
    admin_gate()
    await _make_master(db, "ZT_RO", name="唯讀測試參數", details=[("VALUE", "abc", 1, True)], edit_scope="READONLY")
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(db, param_id="ZT_RO", param_key="VALUE", data=payload, operator=_OP)
    assert exc.value.error_code == "DP_PARAM_007"


async def test_edit_scope_check_precedes_value_validation(db, admin_gate):
    """層級檢核在值域驗證**之前**：改不動的列，值合不合法無關緊要。

    這條刻意送一個**超出值域**的值（`JWT.ACCESS_TTL_MIN` 值域 1–15，此處送 9999）。
    其餘擋寫測試送的是合法值，兩種檢核順序都會得到 007——**分辨不出順序**；唯有送非法值
    才能證明層級先跑（否則會先被 `DP_PARAM_001` 擋下）。
    順序若反過來，等於對一個改不動的參數洩露它的值域規則。

    ⚠️ 這裡用 `JWT`（#459 起為 HIDDEN）而非自建的 READONLY 參數，因為**自建參數不在
    `param_rules` registry 裡、根本不會觸發值域驗證**，送 9999 也照樣通過——那樣這條就
    失去鑑別力。擋寫判的是 `is_editable_scope()`，READONLY / HIDDEN 走同一條路徑，
    故以 HIDDEN 驗證順序同樣成立。
    """
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="JWT", param_key="ACCESS_TTL_MIN", data=ParamDetailUpdate(param_value="9999"), operator=_OP
        )
    assert exc.value.error_code == "DP_PARAM_007"  # 不是 DP_PARAM_001


async def test_hidden_detail_update_rejected(db, admin_gate):
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="MAIL", param_key="RATE_PER_MIN", data=ParamDetailUpdate(param_value="120"), operator=_OP
        )
    # 403 而非 404：回 404 等於宣稱「此參數不存在」，與事實不符
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_PARAM_007"


async def test_hidden_details_excluded_from_list(db, admin_gate):
    """HIDDEN 明細不出現於維護頁；整組皆 HIDDEN 之主檔連主檔一併不回傳。

    #459 起 `JWT` 兩列皆 HIDDEN，故與 `MAIL` 一樣整個主檔消失；`PWD_POLICY` / `LOGIN`
    仍可見，作為「不是全部都被濾掉」的對照——沒有這個對照，`list_visible` 回空清單
    也會讓上面兩條 `not in` 通過。
    """
    admin_gate()
    result = await ParamAdminService().list_visible(db, "admin01")
    ids = {m.param_id for m in result}
    assert "MAIL" not in ids  # 三個明細皆 HIDDEN → 不留下 0 項的空群組
    assert "JWT" not in ids  # 同上（#459）
    assert "PWD_POLICY" in ids and "LOGIN" in ids  # 對照組
    keys = {(m.param_id, d.param_key) for m in result for d in m.details}
    assert ("MAIL", "RATE_PER_MIN") not in keys
    assert ("JWT", "ACCESS_TTL_MIN") not in keys


async def test_master_without_details_is_still_listed(db, admin_gate):
    """「整組皆 HIDDEN 不回傳」不得誤殺「本來就沒有明細」的主檔。

    兩者在 `list_visible` 是同一個分支的兩半。若寫成「過濾後為空就跳過」，新建的 LIST
    主檔會連第一個項目都加不進去——維護頁的新增入口就在主檔那一列上。
    """
    admin_gate()
    await _make_master(db, "EMPTY_LIST", param_type="LIST", name="尚無項目的清單", details=())
    ids = {m.param_id for m in await ParamAdminService().list_visible(db, "admin01")}
    assert "EMPTY_LIST" in ids
    assert "MAIL" not in ids  # 對照：有明細但全為 HIDDEN 者才該被跳過


async def test_hiding_is_per_detail_not_per_master(db, admin_gate):
    """層級掛在**明細**而非主檔：同一個 `LOGIN` 底下，5 列可見、1 列被藏。

    這是本欄位放在 `DP_PARAM_D` 而非 `DP_PARAM_M` 的原因，也是 #459 之後唯一還驗得到
    「同主檔混層級」的種子資料（`JWT` 兩列皆 HIDDEN，整個主檔已消失）。
    若改掛主檔層，`LOGIN` 只能整組可見或整組消失，這條就會紅。
    """
    admin_gate()
    result = await ParamAdminService().list_visible(db, "admin01")
    login = next(m for m in result if m.param_id == "LOGIN")
    keys = {d.param_key for d in login.details}

    assert "VERIFY_SEND_COOLDOWN_SEC" not in keys  # 這一列被藏
    assert "FAIL_LOCK_COUNT" in keys  # 同主檔的其他列照常可見
    assert len(keys) == 5  # DB 有 6 列，回傳 5 列
    assert all(d.edit_scope == "ADMIN" for d in login.details)  # 回傳的都是可編輯的


async def test_edit_scope_does_not_affect_runtime_reads(db, admin_gate):
    """EDIT_SCOPE 只管維護面，不得影響執行期讀取——故濾在 service 層、不在 repository。

    若把 HIDDEN 濾進 `ParamRepository`，寄信 worker 讀 `MAIL.RATE_PER_MIN` 會得 None 而
    fallback 到程式碼預設值：行為變了、卻沒有任何錯誤訊息。
    """
    admin_gate()
    svc = ParamService()
    assert await svc.get_int_param(db, "MAIL", "RATE_PER_MIN", -1) == 60  # HIDDEN 照樣讀得到
    # #459 把 JWT 兩列改為 HIDDEN。維護頁看不到它，但登入流程仍靠它決定 token 效期——
    # 若這條紅了，代表「從畫面上拿掉」不小心變成了「系統讀不到」。
    assert await svc.get_param_value(db, "JWT", "ACCESS_TTL_MIN") == "15"


async def test_module_filter_precedes_edit_scope(db, admin_gate):
    """兩層獨立且模組過濾先行：ET 管理者對 DM 的不可編輯參數應得越權碼，而非 IT 設定碼。

    反過來會讓「你不是這個模組的管理者」與「這個參數誰都不能改」在前端無法分辨。
    （`DM_FILE_TYPES` 於 #459 起為 HIDDEN；不論 READONLY 或 HIDDEN，模組過濾都該先擋。）
    """
    admin_gate(et_admins=("etadmin",))
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db,
            param_id="DM_FILE_TYPES",
            param_key="VALUE",
            data=ParamDetailUpdate(param_value="pdf"),
            operator=OperatorInfo(user_id="etadmin"),
        )
    assert exc.value.error_code == "DP_PARAM_003"


async def test_dm_admin_sees_readonly_param_but_cannot_edit(db, admin_gate):
    """兩層疊加的另一半：模組過濾放行、層級擋下——看得到、改不動。

    #459 之前這條用種子的 `DM_FILE_TYPES`（當時為 READONLY），現已改 HIDDEN，
    故改以自建的 DM 模組級 READONLY 參數驗證——**這一層疊加本身沒有被取消**，
    只是目前沒有真實參數落在這個組合上。
    """
    admin_gate(dm_admins=("dmadmin",))
    svc = ParamAdminService()
    await _make_master(db, "DM_ZT_RO", name="DM 唯讀測試參數", details=[("VALUE", "abc", 1, True)], edit_scope="READONLY")

    result = await svc.list_visible(db, "dmadmin")
    dm = next(m for m in result if m.param_id == "DM_ZT_RO")
    assert dm.details[0].edit_scope == "READONLY"  # 模組過濾放行 → 看得到

    with pytest.raises(AppError) as exc:
        await svc.update_detail(
            db,
            param_id="DM_ZT_RO",
            param_key="VALUE",
            data=ParamDetailUpdate(param_value="pdf"),
            operator=OperatorInfo(user_id="dmadmin"),
        )
    assert exc.value.error_code == "DP_PARAM_007"  # 層級擋下 → 改不動


async def test_seeded_module_params_are_hidden_from_their_admins(db, admin_gate):
    """模組管理者只看得到該模組唯一可調的那一項，其餘種子參數已隱藏（#459）。

    這條補的是 `sti-alembic-rules` 要求的「migration 由對應 service / API 測試間接覆蓋」。
    沒有它，回填若漏掉這 6 列**不會有任何測試變紅**——漏掉的列會停在 `READONLY`
    （可見但不可編輯），而其餘測試驗的不是自建資料就是平台級參數，都碰不到它們。
    （2026-09-30 security review 以變異實測：拿掉這 6 列後 593 條測試全綠。）

    每個模組都留一個「該可見」的對照組，否則 `list_visible` 回空清單也會讓 `not in` 全數通過。
    """
    admin_gate(et_admins=("etadmin",), dm_admins=("dmadmin",))
    svc = ParamAdminService()

    dm_ids = {m.param_id for m in await svc.list_visible(db, "dmadmin")}
    assert "DM_REMIND_THRESHOLD" in dm_ids  # 對照組：DM 唯一仍可維護的參數
    assert "DM_FILE_MAX_MB" not in dm_ids
    assert "DM_FILE_TYPES" not in dm_ids

    et_ids = {m.param_id for m in await svc.list_visible(db, "etadmin")}
    assert "ET_URGENT_REMIND_DAYS" in et_ids  # 對照組：ET 唯一仍可維護的參數
    for param_id in (
        "ET_VIDEO_ALLOWED_FORMATS",
        "ET_VIDEO_MAX_SIZE_MB",
        "ET_VIDEO_PLAYBACK_MAX_RATE",
        "ET_INVITATION_CODE_LENGTH",
    ):
        assert param_id not in et_ids


async def test_detail_lock_and_edit_scope_report_distinct_codes(db, admin_gate):
    """AC10：兩機制正交，各自回自己的碼——DETAIL_LOCK 管碼值、EDIT_SCOPE 管誰能改這一列。"""
    admin_gate()
    await _make_master(db, "LOCKED_RO", param_type="LIST", detail_lock=True, details=[("SOP", "程序", 1, True)])
    svc = ParamAdminService()
    detail = await svc._repo.get_detail(db, "LOCKED_RO", "SOP")
    detail.edit_scope = "READONLY"
    await db.flush()

    with pytest.raises(AppError) as lock_exc:  # 新增碼值 → DETAIL_LOCK
        await svc.create_detail(
            db, param_id="LOCKED_RO", data=ParamDetailCreate(param_key="NEW", param_name="新"), operator=_OP
        )
    assert lock_exc.value.error_code == "DP_PARAM_002"

    with pytest.raises(AppError) as scope_exc:  # 改既有列 → EDIT_SCOPE
        await svc.update_detail(
            db, param_id="LOCKED_RO", param_key="SOP", data=ParamDetailUpdate(param_name="改名"), operator=_OP
        )
    assert scope_exc.value.error_code == "DP_PARAM_007"


# ---- HTTP 接線抽樣（認證 + 列表回應）----


async def test_list_params_http(db, client, admin_gate):
    # #250：後台 router 掛 require_any_module_admin，須明確授予管理者身分才進得來
    # （原為空設定 admin_gate()——當時 router 只驗認證）。斷言仍聚焦「平台級參數可見」。
    admin_gate(et_admins=("admin01",))
    now = utcnow()
    db.add(
        DpUser(
            user_id="admin01",
            email="a@edms.local",
            pwd_hash="x",
            user_name="管理者",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=now,
            created_user="seed",
            created_date=now,
        )
    )
    await db.flush()
    token = create_access_token(sub="admin01", ttl_minutes=15)

    resp = await client.get("/api/dp/params", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    ids = {m["param_id"] for m in resp.json()}
    assert "PWD_POLICY" in ids  # 平台級可見
