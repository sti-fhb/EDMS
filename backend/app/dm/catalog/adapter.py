"""DM 受控主檔維護轉接層（US1，module-callbacks §3.1）。

供 DP 後台「系統參數與清單」經 registry 呼叫，維護 DM 分類 / func_name / 標籤：
列出（`list_controlled`）、新增 / 改名 / 啟停（不刪除、碼建立後鎖定），AUDIENCE 標籤停用採
soft-retire（回傳受影響文件 / 閱覽者數）；`list_audiences` 供「權限管理」可見對象核取清單。

CATEGORY 委派既有 `CatalogService`（重用碼格式 / 重複檢核）；FUNC / TAG 於本轉接層落地。
`kind` 對應：`CATEGORY`＝分類、`FUNC`＝作業項目、`TAG`＝標籤（create 之 `code` 為所屬標籤組）。
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import ControlledItemView, SetEnabledResult
from app.core.utils import utcnow
from app.dm.catalog.models import DmCategory, DmFunc, DmTag, DmTagGroup
from app.dm.catalog.service import CatalogService
from app.services import AuditLogService

_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
_KINDS = ("CATEGORY", "FUNC", "TAG")
_AUDIENCE = "AUDIENCE"
# 通用值「全體」為**文件端**語意（文件掛上即所有閱覽者可見），非「指派給某使用者」的可見對象，
# 故不列入權限管理可見對象核取清單。與 app.dm.document.visibility._ALL_AUDIENCE_TAG 同一語意。
_ALL_AUDIENCE_TAG = "全體"


class CatalogAdapter:
    """受控主檔維護轉接層（§3.1）；分類委派 CatalogService，func / tag 於此落地。

    維護異動（新增 / 改名 / 啟停 / soft-retire）於同交易呼叫 SRVDP003 寫稽核（`MODULE=DM`），
    與角色指派一致（module-callbacks §3.1）。
    """

    def __init__(self, catalog: CatalogService | None = None, audit: AuditLogService | None = None) -> None:
        self._catalog = catalog or CatalogService()
        self._audit = audit or AuditLogService()

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]:
        """列出某類受控項（供 DP 後台清單 / 下拉）。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            rows = (await db.execute(_maybe_enabled(select(DmCategory), DmCategory, enabled_only))).scalars()
            return [
                ControlledItemView("CATEGORY", c.category_code, c.category_name, c.is_builtin, c.is_enabled)
                for c in rows
            ]
        if kind == "FUNC":
            rows = (await db.execute(_maybe_enabled(select(DmFunc), DmFunc, enabled_only))).scalars()
            return [ControlledItemView("FUNC", f.func_code, f.func_name, False, f.is_enabled) for f in rows]
        rows = (
            await db.execute(_maybe_enabled(select(DmTag, DmTagGroup.group_type).join(DmTagGroup), DmTag, enabled_only))
        ).all()
        return [
            ControlledItemView("TAG", str(t.tag_id), t.tag_name, False, t.is_enabled, gt, t.tag_group_code)
            for t, gt in rows
        ]

    async def list_audiences(self, db: AsyncSession, *, enabled_only: bool = True) -> list[ControlledItemView]:
        """列出 AUDIENCE 組標籤（供權限管理可見對象核取清單）。

        排除通用值「全體」——它是文件端「所有閱覽者可見」的語意，不是可指派給個別使用者的可見對象。
        """
        stmt = (
            select(DmTag)
            .join(DmTagGroup)
            .where(DmTagGroup.group_type == _AUDIENCE, DmTag.tag_name != _ALL_AUDIENCE_TAG)
        )
        if enabled_only:
            stmt = stmt.where(DmTag.is_enabled.is_(True))
        rows = (await db.execute(stmt)).scalars()
        return [
            ControlledItemView("TAG", str(t.tag_id), t.tag_name, False, t.is_enabled, _AUDIENCE, t.tag_group_code)
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
        else:  # TAG：code 為所屬標籤組
            if await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.tag_group_code == code)) is None:
                raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
            db.add(DmTag(tag_group_code=code, tag_name=name, created_user=operator_id, created_date=utcnow()))
            await db.flush()
        await self._log(db, "CREATE", operator_id, target=code, after={"kind": kind, "name": name})

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        """改名（代碼 / TAG_ID 不可改；查無 404 DM_CATALOG_002）。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            await self._catalog.rename_category(db, code=code, new_name=new_name, operator=operator_id)
        else:
            obj = await self._require(db, kind, code)
            if kind == "FUNC":
                obj.func_name = new_name
            else:
                obj.tag_name = new_name
            obj.updated_user, obj.updated_date = operator_id, utcnow()
            await db.flush()
        await self._log(db, "UPDATE", operator_id, target=code, after={"kind": kind, "name": new_name})

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        """啟停（不刪除；停用後既有引用保留）。AUDIENCE 標籤停用採 soft-retire、回傳受影響數。"""
        _ensure_kind(kind)
        after = {"kind": kind, "enabled": enabled}
        if kind == "CATEGORY":
            await self._catalog.set_category_enabled(db, code=code, enabled=enabled, operator=operator_id)
            await self._log(db, "UPDATE", operator_id, target=code, after=after)
            return SetEnabledResult()
        obj = await self._require(db, kind, code)
        if kind == "TAG" and not enabled:
            group = await db.scalar(select(DmTagGroup).where(DmTagGroup.tag_group_code == obj.tag_group_code))
            if group is not None and group.group_type == _AUDIENCE:
                r = await self._catalog.soft_retire_audience_tag(db, tag_id=_tag_id(code), operator=operator_id)
                await self._log(db, "UPDATE", operator_id, target=code, after={**after, "soft_retire": True})
                return SetEnabledResult(affected_docs=r.affected_docs, affected_viewers=r.affected_viewers)
        obj.is_enabled = enabled
        obj.updated_user, obj.updated_date = operator_id, utcnow()
        await db.flush()
        await self._log(db, "UPDATE", operator_id, target=code, after=after)
        return SetEnabledResult()

    async def _log(self, db: AsyncSession, action_type: str, operator_id: str, *, target: str, after: dict) -> None:
        """受控主檔維護異動於同交易寫 SRVDP003 稽核（MODULE=DM）。"""
        await self._audit.log_action(
            db,
            module="DM",
            func_name="DM-CATALOG",
            action_type=action_type,
            result="SUCCESS",
            operator_id=operator_id,
            target_id=target,
            after_value=after,
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
    """TAG code（TAG_ID 字串）轉 int；非數字 → 404 DM_CATALOG_002（避免 int() 丟未攔截 500）。"""
    if not code.isdigit():
        raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
    return int(code)


def _ensure_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")


def _ensure_code(code: str) -> None:
    if not _CODE_PATTERN.match(code):
        raise AppError(status_code=422, detail="代碼格式不合法，僅允許英文與數字", error_code="DM_CATALOG_003")


def _maybe_enabled(stmt, model, enabled_only: bool):
    return stmt.where(model.is_enabled.is_(True)) if enabled_only else stmt
