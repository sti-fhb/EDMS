"""US9 通知範本維護整合測試：MODULE 過濾（A-strict）/ 越權 / 系統信保護 / VERSION 樂觀鎖 / 稽核。

多以 TemplateAdminService + 真實 DB 直測業務規則；另抽樣一條 HTTP 驗 router 接線與認證。
MODULE 過濾以注入 module_admin_gate stub 驗證（ET/DM checker 正式版未就緒，同 US5）。
"""

import pytest
from sqlalchemy import func, select

from app.core.auth import create_access_token
from app.core.exceptions import AppError
from app.core.module_admin import module_admin_gate
from app.core.operator import OperatorInfo
from app.core.password_policy import hash_password
from app.core.utils import utcnow
from app.dm.roles.gate import dm_is_module_admin
from app.dp.audit.models import DpAuditLog
from app.dp.notify.admin_service import TemplateAdminService
from app.dp.notify.models import DpNotifyTemplate
from app.dp.notify.schemas import TemplateUpdate
from app.dp.users.models import DpUser
from app.et.roles.gate import et_is_module_admin

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


async def _make_template(
    db, *, module, code, is_system=False, is_enabled=True, channel="EMAIL", version=1, subject="主旨", body="內文"
):
    db.add(
        DpNotifyTemplate(
            module=module,
            template_code=code,
            template_name=f"{code} 名稱",
            subject=subject,
            body=body,
            variables="user_name",
            channel=channel,
            is_enabled=is_enabled,
            is_system=is_system,
            version=version,
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


def _upd(**kw):
    base = {"subject": "新主旨", "body": "新內文", "channel": "EMAIL", "is_enabled": True, "version": 1}
    base.update(kw)
    return TemplateUpdate(**base)


async def _count_audit(db, target_id):
    stmt = select(func.count()).select_from(DpAuditLog).where(DpAuditLog.target_id == target_id)
    return (await db.execute(stmt)).scalar_one()


# ---- MODULE 過濾（AC1 / AC7）----


async def test_list_et_admin_sees_et_and_dp_not_dm(db, admin_gate):
    admin_gate(et_admins=("etadmin",))
    await _make_template(db, module="ET", code="ET_ONLY")
    await _make_template(db, module="DM", code="DM_ONLY")

    result = await TemplateAdminService().list_visible(db, "etadmin")
    modules_codes = {(t.module, t.template_code) for t in result}
    assert ("ET", "ET_ONLY") in modules_codes  # 自己模組可見
    assert ("DM", "DM_ONLY") not in modules_codes  # 他模組不可見
    assert any(m == "DP" for m, _ in modules_codes)  # DP 系統信共用恆見（種子）


async def test_list_non_admin_sees_dp_only(db, admin_gate):
    admin_gate()  # 皆非管理者（fail-closed 過渡態）
    await _make_template(db, module="ET", code="ET_X")
    await _make_template(db, module="DM", code="DM_X")

    result = await TemplateAdminService().list_visible(db, "nobody")
    assert all(t.module == "DP" for t in result)  # 只見 DP 系統信
    assert result, "應至少見到種子 DP 系統信"


# ---- 編輯成功 + 版本 +1 + 稽核（AC2 / FR-06）----


async def test_update_success_bumps_version_and_audits(db, admin_gate):
    admin_gate(et_admins=("etadmin",))
    await _make_template(db, module="ET", code="ET_UPD", version=1)
    op = OperatorInfo(user_id="etadmin")

    resp = await TemplateAdminService().update_template(
        db, module="ET", template_code="ET_UPD", data=_upd(subject="改後主旨", version=1), operator=op
    )
    assert resp.version == 2 and resp.subject == "改後主旨"
    row = (
        await db.execute(
            select(DpNotifyTemplate).where(DpNotifyTemplate.module == "ET", DpNotifyTemplate.template_code == "ET_UPD")
        )
    ).scalar_one()
    assert row.version == 2 and row.subject == "改後主旨"
    assert await _count_audit(db, "ET.ET_UPD") == 1


# ---- 系統信保護（AC4 / FR-03）----


async def test_system_template_block_disable(db, admin_gate):
    admin_gate()
    await _make_template(db, module="DP", code="SYS_MAIL", is_system=True, version=1)
    with pytest.raises(AppError) as exc:
        await TemplateAdminService().update_template(
            db, module="DP", template_code="SYS_MAIL", data=_upd(is_enabled=False, version=1), operator=_OP
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_MAIL_003"


async def test_system_template_block_channel_msg(db, admin_gate):
    """系統信不可把 channel 改為 MSG（移除 Email 通道＝實質停用）→ DP_MAIL_003（Security Review）。"""
    admin_gate()
    await _make_template(db, module="DP", code="SYS_CH", is_system=True, version=1)
    with pytest.raises(AppError) as exc:
        await TemplateAdminService().update_template(
            db, module="DP", template_code="SYS_CH", data=_upd(channel="MSG", is_enabled=True, version=1), operator=_OP
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_MAIL_003"


async def test_system_template_subject_editable(db, admin_gate):
    """系統信主旨 / 內文仍可編（僅擋停用）。"""
    admin_gate()
    await _make_template(db, module="DP", code="SYS_EDIT", is_system=True, version=1)
    resp = await TemplateAdminService().update_template(
        db,
        module="DP",
        template_code="SYS_EDIT",
        data=_upd(subject="系統信新主旨", is_enabled=True, version=1),
        operator=_OP,
    )
    assert resp.subject == "系統信新主旨" and resp.version == 2


# ---- 樂觀鎖（AC5 / FR-05）----


async def test_optimistic_lock_conflict(db, admin_gate):
    admin_gate(et_admins=("etadmin",))
    await _make_template(db, module="ET", code="ET_LOCK", version=3)  # DB 版本 3
    op = OperatorInfo(user_id="etadmin")
    with pytest.raises(AppError) as exc:  # 以落後版本 2 儲存
        await TemplateAdminService().update_template(
            db, module="ET", template_code="ET_LOCK", data=_upd(version=2), operator=op
        )
    assert exc.value.status_code == 409 and exc.value.error_code == "DP_MAIL_004"


# ---- 越權（AC7 / FR-02）----


async def test_update_forbidden_other_module(db, admin_gate):
    admin_gate(et_admins=("etadmin",))  # 僅 ET 管理者
    await _make_template(db, module="DM", code="DM_FORBID", version=1)
    op = OperatorInfo(user_id="etadmin")
    with pytest.raises(AppError) as exc:
        await TemplateAdminService().update_template(
            db, module="DM", template_code="DM_FORBID", data=_upd(version=1), operator=op
        )
    assert exc.value.status_code == 403 and exc.value.error_code == "DP_MAIL_005"


async def test_update_not_found(db, admin_gate):
    admin_gate(et_admins=("etadmin",))
    with pytest.raises(AppError) as exc:
        await TemplateAdminService().update_template(
            db, module="ET", template_code="NOPE", data=_upd(version=1), operator=OperatorInfo(user_id="etadmin")
        )
    assert exc.value.status_code == 404 and exc.value.error_code == "DP_MAIL_001"


# ---- 管道含站內可存（AC8）----


async def test_update_channel_both_allowed(db, admin_gate):
    admin_gate(et_admins=("etadmin",))
    await _make_template(db, module="ET", code="ET_CH", version=1)
    resp = await TemplateAdminService().update_template(
        db,
        module="ET",
        template_code="ET_CH",
        data=_upd(channel="BOTH", version=1),
        operator=OperatorInfo(user_id="etadmin"),
    )
    assert resp.channel == "BOTH"


# ---- HTTP 端點抽樣（router→schema→service 串接）----


async def _make_user(db, user_id):
    db.add(
        DpUser(
            user_id=user_id,
            email=f"{user_id}@edms.local",
            pwd_hash=hash_password("Abcd1234"),
            user_name="範本管理者",
            status="ACTIVE",
            login_fail_count=0,
            pwd_changed_date=utcnow(),
            must_change_pwd=False,
            created_user="seed",
            created_date=utcnow(),
        )
    )
    await db.flush()


async def test_list_and_update_endpoint(client, db, admin_gate):
    """端點：GET 清單 + PUT 編輯（ET 管理者改 ET 範本）→ 200 + 實際更新。"""
    admin_gate(et_admins=("tadmin",))
    await _make_user(db, "tadmin")
    await _make_template(db, module="ET", code="ET_EP", version=1)
    headers = {"Authorization": f"Bearer {create_access_token(sub='tadmin', ttl_minutes=15)}"}

    r_list = await client.get("/api/dp/notify/templates", headers=headers)
    assert r_list.status_code == 200
    assert any(t["template_code"] == "ET_EP" for t in r_list.json())

    r_put = await client.put(
        "/api/dp/notify/templates/ET/ET_EP",
        json={"subject": "端點改主旨", "body": "端點內文", "channel": "EMAIL", "is_enabled": True, "version": 1},
        headers=headers,
    )
    assert r_put.status_code == 200 and r_put.json()["version"] == 2
    row = (
        await db.execute(
            select(DpNotifyTemplate).where(DpNotifyTemplate.module == "ET", DpNotifyTemplate.template_code == "ET_EP")
        )
    ).scalar_one()
    assert row.subject == "端點改主旨"


async def test_no_create_endpoint(client, db, admin_gate):
    """無新增範本端點（AC6）：POST 集合 → 405。"""
    admin_gate(et_admins=("tadmin2",))
    await _make_user(db, "tadmin2")
    headers = {"Authorization": f"Bearer {create_access_token(sub='tadmin2', ttl_minutes=15)}"}
    r = await client.post("/api/dp/notify/templates", json={}, headers=headers)
    assert r.status_code == 405


async def test_no_delete_endpoint(client, db, admin_gate):
    """無刪除範本端點（AC6）：DELETE 單筆 → 405。"""
    admin_gate(et_admins=("tadmin3",))
    await _make_user(db, "tadmin3")
    headers = {"Authorization": f"Bearer {create_access_token(sub='tadmin3', ttl_minutes=15)}"}
    r = await client.delete("/api/dp/notify/templates/ET/ET_EP", headers=headers)
    assert r.status_code == 405
