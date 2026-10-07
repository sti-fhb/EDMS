"""ET 受控主檔維護轉接層（module-callbacks §3.1；SRVET004）。

ET 之受控主檔僅一類：**受訓對象標籤庫 `ET_TAG`**（`kind='TAG'`），分「單位」「職位」兩組
（`TAG_TYPE`，#538）。維護入口於平台
DP 後台「系統參數與清單」，經本轉接層呼叫——**DP 不直接寫 ET 表**。比照
`app/dm/catalog/adapter.py`。

> ✅ **DP 端已接上受控主檔維護（#182）**：DP03「系統參數與清單」經
> `module_assign_registry` 呼叫 `list_controlled_kinds` / `list_controlled` /
> `create_controlled` / `rename_controlled` / `set_controlled_enabled`。

**通用值保護**：`IS_ALL=true` 之標籤（「全體」「全單位」）不可停用、不可改名（`ET_TAG_001`）。
此為 ET 業務規則，**伺服器端保護必須在 ET**——DP 端之 `is_builtin` 旗標與前端隱藏
僅為 UX，不可作為唯一防線。
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.core.module_assign import ControlledGroupView, ControlledItemView, ControlledKindView, SetEnabledResult
from app.et.catalog.models import TAG_TYPE_AUDIENCE, TAG_TYPE_UNIT, EtTag, EtUserTag
from app.services import AuditLogService

logger = logging.getLogger(__name__)

# 受控主檔「定義」維護之稽核碼，與角色 / 標籤「指派」（ET-ROLES）分開——
# 比照 DM 之 DM-CATALOG vs DM-ROLES，使稽核可依 FUNC_NAME 區分兩類管理行為。
_FUNC_NAME = "ET-CATALOG"
_MODULE = "ET"
_KIND_TAG = "TAG"
# DP 後台之區塊顯示名——名稱權威在模組，DP 不硬編碼模組語彙（#538 SA Q3：改名「受訓對象」）
_KIND_TAG_LABEL = "受訓對象"
# 維護頁「說明」欄：講掛上之後會發生什麼，不複述名稱
_KIND_TAG_DESCRIPTION = (
    "課程的受訓對象，以「單位 + 職位」成對設定。課程發布時依此自動把對應學員加入課程並寄發通知；"
    "學員身上的配對於「權限管理」指派。停用後不可再出現於新配對，既有配對不受影響。"
)
# 兩個分組（子分區）；單位在前，與 DM 可見對象的分區順序一致
_GROUPS = (
    ControlledGroupView(
        code=TAG_TYPE_UNIT,
        name="單位",
        description="配對的單位欄。「全單位」代表不限單位，僅能用於課程，不可停用或改名。",
    ),
    ControlledGroupView(
        code=TAG_TYPE_AUDIENCE,
        name="職位",
        description="配對的職位欄。「全體」代表不限職位，僅能用於課程，不可停用或改名。",
    ),
)
_GROUP_CODES = frozenset(g.code for g in _GROUPS)
_MAX_BIGINT = 9_223_372_036_854_775_807
# 對應 ET_TAG.TAG_NAME 之 VARCHAR(50)
_MAX_TAG_NAME_LEN = 50


def _normalise_tag_name(name: str) -> str:
    """標籤名稱正規化與驗證。

    `strip()` 是必要的——否則 `"軍人 "` 可繞過 `TAG_NAME` 唯一約束與重複檢查，
    建出視覺上重複的標籤。長度上限對應 `ET_TAG.TAG_NAME` 之 VARCHAR(50)，
    未擋會在 DB 層炸成 500。
    """
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > _MAX_TAG_NAME_LEN:
        raise AppError(status_code=422, detail="受訓對象標籤名稱不合法", error_code="ET_TAG_004")
    return cleaned


def _ensure_tag_kind(kind: str) -> None:
    """ET 僅有 `TAG` 一類受控主檔；其餘 kind 一律拒絕（fail-closed）。"""
    if kind != _KIND_TAG:
        raise AppError(status_code=404, detail="查無此受訓對象標籤或項目類別", error_code="ET_TAG_003")


_GENERIC_LOCKED_DETAIL = "「全體」「全單位」為系統內建通用值，不可停用或改名"


def _generic_locked() -> AppError:
    return AppError(status_code=422, detail=_GENERIC_LOCKED_DETAIL, error_code="ET_TAG_001")


def _view(t: EtTag) -> ControlledItemView:
    """`group_type` / `tag_group_code` 皆帶 `TAG_TYPE`——前者供 DP02 分維度，後者供 DP03 分區。"""
    return ControlledItemView(
        kind=_KIND_TAG,
        code=str(t.tag_id),
        name=t.tag_name,
        is_builtin=t.is_builtin,
        is_enabled=t.is_active,
        group_type=t.tag_type,
        tag_group_code=t.tag_type,
    )


class EtCatalogAdapter:
    """受訓對象標籤庫維護（供 DP 後台「系統參數與清單」呼叫）。"""

    def __init__(self, audit: AuditLogService | None = None) -> None:
        self._audit = audit or AuditLogService()

    async def list_controlled_kinds(self, db: AsyncSession) -> list[ControlledKindView]:
        """ET 可維護之受控主檔類別：僅受訓對象一類，分「單位」「職位」兩個子分組（#538）。

        靜態宣告、**不查 DB**（`db` 僅為符合 Protocol 簽章）。`requires_code=False`——
        `TAG_ID` 由 Identity 配號，使用者不需輸入代碼；DP 新增時把**所屬分組**當 `code` 傳入
        （比照 DM 標籤組）。
        """
        return [
            ControlledKindView(
                kind=_KIND_TAG,
                name=_KIND_TAG_LABEL,
                requires_code=False,
                description=_KIND_TAG_DESCRIPTION,
                groups=_GROUPS,
            )
        ]

    async def list_controlled(
        self, db: AsyncSession, kind: str, *, enabled_only: bool = False
    ) -> list[ControlledItemView]:
        """列出受訓對象標籤；`code` 為 `TAG_ID` 字串化、`is_builtin` 供 DP 決定操作入口。

        `tag_group_code` 帶 `TAG_TYPE`，DP 依此把項目放進「單位」或「職位」分區。
        """
        _ensure_tag_kind(kind)
        stmt = select(EtTag).where(EtTag.deleted == 0)
        if enabled_only:
            stmt = stmt.where(EtTag.is_active.is_(True))
        rows = await db.scalars(stmt.order_by(EtTag.tag_type, EtTag.display_order, EtTag.tag_id))
        return [_view(t) for t in rows.all()]

    async def list_audiences(self, db: AsyncSession, *, enabled_only: bool = True) -> list[ControlledItemView]:
        """權限管理之「受訓對象」可選清單——**單位與職位兩類**（#538）。

        `group_type` 帶 `TAG_TYPE`：DP02 前端以 `kind == "UNIT"` 判定走配對模式、分成兩個
        下拉（`RolesPage.isPairedModule`），不寫死模組。

        通用值（「全體」「全單位」）排除：它們是**課程端**「不限」的語意，人不會屬於它們
        （比照 DM）；`assign_service._validate_pairs` 另有伺服器端防線。
        """
        _ensure_tag_kind(_KIND_TAG)
        stmt = select(EtTag).where(EtTag.deleted == 0, EtTag.is_all.is_(False))
        if enabled_only:
            stmt = stmt.where(EtTag.is_active.is_(True))
        rows = await db.scalars(stmt.order_by(EtTag.tag_type.desc(), EtTag.display_order, EtTag.tag_id))
        return [_view(t) for t in rows.all()]

    async def create_controlled(self, db: AsyncSession, kind: str, *, code: str, name: str, operator_id: str) -> None:
        """新增受訓對象標籤。

        `code` 為**所屬分組**（`UNIT` / `AUDIENCE`，#538），由 DP 依分區傳入；**空白時為職位**
        ——#538 之前 ET 只有一類、`code` 一律忽略，既有呼叫端（含 DP 的「代碼可省略」契約）
        不帶 `code`，預設職位即與改版前行為相同。其餘值 404。
        `TAG_ID` 為 Identity 自動配號；標籤以 `TAG_NAME` 唯一識別（全表唯一，跨兩組）。
        新增之標籤 `IS_BUILTIN=false`、`IS_ALL=false`——通用值只有 seed 那兩筆。
        """
        _ensure_tag_kind(kind)
        code = code or TAG_TYPE_AUDIENCE
        if code not in _GROUP_CODES:
            raise AppError(status_code=404, detail="查無此受訓對象標籤或項目類別", error_code="ET_TAG_003")
        name = _normalise_tag_name(name)
        now = datetime.now(timezone.utc)
        exists = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name, EtTag.deleted == 0))
        if exists is not None:
            raise AppError(status_code=409, detail="受訓對象標籤名稱已存在", error_code="ET_TAG_002")

        max_order = await db.scalar(
            select(EtTag.display_order).where(EtTag.tag_type == code).order_by(EtTag.display_order.desc()).limit(1)
        )
        tag = EtTag(
            tag_name=name,
            tag_type=code,
            is_active=True,
            is_all=False,
            is_builtin=False,
            display_order=(max_order or 0) + 1,
            created_user=operator_id,
            created_date=now,
            deleted=0,
        )
        db.add(tag)
        await db.flush()
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="CREATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(tag.tag_id),
            description="新增受訓對象標籤",
            after_value={"tag_name": name, "tag_type": code},
        )

    async def rename_controlled(
        self, db: AsyncSession, kind: str, *, code: str, new_name: str, operator_id: str
    ) -> None:
        """標籤改名。**僅通用值（`IS_ALL`：「全體」「全單位」）不可改名**；其餘內建標籤可改名（代碼仍鎖定）。

        保護條件用 `is_all` 而非 `is_builtin`：種子 5 筆皆 `IS_BUILTIN=true`，以 `is_builtin`
        把關會使全部內建標籤都不能改名，逾越契約（`srv-et-dp-module-callbacks.md` §「全體」保護
        只保護 `IS_ALL`）。#182 定案 D2 統一 `is_builtin` 為「代碼鎖定、僅可改名」之全平台語意。
        """
        _ensure_tag_kind(kind)
        new_name = _normalise_tag_name(new_name)
        tag = await self._require_tag(db, code)
        if tag.is_all:
            raise _generic_locked()

        dup = await db.scalar(
            select(EtTag.tag_id).where(EtTag.tag_name == new_name, EtTag.tag_id != tag.tag_id, EtTag.deleted == 0)
        )
        if dup is not None:
            raise AppError(status_code=409, detail="受訓對象標籤名稱已存在", error_code="ET_TAG_002")

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
            description="受訓對象標籤改名",
            before_value={"tag_name": before},
            after_value={"tag_name": new_name},
        )

    async def set_controlled_enabled(
        self, db: AsyncSession, kind: str, *, code: str, enabled: bool, operator_id: str
    ) -> SetEnabledResult:
        """標籤啟用 / 停用（soft-retire，不刪除）。

        停用後**不可再掛至新課程**，已掛之既有課程與 `ET_COURSE_TAG` 不受影響
        （比照 DM AUDIENCE）。回傳受影響之使用者指派數供 DP 端提示。

        **通用值不可停用**——「全體」「全單位」代表不限，停用將使自動邀請機制失效。
        """
        _ensure_tag_kind(kind)
        tag = await self._require_tag(db, code)
        if not enabled and tag.is_all:
            raise _generic_locked()

        if tag.is_active == enabled:
            return SetEnabledResult()  # 無異動

        tag.is_active = enabled
        tag.updated_user = operator_id
        tag.updated_date = datetime.now(timezone.utc)
        await db.flush()

        # 單次 count 查詢（比照 dm/catalog/service.py 之 soft_retire_audience_tag）。
        # ⚠️ 兩欄都要算（#538）：單位放在 `UNIT_TAG_ID`，只比 `TAG_ID` 的話停用任何單位都恆回 0
        # ——#437 的 code review 在 DM 抓到同一個問題。
        affected_count = await db.scalar(
            select(func.count())
            .select_from(EtUserTag)
            .where(
                or_(EtUserTag.tag_id == tag.tag_id, EtUserTag.unit_tag_id == tag.tag_id),
                EtUserTag.deleted == 0,
            )
        )

        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=operator_id,
            target_id=str(tag.tag_id),
            description="受訓對象標籤啟用 / 停用",
            after_value={"is_active": enabled},
        )
        return SetEnabledResult(affected_viewers=affected_count)

    async def _require_tag(self, db: AsyncSession, code: str) -> EtTag:
        """依 `code`（TAG_ID 字串）取標籤；查無或格式錯誤一律 404。

        用 `isdecimal()` 而非 `isdigit()`——後者對 Unicode 數字字元（`²` / `①`）回 True
        但 `int()` 會拋 ValueError，形成未攔截的 500。並加 BIGINT 界限。
        """
        if not (code.isdecimal() and len(code) <= 19 and 0 < int(code) <= _MAX_BIGINT):
            raise AppError(status_code=404, detail="查無此受訓對象標籤或項目類別", error_code="ET_TAG_003")
        tag = await db.scalar(select(EtTag).where(EtTag.tag_id == int(code), EtTag.deleted == 0))
        if tag is None:
            raise AppError(status_code=404, detail="查無此受訓對象標籤或項目類別", error_code="ET_TAG_003")
        return tag
