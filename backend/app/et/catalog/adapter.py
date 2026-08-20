"""ET 受控主檔維護轉接層（module-callbacks §3.1；SRVET004）。

ET 之受控主檔僅一類：**受訓單位標籤庫 `ET_TAG`**（`kind='TAG'`）。維護入口於平台
DP 後台「系統參數與清單」，經本轉接層呼叫——**DP 不直接寫 ET 表**。比照
`app/dm/catalog/adapter.py`。

> ⚠️ **DP 端目前尚未接上受控主檔維護**（`list_controlled` / `set_controlled_enabled`
> 全 backend 無 DP 呼叫者，見 #182）。本轉接層先行交付以符合 Protocol，端到端驗證
> 待 #182。

**「全體」標籤保護**：`IS_ALL=true` 之標籤不可停用、不可改名（`ET_TAG_001`）。
此為 ET 業務規則，**伺服器端保護必須在 ET**——DP 端之 `is_builtin` 旗標與前端隱藏
僅為 UX，不可作為唯一防線。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import ControlledItemView, SetEnabledResult
from app.et.catalog.models import EtTag, EtUserTag
from app.services import AuditLogService

logger = logging.getLogger(__name__)

# 受控主檔「定義」維護之稽核碼，與角色 / 標籤「指派」（ET-ROLES）分開——
# 比照 DM 之 DM-CATALOG vs DM-ROLES，使稽核可依 FUNC_NAME 區分兩類管理行為。
_FUNC_NAME = "ET-CATALOG"
_MODULE = "ET"
_KIND_TAG = "TAG"


def _ensure_tag_kind(kind: str) -> None:
    """ET 僅有 `TAG` 一類受控主檔；其餘 kind 一律拒絕（fail-closed）。"""
    if kind != _KIND_TAG:
        raise AppError(status_code=404, detail="查無此受訓單位標籤或項目類別", error_code="ET_TAG_003")


class EtCatalogAdapter:
    """受訓單位標籤庫維護（供 DP 後台「系統參數與清單」呼叫）。"""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService()

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]:
        """列出受訓單位標籤；`code` 為 `TAG_ID` 字串化、`is_builtin` 供 DP 決定操作入口。"""
        _ensure_tag_kind(kind)
        stmt = select(EtTag).where(EtTag.deleted == 0)
        if enabled_only:
            stmt = stmt.where(EtTag.is_active.is_(True))
        rows = await db.scalars(stmt.order_by(EtTag.display_order, EtTag.tag_id))
        return [
            ControlledItemView(
                kind=_KIND_TAG,
                code=str(t.tag_id),
                name=t.tag_name,
                is_builtin=t.is_builtin,
                is_enabled=t.is_active,
            )
            for t in rows.all()
        ]

    async def list_audiences(self, db: AsyncSession, *, enabled_only: bool = True) -> list[ControlledItemView]:
        """權限管理之「受訓單位標籤」可選清單。

        與 DM 不同：DM 將通用值「全體」排除於可指派清單外（那是文件端語意）；
        **ET 之「全體」代表所有具學員角色者、同樣不需逐人指派**，故一併排除，
        避免管理者誤以為要逐人貼「全體」。
        """
        _ensure_tag_kind(_KIND_TAG)
        stmt = select(EtTag).where(EtTag.deleted == 0, EtTag.is_all.is_(False))
        if enabled_only:
            stmt = stmt.where(EtTag.is_active.is_(True))
        rows = await db.scalars(stmt.order_by(EtTag.display_order, EtTag.tag_id))
        return [
            ControlledItemView(
                kind=_KIND_TAG,
                code=str(t.tag_id),
                name=t.tag_name,
                is_builtin=t.is_builtin,
                is_enabled=t.is_active,
            )
            for t in rows.all()
        ]

    async def create_controlled(self, db: AsyncSession, kind: str, *, code: str, name: str, operator_id: str) -> None:
        """新增受訓單位標籤。

        `code` 由 DP 端傳入但 **ET 不採用**——`TAG_ID` 為 Identity 自動配號；
        標籤以 `TAG_NAME` 唯一識別。新增之標籤 `IS_BUILTIN=false`、`IS_ALL=false`。
        """
        _ensure_tag_kind(kind)
        now = datetime.now(timezone.utc)
        exists = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
        if exists is not None:
            raise AppError(status_code=409, detail="受訓單位標籤名稱已存在", error_code="ET_TAG_002")

        max_order = await db.scalar(select(EtTag.display_order).order_by(EtTag.display_order.desc()).limit(1))
        db.add(
            EtTag(
                tag_name=name,
                is_active=True,
                is_all=False,
                is_builtin=False,
                display_order=(max_order or 0) + 1,
                created_user=operator_id,
                created_date=now,
                deleted=0,
            )
        )
        await db.flush()
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator_id,
            description="新增受訓單位標籤",
            after_value={"tag_name": name},
        )

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        """標籤改名。**內建標籤（含「全體」）不可改名**。"""
        _ensure_tag_kind(kind)
        tag = await self._require_tag(db, code)
        if tag.is_builtin:
            raise AppError(status_code=422, detail="內建標籤不可停用或改名", error_code="ET_TAG_001")

        dup = await db.scalar(
            select(EtTag.tag_id).where(EtTag.tag_name == new_name, EtTag.tag_id != tag.tag_id, EtTag.deleted == 0)
        )
        if dup is not None:
            raise AppError(status_code=409, detail="受訓單位標籤名稱已存在", error_code="ET_TAG_002")

        before = tag.tag_name
        tag.tag_name = new_name
        tag.updated_user = operator_id
        tag.updated_date = datetime.now(timezone.utc)
        await db.flush()
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(tag.tag_id),
            description="受訓單位標籤改名",
            before_value={"tag_name": before},
            after_value={"tag_name": new_name},
        )

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        """標籤啟用 / 停用（soft-retire，不刪除）。

        停用後**不可再掛至新課程**，已掛之既有課程與 `ET_COURSE_TAG` 不受影響
        （比照 DM AUDIENCE）。回傳受影響之使用者指派數供 DP 端提示。

        **「全體」不可停用**——它代表所有具學員角色者，停用將使自動邀請機制失效。
        """
        _ensure_tag_kind(kind)
        tag = await self._require_tag(db, code)
        if not enabled and tag.is_all:
            raise AppError(status_code=422, detail="內建標籤不可停用或改名", error_code="ET_TAG_001")

        if tag.is_active == enabled:
            return SetEnabledResult()  # 無異動

        tag.is_active = enabled
        tag.updated_user = operator_id
        tag.updated_date = datetime.now(timezone.utc)
        await db.flush()

        # 單次 count 查詢（比照 dm/catalog/service.py 之 soft_retire_audience_tag）
        affected_count = await db.scalar(
            select(func.count()).select_from(EtUserTag).where(EtUserTag.tag_id == tag.tag_id, EtUserTag.deleted == 0)
        )

        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(tag.tag_id),
            description="受訓單位標籤啟用 / 停用",
            after_value={"is_active": enabled},
        )
        return SetEnabledResult(affected_viewers=affected_count)

    async def _require_tag(self, db: AsyncSession, code: str) -> EtTag:
        """依 `code`（TAG_ID 字串）取標籤；查無或格式錯誤一律 404。"""
        if not code.isdigit():
            raise AppError(status_code=404, detail="查無此受訓單位標籤或項目類別", error_code="ET_TAG_003")
        tag = await db.scalar(select(EtTag).where(EtTag.tag_id == int(code), EtTag.deleted == 0))
        if tag is None:
            raise AppError(status_code=404, detail="查無此受訓單位標籤或項目類別", error_code="ET_TAG_003")
        return tag
