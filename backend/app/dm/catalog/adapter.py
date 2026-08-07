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

_CODE_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
_KINDS = ("CATEGORY", "FUNC", "TAG")
_AUDIENCE = "AUDIENCE"


class CatalogAdapter:
    """受控主檔維護轉接層（§3.1）；分類委派 CatalogService，func / tag 於此落地。"""

    def __init__(self, catalog: CatalogService | None = None) -> None:
        self._catalog = catalog or CatalogService()

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
        """列出 AUDIENCE 組標籤（供權限管理可見對象核取清單）。"""
        stmt = select(DmTag).join(DmTagGroup).where(DmTagGroup.group_type == _AUDIENCE)
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
            return
        if kind == "FUNC":
            _ensure_code(code)
            if await db.scalar(select(DmFunc.func_code).where(DmFunc.func_code == code)) is not None:
                raise AppError(status_code=409, detail="受控項目代碼已存在", error_code="DM_CATALOG_001")
            db.add(DmFunc(func_code=code, func_name=name, created_user=operator_id, created_date=utcnow()))
            await db.flush()
            return
        # TAG：code 為所屬標籤組
        if await db.scalar(select(DmTagGroup.tag_group_code).where(DmTagGroup.tag_group_code == code)) is None:
            raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
        db.add(DmTag(tag_group_code=code, tag_name=name, created_user=operator_id, created_date=utcnow()))
        await db.flush()

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        """改名（代碼 / TAG_ID 不可改；查無 404 DM_CATALOG_002）。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            await self._catalog.rename_category(db, code=code, new_name=new_name, operator=operator_id)
            return
        obj = await self._require(db, kind, code)
        if kind == "FUNC":
            obj.func_name = new_name
        else:
            obj.tag_name = new_name
        obj.updated_user, obj.updated_date = operator_id, utcnow()
        await db.flush()

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        """啟停（不刪除；停用後既有引用保留）。AUDIENCE 標籤停用採 soft-retire、回傳受影響數。"""
        _ensure_kind(kind)
        if kind == "CATEGORY":
            await self._catalog.set_category_enabled(db, code=code, enabled=enabled, operator=operator_id)
            return SetEnabledResult()
        obj = await self._require(db, kind, code)
        if kind == "TAG" and not enabled:
            group = await db.scalar(select(DmTagGroup).where(DmTagGroup.tag_group_code == obj.tag_group_code))
            if group is not None and group.group_type == _AUDIENCE:
                r = await self._catalog.soft_retire_audience_tag(db, tag_id=int(code), operator=operator_id)
                return SetEnabledResult(affected_docs=r.affected_docs, affected_viewers=r.affected_viewers)
        obj.is_enabled = enabled
        obj.updated_user, obj.updated_date = operator_id, utcnow()
        await db.flush()
        return SetEnabledResult()

    async def _require(self, db: AsyncSession, kind: str, code: str):
        """取 FUNC / TAG 物件；查無 404 DM_CATALOG_002。"""
        if kind == "FUNC":
            obj = await db.scalar(select(DmFunc).where(DmFunc.func_code == code))
        else:
            obj = await db.scalar(select(DmTag).where(DmTag.tag_id == int(code)))
        if obj is None:
            raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")
        return obj


def _ensure_kind(kind: str) -> None:
    if kind not in _KINDS:
        raise AppError(status_code=404, detail="查無此受控項目", error_code="DM_CATALOG_002")


def _ensure_code(code: str) -> None:
    if not _CODE_PATTERN.match(code):
        raise AppError(status_code=422, detail="代碼格式不合法，僅允許英文與數字", error_code="DM_CATALOG_003")


def _maybe_enabled(stmt, model, enabled_only: bool):
    return stmt.where(model.is_enabled.is_(True)) if enabled_only else stmt
