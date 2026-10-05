"""DM 受控主檔維護轉接層（US1，module-callbacks §3.1）。

供 DP 後台「系統參數與清單」經 registry 呼叫，維護 DM 分類 / func_name / 標籤：
列出（`list_controlled`）、新增 / 改名 / 啟停（不刪除、碼建立後鎖定），AUDIENCE 標籤停用採
soft-retire（回傳受影響文件 / 閱覽者數）；`list_audiences` 供「權限管理」可見對象核取清單。

CATEGORY 委派既有 `CatalogService`（重用碼格式 / 重複檢核）；FUNC / TAG 於本轉接層落地。
`kind` 對應：`CATEGORY`＝分類、`FUNC`＝作業項目、`TAG`＝標籤（create 之 `code` 為所屬標籤組）。
"""

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import ControlledGroupView, ControlledItemView, ControlledKindView, SetEnabledResult
from app.core.request_context import get_client_ip
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.catalog.service import CatalogService
from app.services import AuditLogService

_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
# 對應 DM_CATEGORY.CATEGORY_CODE / DM_FUNC.FUNC_CODE 之 VARCHAR(10)
_MAX_CODE_LEN = 10
_MAX_BIGINT = 9_223_372_036_854_775_807
_KINDS = ("CATEGORY", "FUNC", "TAG")
_AUDIENCE = "AUDIENCE"
# 通用值「全體」為**文件端**語意（文件掛上即所有閱覽者可見），非「指派給某使用者」的可見對象，
# 故不列入權限管理可見對象核取清單。與 app.dm.document.visibility._ALL_AUDIENCE_TAG 同一語意。
_ALL_AUDIENCE_TAG = "全體"
_UNIT = "UNIT"  # 單位標籤組（#437）；其 GROUP_TYPE 與 TAG_GROUP_CODE 同值
_ALL_UNITS_TAG = "全單位"
# 標籤名稱在組內重複（`UQ_DM_TAG_GROUP_NAME`）。沿用 `DM_CATALOG_001`——它是 DM 的 409「已存在」
# 碼，與 ET 的 `ET_TAG_002` 對應；但登記訊息寫的是「代碼」，故此處另給貼合名稱情境的文字。
_DUP_TAG_NAME_MSG = "此標籤名稱在該組已存在"

# 各受控清單於 DP 維護頁「說明」欄之內容。**只有 DM 寫得出這些句子**——它們講的是
# 掛上之後文件會怎麼被看見 / 被檢索，屬 DM 業務語意（見 `ControlledKindView.description`）。
_KIND_DESCRIPTIONS = {
    "CATEGORY": "文件建檔時必選。",
    "FUNC": "主系統作業功能代號。僅「系統操作手冊」類文件可標記，供文件庫依作業項目反查該作業的手冊。",
    "TAG": "文件標籤庫。撰寫者只能從此挑選、不可自由輸入；不刪除，淘汰改停用。",
}

# 標籤組各自的說明。組由 `DM_TAG_GROUP` 資料決定，故以組代碼對照；
# 管理者自建的組查不到對照，由 DP 退回 `TAG` 的 kind 層說明。
_TAG_GROUP_DESCRIPTIONS = {
    _UNIT: "可見對象的一半。與「職位」組成（單位, 職位）配對；文件掛「全單位」表示不限單位。",
    _AUDIENCE: (
        "可見對象的另一半。文件與閱覽者皆以（單位, 職位）配對授權，閱覽者只看得到配對相符、或掛「全體」的文件。"
    ),
    "LEGAL": "檢索用標籤，標示文件依據的法規來源。僅供文件庫篩選，不影響誰看得到。",
    "MODULE": "檢索用標籤，標示文件適用的主系統模組。僅供文件庫篩選，不影響誰看得到。",
    "NATURE": "檢索用標籤，標示文件的適用情境（平時 / 緊急 / 戰時）。僅供文件庫篩選，不影響誰看得到。",
}

# 分區順序：可見對象的兩維度排在最前且**單位在職位之前**——與（單位, 職位）的配對書寫順序
# 一致，維護者由上往下讀才對得起來。其餘（檢索標籤）按代碼排，加入新組時位置可預期。
_GROUP_ORDER = {_UNIT: 0, _AUDIENCE: 1}
_GROUP_ORDER_DEFAULT = 9


class CatalogAdapter:
    """受控主檔維護轉接層（§3.1）；分類委派 CatalogService，func / tag 於此落地。

    維護異動（新增 / 改名 / 啟停 / soft-retire）於同交易呼叫 SRVDP003 寫稽核（`MODULE=DM`），
    與角色指派一致（module-callbacks §3.1）。
    """

    def __init__(self, catalog: CatalogService | None = None, audit: AuditLogService | None = None) -> None:
        self._catalog = catalog or CatalogService()
        self._audit = audit or AuditLogService()

    async def list_controlled_kinds(self, db: AsyncSession) -> list[ControlledKindView]:
        """DM 可維護之受控主檔類別：分類 / 作業項目 / 標籤三類。

        標籤另帶子分組供 DP 分區呈現（可見對象與三組檢索標籤）；**組名取自
        `DM_TAG_GROUP.TAG_GROUP_NAME`**——標籤組可由資料異動，DP 硬編碼會與實際不符。
        `requires_code`：分類 / 作業項目之代碼由管理者指定且建立後鎖定，故新增表單需代碼欄；
        標籤之 `code` 為「所屬標籤組」、由 DP 自當前分區帶入，非使用者輸入。

        `description` 取自本模組的 `_KIND_DESCRIPTIONS` / `_TAG_GROUP_DESCRIPTIONS`——
        組名（「職位」「法規關聯」）說不出「掛了會怎樣」，而那正是維護者要知道的事。
        自建標籤組查無對照時留空，由 DP 退回 kind 層說明。

        分區順序見 `_GROUP_ORDER`：排序在**應用層**而非 SQL，因為它表達的是畫面上的閱讀
        順序（可見對象兩維度優先、單位在職位之前），不是資料的自然順序。
        """
        rows = (
            await db.execute(select(DmTagGroup).where(DmTagGroup.deleted == 0).order_by(DmTagGroup.tag_group_code))
        ).scalars()
        ordered = sorted(
            rows, key=lambda g: (_GROUP_ORDER.get(g.tag_group_code, _GROUP_ORDER_DEFAULT), g.tag_group_code)
        )
        groups = tuple(
            ControlledGroupView(
                code=g.tag_group_code,
                name=g.tag_group_name,
                description=_TAG_GROUP_DESCRIPTIONS.get(g.tag_group_code, ""),
            )
            for g in ordered
        )
        return [
            ControlledKindView(
                kind="CATEGORY", name="文件分類", requires_code=True, description=_KIND_DESCRIPTIONS["CATEGORY"]
            ),
            ControlledKindView(
                kind="FUNC", name="關聯作業項目", requires_code=True, description=_KIND_DESCRIPTIONS["FUNC"]
            ),
            ControlledKindView(
                kind="TAG", name="標籤", requires_code=False, description=_KIND_DESCRIPTIONS["TAG"], groups=groups
            ),
        ]

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]:
        """列出某類受控項（供 DP 後台清單 / 下拉）。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            # 三類皆須明確排序：不加 ORDER BY 時順序取決於列的實體位置，改名 / 啟停後該列會移位，
            # 維護畫面看起來就是亂的。標籤依建立順序（TAG_ID），分類 / 作業項目依代碼。
            stmt = _maybe_enabled(select(DmCategory), DmCategory, enabled_only).order_by(DmCategory.category_code)
            rows = (await db.execute(stmt)).scalars()
            return [
                ControlledItemView("CATEGORY", c.category_code, c.category_name, c.is_builtin, c.is_enabled)
                for c in rows
            ]
        if kind == "FUNC":
            stmt = _maybe_enabled(select(DmFunc), DmFunc, enabled_only).order_by(DmFunc.func_code)
            rows = (await db.execute(stmt)).scalars()
            return [ControlledItemView("FUNC", f.func_code, f.func_name, False, f.is_enabled) for f in rows]
        stmt = _maybe_enabled(select(DmTag, DmTagGroup.group_type).join(DmTagGroup), DmTag, enabled_only).order_by(
            DmTag.tag_id
        )
        rows = (await db.execute(stmt)).all()
        return [
            ControlledItemView("TAG", str(t.tag_id), t.tag_name, False, t.is_enabled, gt, t.tag_group_code)
            for t, gt in rows
        ]

    async def list_audiences(self, db: AsyncSession, *, enabled_only: bool = True) -> list[ControlledItemView]:
        """列出可指派之可見對象項（供權限管理配對清單）。

        回**兩個維度**（#437）：職位（`group_type='AUDIENCE'`）與單位（`group_type='UNIT'`），
        由呼叫端依 `group_type` 分成兩個下拉組成 (單位, 職位) 配對。契約簽名不變——`group_type`
        本就是為了區分項目類別而存在，故不需擴充 `ModuleAssignProvider`（ET 僅回單一類別、
        行為不受影響）。

        兩個通用值皆排除：「全體」與「全單位」是**文件端**「不限」之語意，人不會屬於它們。
        人側之單位可為未指定（`DM_USER_TAG.UNIT_TAG_ID IS NULL`），那是過渡狀態而非「全單位」。
        """
        stmt = (
            select(DmTag)
            .join(DmTagGroup)
            .where(
                DmTagGroup.group_type.in_((_AUDIENCE, _UNIT)),
                DmTag.tag_name.not_in((_ALL_AUDIENCE_TAG, _ALL_UNITS_TAG)),
            )
            .order_by(DmTagGroup.group_type, DmTag.tag_id)
        )
        if enabled_only:
            stmt = stmt.where(DmTag.is_enabled.is_(True))
        rows = (await db.execute(stmt)).scalars()
        return [
            ControlledItemView(
                "TAG",
                str(t.tag_id),
                t.tag_name,
                False,
                t.is_enabled,
                _UNIT if t.tag_group_code == _UNIT else _AUDIENCE,
                t.tag_group_code,
            )
            for t in rows
        ]

    async def create_controlled(self, db: AsyncSession, kind: str, *, code: str, name: str, operator_id: str) -> None:
        """新增受控項（CATEGORY/FUNC：code＝代碼；TAG：code＝所屬標籤組）。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            await self._catalog.create_category(db, code=code, name=name, operator=operator_id)
        elif kind == "FUNC":
            _ensure_code(code)
            if await db.scalar(select(DmFunc.func_code).where(DmFunc.func_code == code)) is not None:
                raise AppError(status_code=409, detail="受控項目代碼已存在", error_code="DM_CATALOG_001")
            db.add(DmFunc(func_code=code, func_name=name, created_user=operator_id, created_date=utcnow()))
            await db.flush()
        target = code
        if kind == "TAG":  # code 為所屬標籤組
            if await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.tag_group_code == code)) is None:
                raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
            await _ensure_tag_name_free(db, group_code=code, name=name)
            tag = DmTag(tag_group_code=code, tag_name=name, created_user=operator_id, created_date=utcnow())
            db.add(tag)
            await _flush_catching_duplicate(db)
            # 稽核 target 用新建之 TAG_ID——`code` 是所屬標籤組，無法定位被建立的是哪個標籤
            target = str(tag.tag_id)
        await self._log(db, "CREATE", operator_id, target=target, after={"kind": kind, "name": name})

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        """改名（代碼 / TAG_ID 不可改；查無 404 DM_CATALOG_002）。"""
        _ensure_kind(kind)
        # 前值一律於改值**之前**組成純 dict：ORM 就地更新後再讀屬性會拿到新值，
        # 稽核會寫出 before == after 且不會失敗（靜默錯誤）。
        if kind == "CATEGORY":
            cat = await db.scalar(select(DmCategory).where(DmCategory.category_code == code))
            before = None if cat is None else {"kind": kind, "name": cat.category_name}
            await self._catalog.rename_category(db, code=code, new_name=new_name, operator=operator_id)
        else:
            obj = await self._require(db, kind, code)
            before = {"kind": kind, "name": obj.func_name if kind == "FUNC" else obj.tag_name}
            if kind == "FUNC":
                obj.func_name = new_name
            else:
                # 排除自己：少了 `exclude_tag_id`，「改名成原值」這個無害操作會被自己擋下
                await _ensure_tag_name_free(
                    db, group_code=obj.tag_group_code, name=new_name, exclude_tag_id=obj.tag_id
                )
                obj.tag_name = new_name
            obj.updated_user, obj.updated_date = operator_id, utcnow()
            await _flush_catching_duplicate(db)
        await self._log(db, "UPDATE", operator_id, target=code, before=before, after={"kind": kind, "name": new_name})

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        """啟停（不刪除；停用後既有引用保留）。AUDIENCE 標籤停用採 soft-retire、回傳受影響數。"""
        _ensure_kind(kind)
        after = {"kind": kind, "enabled": enabled}
        if kind == "CATEGORY":
            cat = await db.scalar(select(DmCategory).where(DmCategory.category_code == code))
            before = None if cat is None else {"kind": kind, "enabled": cat.is_enabled}
            await self._catalog.set_category_enabled(db, code=code, enabled=enabled, operator=operator_id)
            await self._log(db, "UPDATE", operator_id, target=code, before=before, after=after)
            return SetEnabledResult()
        obj = await self._require(db, kind, code)
        before = {"kind": kind, "enabled": obj.is_enabled}  # 同上：須在改值前取
        if kind == "TAG" and not enabled:
            group = await db.scalar(select(DmTagGroup).where(DmTagGroup.tag_group_code == obj.tag_group_code))
            # 可見對象之兩個維度（職位 AUDIENCE / 單位 UNIT）皆採 soft-retire 並回報受影響數（#437）
            if group is not None and group.group_type in (_AUDIENCE, _UNIT):
                r = await self._catalog.soft_retire_audience_tag(
                    db, tag_id=_tag_id(code), operator=operator_id, is_unit=group.group_type == _UNIT
                )
                await self._log(
                    db, "UPDATE", operator_id, target=code, before=before, after={**after, "soft_retire": True}
                )
                return SetEnabledResult(affected_docs=r.affected_docs, affected_viewers=r.affected_viewers)
        obj.is_enabled = enabled
        obj.updated_user, obj.updated_date = operator_id, utcnow()
        await db.flush()
        await self._log(db, "UPDATE", operator_id, target=code, before=before, after=after)
        return SetEnabledResult()

    async def _log(
        self,
        db: AsyncSession,
        action_type: str,
        operator_id: str,
        *,
        target: str,
        after: dict,
        before: dict | None = None,
    ) -> None:
        """受控主檔維護異動於同交易寫 SRVDP003 稽核（MODULE=DM）。

        `before` 為異動前值（FR-DP-US5-06 要求前後值皆記）。AUDIENCE 標籤即文件可見性之
        授權群組，改名等於「成員不變、群組身分標籤易手」，無前值則事後無從還原原名。
        """
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-CATALOG",
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=target,
            before_value=before,
            after_value=after,
            source_ip=get_client_ip(),
        )

    async def _require(self, db: AsyncSession, kind: str, code: str):
        """取 FUNC / TAG 物件；查無 / 代碼格式非法 404 DM_CATALOG_002。"""
        if kind == "FUNC":
            obj = await db.scalar(select(DmFunc).where(DmFunc.func_code == code))
        else:
            obj = await db.scalar(select(DmTag).where(DmTag.tag_id == _tag_id(code)))
        if obj is None:
            raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
        return obj


def _tag_id(code: str) -> int:
    """TAG code（`TAG_ID` 字串）轉 int；非十進位數字 / 超出 BIGINT → 404 DM_CATALOG_002。

    用 `isdecimal()` 而非 `isdigit()`——後者對 Unicode 數字字元（`²` / `①`）回 True
    但 `int()` 會拋 ValueError；另加 BIGINT 界限，否則超長數字會在 asyncpg 綁參數時拋
    DataError。兩者皆為未攔截的 500。比照 `app/et/catalog/adapter.py` 之 `_require_tag`。

    `code` 為 path param，DP 端 schema 的長度上限只約束 body、管不到此處，故界限必須在此。
    """
    if not (code.isdecimal() and len(code) <= 19 and 0 < int(code) <= _MAX_BIGINT):
        raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
    return int(code)


def _ensure_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")


async def _ensure_tag_name_free(
    db: AsyncSession, *, group_code: str, name: str, exclude_tag_id: int | None = None
) -> None:
    """確認該標籤組內尚無同名標籤，否則回 409（#506）。

    `DM_TAG` 有 `UQ_DM_TAG_GROUP_NAME`（組 + 名稱，#437）。在本檢核之前，新增 / 改名撞到
    既有名稱會直接讓 `IntegrityError` 逸出——`main.py` 無對應 handler，落到泛用 `Exception`
    handler 變成 **500**，而 DP03 的標籤分區一按就中。

    唯一鍵是 **(組, 名稱)** 不是 (名稱)：查詢必須帶 `group_code`，否則會擋掉合法的跨組同名
    （例如「護理師」可同時存在於職位組與某檢索組）。

    `exclude_tag_id` 供改名排除自己，否則「改名成原值」會被自己擋下。

    寫法比照同契約的 ET 實作（`et/catalog/adapter.py` 的 `create_controlled` / `rename_controlled`）。
    """
    stmt = select(DmTag.tag_id).where(DmTag.tag_group_code == group_code, DmTag.tag_name == name)
    if exclude_tag_id is not None:
        stmt = stmt.where(DmTag.tag_id != exclude_tag_id)
    if await db.scalar(stmt) is not None:
        raise AppError(status_code=409, detail=_DUP_TAG_NAME_MSG, error_code="DM_CATALOG_001")


async def _flush_catching_duplicate(db: AsyncSession) -> None:
    """flush，並把撞唯一鍵的 `IntegrityError` 轉成乾淨的 409。

    `_ensure_tag_name_free` 與本次 flush 之間有 TOCTOU 空窗：兩位管理者同時送出同名標籤時，
    兩邊的檢核都會通過，後寫入的那邊撞唯一鍵。比照 `dp/params/service.py` 的 `create_detail`
    兜底（否則落全域 500），交由 `get_db` rollback。

    ⚠️ **這道無法以測試覆蓋**——需要真實並發才觸發。留著是因為少了它，本 issue 要修的那個
    500 只是從「必然」縮成「偶發」，而偶發的 500 更難被發現。
    """
    try:
        await db.flush()
    except IntegrityError as exc:
        raise AppError(status_code=409, detail=_DUP_TAG_NAME_MSG, error_code="DM_CATALOG_001") from exc


def _ensure_code(code: str) -> None:
    """代碼格式檢核：英數且不超過欄位長度。

    長度上限對應 `DM_FUNC.FUNC_CODE` / `DM_CATEGORY.CATEGORY_CODE` 之 VARCHAR(10)；
    未擋會在 INSERT 時由 DB 拋 `value too long`，落成未攔截的 500 而非乾淨的 422。
    #182 讓 DP 後台第一次可外部呼叫此路徑，該缺口從此可達。
    """
    if not _CODE_PATTERN.match(code) or len(code) > _MAX_CODE_LEN:
        raise AppError(status_code=422, detail="代碼格式不合法，僅允許英文與數字", error_code="DM_CATALOG_003")


def _maybe_enabled(stmt, model, enabled_only: bool):
    return stmt.where(model.is_enabled.is_(True)) if enabled_only else stmt
