"""DM 受控主檔維護轉接層整合測試（§3.1，真實 DB）。

驗證：三類受控項（CATEGORY / FUNC / TAG）之列出 / 新增 / 改名 / 啟停、不刪除、碼鎖定、
停用保留既有引用、AUDIENCE 標籤停用 soft-retire 回受影響數、list_audiences，以及 provider 註冊。
"""

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.module_assign import module_assign_registry
from app.dm.bootstrap import register_dm_module
from app.dm.catalog.adapter import CatalogAdapter
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup

pytestmark = pytest.mark.integration

_svc = CatalogAdapter()


async def _audience_group(db) -> str:
    return await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.group_type == "AUDIENCE").limit(1))


async def test_list_controlled_covers_seeded(db):
    """列出三類受控項（#127 已種 4 分類 / 標籤等）。"""
    cats = await _svc.list_controlled(db, "CATEGORY")
    assert any(c.code == "SOP" and c.is_builtin for c in cats)
    tags = await _svc.list_controlled(db, "TAG")
    assert any(t.group_type == "AUDIENCE" for t in tags)


async def test_list_controlled_kinds_covers_three(db):
    """DM 宣告三類受控主檔；TAG 另帶子分組供 DP 分區呈現（#182 D1）。

    DP 端無從得知模組有哪些 kind，硬編碼對照表會在新增 kind 時靜默漏列（fail-closed、
    CI 抓不到），故由模組自報。組名取自 `DM_TAG_GROUP.TAG_GROUP_NAME`、非 DP 硬編碼。
    """
    kinds = {k.kind: k for k in await _svc.list_controlled_kinds(db)}
    assert set(kinds) == {"CATEGORY", "FUNC", "TAG"}
    # 分類碼 / func 代碼由管理者指定且建立後鎖定 → 新增表單需代碼欄
    assert kinds["CATEGORY"].requires_code is True
    assert kinds["FUNC"].requires_code is True
    # TAG 之 code 為「所屬標籤組」、由 DP 從當前分區帶入，不是使用者輸入
    assert kinds["TAG"].requires_code is False
    assert all(k.name for k in kinds.values()), "顯示名不可為空"

    groups = {g.code: g.name for g in kinds["TAG"].groups}
    assert await _audience_group(db) in groups, "AUDIENCE 組須在子分組內（供可見對象維護）"
    assert all(groups.values()), "組名須取自 DM_TAG_GROUP，不可為空"
    assert kinds["CATEGORY"].groups == () and kinds["FUNC"].groups == ()


async def test_create_rename_disable_category(db):
    """分類新增（碼英數鎖定）/ 改名 / 停用；停用後既有引用保留（IS_ENABLED=false 仍在）。"""
    await _svc.create_controlled(db, "CATEGORY", code="ZTAD", name="測試類", operator_id="admin")
    await _svc.rename_controlled(db, "CATEGORY", code="ZTAD", new_name="改名類", operator_id="admin")
    await _svc.set_controlled_enabled(db, "CATEGORY", code="ZTAD", enabled=False, operator_id="admin")
    cat = await db.scalar(select(DmCategory).where(DmCategory.category_code == "ZTAD"))
    assert cat.category_name == "改名類" and cat.is_enabled is False  # 停用不刪除、列仍在


async def test_create_category_bad_code_rejected(db):
    """分類碼含非英數 → DM_CATALOG_003。"""
    with pytest.raises(AppError) as e:
        await _svc.create_controlled(db, "CATEGORY", code="ZT_X", name="x", operator_id="admin")
    assert e.value.error_code == "DM_CATALOG_003"


async def test_create_and_disable_func(db):
    """func_name 新增 / 停用（不刪除）。"""
    await _svc.create_controlled(db, "FUNC", code="ZTF1", name="測試作業", operator_id="admin")
    await _svc.set_controlled_enabled(db, "FUNC", code="ZTF1", enabled=False, operator_id="admin")
    fn = await db.scalar(select(DmFunc).where(DmFunc.func_code == "ZTF1"))
    assert fn.is_enabled is False


async def test_create_tag_in_group_and_rename(db):
    """標籤新增於指定組（code＝組碼、自動配 TAG_ID）/ 改名。"""
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="測試對象", operator_id="admin")
    tag = await db.scalar(select(DmTag).where(DmTag.tag_name == "測試對象"))
    assert tag is not None and tag.tag_group_code == grp
    await _svc.rename_controlled(db, "TAG", code=str(tag.tag_id), new_name="對象改名", operator_id="admin")
    refreshed = await db.scalar(select(DmTag).where(DmTag.tag_id == tag.tag_id))
    assert refreshed.tag_name == "對象改名"


async def test_disable_audience_tag_soft_retire_returns_affected(db):
    """停用 AUDIENCE 標籤 → soft-retire，回傳受影響文件 / 閱覽者數（既有可見性不收回）。"""
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="待退對象", operator_id="admin")
    tag_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "待退對象"))
    result = await _svc.set_controlled_enabled(db, "TAG", code=str(tag_id), enabled=False, operator_id="admin")
    assert result.affected_docs is not None and result.affected_viewers is not None
    tag = await db.scalar(select(DmTag).where(DmTag.tag_id == tag_id))
    assert tag.is_enabled is False


async def test_list_audiences_only_audience_group(db):
    """list_audiences 僅回 AUDIENCE 組（供權限管理核取清單）。"""
    auds = await _svc.list_audiences(db)
    assert len(auds) >= 1 and all(a.group_type == "AUDIENCE" for a in auds)


async def test_list_audiences_excludes_all_universal_tag(db):
    """list_audiences 排除通用值「全體」——它是文件端「所有閱覽者可見」，非可指派給個別使用者之可見對象。"""
    auds = await _svc.list_audiences(db)
    assert "全體" not in {a.name for a in auds}


async def test_maintenance_writes_audit(db):
    """受控主檔維護（新增 / 改名 / 啟停）於同交易寫 SRVDP003 稽核（MODULE=DM / DM-CATALOG）。"""
    from sqlalchemy import text

    await _svc.create_controlled(db, "CATEGORY", code="ZTAU", name="稽核類", operator_id="admin")
    cnt = await db.scalar(
        text(
            'SELECT count(*) FROM "DP_AUDIT_LOG" '
            'WHERE "MODULE"=\'DM\' AND "FUNC_NAME"=\'DM-CATALOG\' AND "TARGET_ID"=:t'
        ),
        {"t": "ZTAU"},
    )
    assert cnt >= 1


async def test_non_numeric_tag_code_rejected(db):
    """TAG 操作之 code 非數字 → 404 DM_CATALOG_002（不丟 500）。"""
    with pytest.raises(AppError) as e:
        await _svc.set_controlled_enabled(db, "TAG", code="abc", enabled=False, operator_id="admin")
    assert e.value.error_code == "DM_CATALOG_002"


async def test_provider_registered(db):
    """DM provider 已註冊進 module_assign_registry。"""
    register_dm_module()
    provider = module_assign_registry.get("DM")
    assert provider is not None
    views = await provider.get_users_assignments(db, ["PV_NONE"])
    assert views["PV_NONE"].roles == frozenset()
