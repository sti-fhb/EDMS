"""US5 系統參數與清單維護整合測試：前綴過濾 / 值編輯 / 清單維護 / DETAIL_LOCK / 越權 / 即時生效。

多以 ParamAdminService + 真實 DB 直測業務規則與稽核；另抽樣一條 HTTP 驗 router 接線與認證。
前綴過濾（A-strict）以注入 module_admin_gate stub 驗證（ET/DM checker 正式版未就緒，見 SA Q1）。
"""

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.audit.models import DpAuditLog
from app.dp.params.models import DpParamDetail, DpParamMaster
from app.dp.params.schemas import ParamDetailCreate, ParamDetailUpdate
from app.dp.params.service import ParamAdminService, ParamService
from app.dp.users.models import DpUser

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
    module_admin_gate.unregister("ET")
    module_admin_gate.unregister("DM")


async def _make_master(db, param_id, *, param_type="VALUE", detail_lock=False, name="測試參數", details=()):
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
                param_value=value,
                sort_order=sort_order,
                is_enabled=is_enabled,
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
    assert "JWT" in ids  # 平台級共用（種子）
    et = next(m for m in result if m.param_id == "ET_UNIT")
    assert et.scope == "ET" and et.details[0].param_key == "A"


async def test_list_visible_non_admin_sees_platform_only(db, admin_gate):
    admin_gate()  # 皆非管理者（等同 fail-closed 過渡態）
    await _make_master(db, "ET_UNIT", param_type="LIST", details=[("A", "甲", 1, True)])
    result = await ParamAdminService().list_visible(db, "plainuser")
    ids = {m.param_id for m in result}
    assert "JWT" in ids and "PWD_POLICY" in ids  # 平台級可見
    assert "ET_UNIT" not in ids  # 模組級隱藏


# ---- VALUE 值編輯 + 驗證 + 即時生效（AC2/6/8）----


async def test_update_value_valid_audits_and_takes_effect(db, admin_gate):
    admin_gate()
    await ParamAdminService().update_detail(
        db, param_id="JWT", param_key="ACCESS_TTL_MIN", data=ParamDetailUpdate(param_value="10"), operator=_OP
    )
    # 稽核 UPDATE 一筆
    assert await _count_audit(db, "JWT.ACCESS_TTL_MIN", "UPDATE") == 1
    # SRVDP001 即時讀到新值（同交易、不快取）
    assert await ParamService().get_int_param(db, "JWT", "ACCESS_TTL_MIN", 15) == 10


async def test_update_value_out_of_range_rejected(db, admin_gate):
    admin_gate()
    with pytest.raises(AppError) as exc:
        await ParamAdminService().update_detail(
            db, param_id="JWT", param_key="ACCESS_TTL_MIN", data=ParamDetailUpdate(param_value="16"), operator=_OP
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
    admin_gate()
    # ACTION_TYPE 為平台級 LIST（種子），新增一項
    svc = ParamAdminService()
    await svc.create_detail(
        db, param_id="ACTION_TYPE", data=ParamDetailCreate(param_key="EXPORT", param_value="匯出"), operator=_OP
    )
    detail = await svc._repo.get_detail(db, "ACTION_TYPE", "EXPORT")
    assert detail is not None and detail.is_enabled is True
    # 改名
    await svc.update_detail(
        db, param_id="ACTION_TYPE", param_key="EXPORT", data=ParamDetailUpdate(param_value="資料匯出"), operator=_OP
    )
    assert (await svc._repo.get_detail(db, "ACTION_TYPE", "EXPORT")).param_value == "資料匯出"
    # 停用
    await svc.update_detail(
        db, param_id="ACTION_TYPE", param_key="EXPORT", data=ParamDetailUpdate(is_enabled=False), operator=_OP
    )
    assert (await svc._repo.get_detail(db, "ACTION_TYPE", "EXPORT")).is_enabled is False
    # 稽核：1 CREATE + 2 UPDATE
    assert await _count_audit(db, "ACTION_TYPE.EXPORT", "CREATE") == 1
    assert await _count_audit(db, "ACTION_TYPE.EXPORT", "UPDATE") == 2


async def test_create_duplicate_key_rejected(db, admin_gate):
    admin_gate()
    svc = ParamAdminService()
    with pytest.raises(AppError) as exc:
        await svc.create_detail(
            db, param_id="ACTION_TYPE", data=ParamDetailCreate(param_key="LOGIN", param_value="重複"), operator=_OP
        )
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_PARAM_005"


async def test_create_on_value_type_rejected(db, admin_gate):
    admin_gate()
    svc = ParamAdminService()
    with pytest.raises(AppError) as exc:
        await svc.create_detail(
            db, param_id="JWT", data=ParamDetailCreate(param_key="FOO", param_value="x"), operator=_OP
        )
    assert exc.value.status_code == 400 and exc.value.error_code == "DP_PARAM_006"


# ---- DETAIL_LOCK（AC5）----


async def test_detail_lock_blocks_new_code(db, admin_gate):
    admin_gate()
    await _make_master(db, "LOCKED_LIST", param_type="LIST", detail_lock=True, details=[("SOP", "程序", 1, True)])
    with pytest.raises(AppError) as exc:
        await ParamAdminService().create_detail(
            db, param_id="LOCKED_LIST", data=ParamDetailCreate(param_key="NEW", param_value="新"), operator=_OP
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
        data=ParamDetailUpdate(param_value="標準程序", is_enabled=False),
        operator=_OP,
    )
    d = await svc._repo.get_detail(db, "LOCKED_LIST", "SOP")
    assert d.param_value == "標準程序" and d.is_enabled is False


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


# ---- HTTP 接線抽樣（認證 + 列表回應）----


async def test_list_params_http(db, client, admin_gate):
    admin_gate()
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
    assert "JWT" in ids  # 平台級可見
