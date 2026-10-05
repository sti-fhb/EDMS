"""DM 受控主檔維護轉接層整合測試（§3.1，真實 DB）。

驗證：三類受控項（CATEGORY / FUNC / TAG）之列出 / 新增 / 改名 / 啟停、不刪除、碼鎖定、
停用保留既有引用、AUDIENCE / UNIT 標籤停用 soft-retire 回受影響數、list_audiences，以及 provider 註冊。
"""

import json

import pytest
from sqlalchemy import select

from app.core.exceptions import AppError
from app.core.module_assign import module_assign_registry
from app.core.utils import utcnow
from app.dm.bootstrap import register_dm_module
from app.dm.catalog.adapter import CatalogAdapter
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.document.models import DmDocTag, DmDocument
from app.dp.audit.models import DpAuditLog

pytestmark = pytest.mark.integration

_svc = CatalogAdapter()


async def _audience_group(db) -> str:
    return await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.group_type == "AUDIENCE").limit(1))


async def _unit_group(db) -> str:
    return await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.group_type == "UNIT").limit(1))


async def test_disable_unit_tag_counts_by_unit_column(db):
    """停用單位標籤 → soft-retire 之受影響數須依 `UNIT_TAG_ID` 計（#437）。

    可見對象為 (單位, 職位) 配對：單位存 `UNIT_TAG_ID`、職位存 `TAG_ID`。若計數沿用 `TAG_ID`
    比對，停用單位時兩個數字**恆為 0**——管理者會看到「不影響任何文件」而停掉一個實際綁著大量
    文件的單位，全程無錯誤。故此處斷言確切數字而非僅 `is not None`。
    """
    grp = await _unit_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="待退單位", operator_id="admin")
    unit_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "待退單位"))
    role_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_group_code == "AUDIENCE").limit(1))
    now = utcnow()
    db.add(
        DmDocument(
            doc_id="DM-SOP-000800",
            doc_name="掛待退單位之文件",
            category_code="SOP",
            status="PUBLISHED",
            created_user="e",
            created_date=now,
        )
    )
    await db.flush()
    db.add(DmDocTag(doc_id="DM-SOP-000800", tag_id=role_id, unit_tag_id=unit_id, created_user="e", created_date=now))
    await db.flush()

    result = await _svc.set_controlled_enabled(db, "TAG", code=str(unit_id), enabled=False, operator_id="admin")

    assert result.affected_docs == 1
    tag = await db.scalar(select(DmTag).where(DmTag.tag_id == unit_id))
    assert tag.is_enabled is False  # soft-retire：停用但既有引用保留


async def test_list_controlled_covers_seeded(db):
    """列出三類受控項（#127 已種 4 分類 / 標籤等）。"""
    cats = await _svc.list_controlled(db, "CATEGORY")
    assert any(c.code == "SOP" and c.is_builtin for c in cats)
    tags = await _svc.list_controlled(db, "TAG")
    assert any(t.group_type == "AUDIENCE" for t in tags)


async def test_標籤清單依建立順序_改名後不移位(db):
    """維護畫面的標籤順序要固定（依 TAG_ID，即建立順序）。

    不加 ORDER BY 時順序取決於列的實體位置：PostgreSQL 的 UPDATE 會寫一份新列版本，
    改名過的標籤就跑到最後——管理者每改一次名，清單就重排一次，看起來是亂的。
    故先建三筆、改名第一筆，再斷言它仍排第一。
    """
    group = await _audience_group(db)
    for name in ("ZT排序一", "ZT排序二", "ZT排序三"):
        await _svc.create_controlled(db, "TAG", code=group, name=name, operator_id="admin")
    first_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "ZT排序一"))
    await _svc.rename_controlled(db, "TAG", code=str(first_id), new_name="ZT排序一改", operator_id="admin")

    names = [t.name for t in await _svc.list_controlled(db, "TAG") if t.name.startswith("ZT排序")]
    assert names == ["ZT排序一改", "ZT排序二", "ZT排序三"]
    tag_ids = [int(t.code) for t in await _svc.list_controlled(db, "TAG")]
    assert tag_ids == sorted(tag_ids)


async def test_分類與作業項目依代碼排序(db):
    """分類 / 作業項目之代碼由管理者指定、具業務意義，依代碼排序。"""
    for code in ("ZTCB", "ZTCA"):
        await _svc.create_controlled(db, "CATEGORY", code=code, name=f"排序{code}", operator_id="admin")
    await _svc.rename_controlled(db, "CATEGORY", code="ZTCA", new_name="排序改名", operator_id="admin")
    cat_codes = [c.code for c in await _svc.list_controlled(db, "CATEGORY")]
    assert cat_codes == sorted(cat_codes)

    for code in ("ZTFB", "ZTFA"):
        await _svc.create_controlled(db, "FUNC", code=code, name=f"排序{code}", operator_id="admin")
    func_codes = [f.code for f in await _svc.list_controlled(db, "FUNC")]
    assert func_codes == sorted(func_codes)


async def test_改名稽核含異動前值(db):
    """FR-DP-US5-06 要求稽核含前後值。

    AUDIENCE 標籤即文件可見性之授權群組，改名等於「成員不變、群組身分標籤易手」；
    無前值則事後無從還原原名。前值須於**改值之前**取得——ORM 就地更新後再讀屬性會拿到
    新值，寫出 before == after 且不會失敗（靜默錯誤），故一併斷言兩者相異。
    """
    group = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=group, name="ZT改名前", operator_id="admin")
    tag_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "ZT改名前"))

    await _svc.rename_controlled(db, "TAG", code=str(tag_id), new_name="ZT改名後", operator_id="admin")

    log = (
        await db.execute(
            select(DpAuditLog)
            .where(DpAuditLog.target_id == str(tag_id), DpAuditLog.action_type == "UPDATE")
            .order_by(DpAuditLog.log_id.desc())
            .limit(1)
        )
    ).scalar_one()
    assert json.loads(log.before_value)["name"] == "ZT改名前"
    assert json.loads(log.after_value)["name"] == "ZT改名後"


async def test_新增標籤之稽核以_tag_id_定位(db):
    """新增 TAG 時 `code` 是所屬標籤組，用它當 target_id 無法定位被建立的是哪個標籤。"""
    group = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=group, name="ZT稽核定位", operator_id="admin")
    tag_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "ZT稽核定位"))

    exists = await db.scalar(
        select(DpAuditLog.log_id).where(DpAuditLog.target_id == str(tag_id), DpAuditLog.action_type == "CREATE")
    )
    assert exists is not None, "CREATE 稽核之 target_id 應為新建標籤的 TAG_ID，而非所屬標籤組代碼"


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


async def test_同組同名標籤新增回409不是500(db):
    """組內同名標籤之新增須回乾淨的 409，不得讓唯一鍵把例外打成 500（#506）。

    `DM_TAG` 有 `UQ_DM_TAG_GROUP_NAME`（#437）。在本修正之前，`create_controlled` 只檢查
    「標籤組存在」就直接 `flush()`，於是撞唯一鍵 → `IntegrityError` → `main.py` 無對應
    handler → 落到泛用 `Exception` handler → **500**。DP03 的標籤分區新增一按就中。

    ⚠️ 斷言 `error_code` 而非只看狀態碼：500 也可能恰巧被某個中介層轉成 4xx，
    只驗狀態碼會讓「換一種方式壞掉」看起來像修好了。
    """
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="ZT重複名", operator_id="admin")

    with pytest.raises(AppError) as exc:
        await _svc.create_controlled(db, "TAG", code=grp, name="ZT重複名", operator_id="admin")

    assert exc.value.status_code == 409
    assert exc.value.error_code == "DM_CATALOG_001"


async def test_跨組同名標籤可新增(db):
    """對照組：唯一鍵是 (組, 名稱) 而非 (名稱)——跨組同名合法，不得被上一條的檢核誤擋。

    沒有這條對照，把檢核寫成「只比名稱」也會讓上一條通過，而那會擋掉合法操作
    （例如「護理師」同時存在於職位組與某檢索組）。
    """
    grp_a = await _audience_group(db)
    grp_b = await _unit_group(db)
    assert grp_a != grp_b, "前提：測試需要兩個不同的標籤組"

    await _svc.create_controlled(db, "TAG", code=grp_a, name="ZT跨組同名", operator_id="admin")
    await _svc.create_controlled(db, "TAG", code=grp_b, name="ZT跨組同名", operator_id="admin")

    groups = (
        await db.execute(select(DmTag.tag_group_code).where(DmTag.tag_name == "ZT跨組同名"))
    ).scalars().all()
    assert set(groups) == {grp_a, grp_b}


async def test_改名為同組既有名稱回409(db):
    """改名撞到同組既有名稱同樣須回 409——與新增是同一個唯一鍵、同一種 500。"""
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="ZT原名A", operator_id="admin")
    await _svc.create_controlled(db, "TAG", code=grp, name="ZT原名B", operator_id="admin")
    tag_b = await db.scalar(select(DmTag).where(DmTag.tag_name == "ZT原名B"))

    with pytest.raises(AppError) as exc:
        await _svc.rename_controlled(db, "TAG", code=str(tag_b.tag_id), new_name="ZT原名A", operator_id="admin")

    assert exc.value.status_code == 409
    assert exc.value.error_code == "DM_CATALOG_001"


async def test_改名為自己原本的名稱不被誤擋(db):
    """邊界：同名檢核必須排除自己，否則「改名成原值」這個無害操作會被擋下。

    這是自我排除條件（`tag_id != 自己`）唯一會變紅的情境——少了它，上面三條照樣全過。
    """
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="ZT不變名", operator_id="admin")
    tag = await db.scalar(select(DmTag).where(DmTag.tag_name == "ZT不變名"))

    await _svc.rename_controlled(db, "TAG", code=str(tag.tag_id), new_name="ZT不變名", operator_id="admin")

    refreshed = await db.scalar(select(DmTag).where(DmTag.tag_id == tag.tag_id))
    assert refreshed.tag_name == "ZT不變名"


async def test_disable_audience_tag_soft_retire_returns_affected(db):
    """停用 AUDIENCE 標籤 → soft-retire，回傳受影響文件 / 閱覽者數（既有可見性不收回）。"""
    grp = await _audience_group(db)
    await _svc.create_controlled(db, "TAG", code=grp, name="待退對象", operator_id="admin")
    tag_id = await db.scalar(select(DmTag.tag_id).where(DmTag.tag_name == "待退對象"))
    result = await _svc.set_controlled_enabled(db, "TAG", code=str(tag_id), enabled=False, operator_id="admin")
    assert result.affected_docs is not None and result.affected_viewers is not None
    tag = await db.scalar(select(DmTag).where(DmTag.tag_id == tag_id))
    assert tag.is_enabled is False


async def test_list_audiences_returns_both_dimensions(db):
    """list_audiences 回職位與單位兩個維度，供權限管理組成 (單位, 職位) 配對（#437）。"""
    auds = await _svc.list_audiences(db)
    kinds = {a.group_type for a in auds}
    assert kinds == {"AUDIENCE", "UNIT"}
    assert all(a.kind == "TAG" for a in auds)


async def test_list_controlled_kinds_includes_unit_group(db):
    """UNIT 組自動出現在可維護之標籤分組（#437）。

    `list_controlled_kinds` 由 `DM_TAG_GROUP` 動態讀取，故新增標籤組不需改程式即可於 DP 後台維護——
    這是客戶日後補單位（例如三總院內捐血站）的路徑，值得釘住，否則被改成硬編碼清單也不會有人發現。
    """
    kinds = await _svc.list_controlled_kinds(db)
    tag_kind = next(k for k in kinds if k.kind == "TAG")
    assert "UNIT" in {g.code for g in tag_kind.groups}


async def test_list_audiences_excludes_all_universal_tag(db):
    """排除兩個通用值——「全體」/「全單位」是**文件端**「不限」之語意，非可指派給個人者。"""
    auds = await _svc.list_audiences(db)
    names = {a.name for a in auds}
    assert "全體" not in names and "全單位" not in names


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
