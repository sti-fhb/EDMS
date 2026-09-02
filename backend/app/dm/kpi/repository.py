"""閱讀統計 KPI 資料存取（US13，唯讀）。

提供 KPI 計算所需之數個集合式查詢（避免逐文件 N+1、亦不用脆弱的相關子查詢）；
「應看 / 已看」之交集與計數於 service 層以 Python 集合運算完成（母體與交集邏輯集中、易測）。

跨模組 join `DP_USER`（收件 email / 姓名）為唯讀查詢例外（sti-backend-boundaries §報表/查詢：僅 SELECT）。
「應看」母體＝具 `DM_VIEWER` 角色之使用者（SA 裁示 2026-09-02，spec_us13 FR-003），audience 比對語意
反向於 `dm/document/visibility`（該處為「使用者能看哪些文件」；此處為「文件能被誰看見」，比照
`review/repository.recipient_emails`）。
"""

from collections.abc import Iterable

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmTag
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

_AUDIENCE_GROUP = "AUDIENCE"
_ALL_AUDIENCE_TAG = "全體"
_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
# 在架（對外有效、閱覽者仍在下載）＝已發布 + 廢止待簽核（對齊 dashboard `_LIVE_STATUSES`）；
# PENDING_OBSOLETE 文件仍可被下載並寫入 DM_DOC_READ（見 detail.write_read），故其閱讀落實度應納入 KPI。
# OBSOLETE（已下架）/ 送審 / 草稿 / SUPERSEDED（舊版）不計。
_LIVE_STATUSES = (_PUBLISHED, _PENDING_OBSOLETE)


class KpiRepository:
    """KPI 計算所需之集合式唯讀查詢。"""

    def published_docs_select(self, *, keyword: str | None, category: str | None) -> Select:
        """在架文件（母體：STATUS ∈ PUBLISHED / PENDING_OBSOLETE 且有目前發布版）+ 分類名 / 版本號。

        依文件名排序（穩定、可預期）；keyword 比對文件名、category 比對分類碼。
        """
        conds = [DmDocument.status.in_(_LIVE_STATUSES), DmDocument.current_version_id.isnot(None)]
        if keyword:
            conds.append(DmDocument.doc_name.ilike(f"%{keyword}%"))
        if category:
            conds.append(DmDocument.category_code == category)
        return (
            select(
                DmDocument.doc_id,
                DmDocument.doc_name,
                DmDocument.category_code,
                DmCategory.category_name,
                DmDocument.current_version_id,
                DmDocVersion.version_no.label("current_version_no"),
            )
            .select_from(DmDocument)
            .outerjoin(DmCategory, DmDocument.category_code == DmCategory.category_code)
            .outerjoin(DmDocVersion, DmDocument.current_version_id == DmDocVersion.version_id)
            .where(*conds)
            .order_by(DmDocument.doc_name.asc(), DmDocument.doc_id.asc())
        )

    async def list_published_docs(self, db: AsyncSession, *, keyword: str | None, category: str | None) -> list[Row]:
        return list((await db.execute(self.published_docs_select(keyword=keyword, category=category))).all())

    async def viewer_ids(self, db: AsyncSession) -> set[str]:
        """具 DM_VIEWER 角色且帳號有效之使用者集（應看母體；SA 裁示：純 EDITOR/ADMIN 無 VIEWER 不計）。

        join DP_USER 並過濾 DELETED=0：停用 / 刪除之帳號不列入應看分母（與 admin_emails / viewer_profiles 一致，
        避免帳號停用但角色列未同步移除時永久拉低閱讀率）。
        """
        rows = await db.scalars(
            select(DmUserRole.user_id)
            .join(DpUser, DmUserRole.user_id == DpUser.user_id)
            .where(DmUserRole.role_code == DM_VIEWER, DmUserRole.deleted == 0, DpUser.deleted == 0)
            .distinct()
        )
        return set(rows.all())

    async def viewer_audience_tags(self, db: AsyncSession, viewer_ids: Iterable[str]) -> dict[str, set[int]]:
        """各閱覽者之有效 AUDIENCE 授權標籤集（DELETED=0）；無授權者不出現於回傳（視為空集）。"""
        ids = list(viewer_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DmUserTag.user_id, DmUserTag.tag_id)
            .join(DmTag, DmUserTag.tag_id == DmTag.tag_id)
            .where(
                DmUserTag.user_id.in_(ids),
                DmUserTag.deleted == 0,
                DmTag.tag_group_code == _AUDIENCE_GROUP,
            )
        )
        result: dict[str, set[int]] = {}
        for user_id, tag_id in rows.all():
            result.setdefault(user_id, set()).add(tag_id)
        return result

    async def viewer_profiles(self, db: AsyncSession, viewer_ids: Iterable[str]) -> dict[str, Row]:
        """各閱覽者之 email / 姓名（未讀提醒收件用）；查無 / 已刪除者不出現。"""
        ids = list(viewer_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DpUser.user_id, DpUser.email, DpUser.user_name).where(DpUser.user_id.in_(ids), DpUser.deleted == 0)
        )
        return {r.user_id: r for r in rows.all()}

    async def doc_audience(self, db: AsyncSession, doc_ids: Iterable[str]) -> dict[str, tuple[set[int], bool]]:
        """各文件之有效 AUDIENCE 標籤集 + 是否掛「全體」。"""
        ids = list(doc_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DmDocTag.doc_id, DmDocTag.tag_id, DmTag.tag_name)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .where(
                DmDocTag.doc_id.in_(ids),
                DmDocTag.deleted == 0,
                DmTag.tag_group_code == _AUDIENCE_GROUP,
            )
        )
        result: dict[str, tuple[set[int], bool]] = {}
        for doc_id, tag_id, tag_name in rows.all():
            tags, has_all = result.get(doc_id, (set(), False))
            tags.add(tag_id)
            result[doc_id] = (tags, has_all or tag_name == _ALL_AUDIENCE_TAG)
        return result

    async def reads_current(self, db: AsyncSession, doc_ids: Iterable[str]) -> dict[str, set[str]]:
        """各文件「目前發布版」之 distinct 下載者（已看候選；發新版後舊版下載者天然不計）。"""
        ids = list(doc_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DmDocRead.doc_id, DmDocRead.created_user)
            .join(
                DmDocument,
                (DmDocRead.doc_id == DmDocument.doc_id) & (DmDocRead.version_id == DmDocument.current_version_id),
            )
            .where(DmDocRead.doc_id.in_(ids))
            .distinct()
        )
        result: dict[str, set[str]] = {}
        for doc_id, user_id in rows.all():
            result.setdefault(doc_id, set()).add(user_id)
        return result

    async def admin_emails(self, db: AsyncSession) -> list[str]:
        """全部具 DM_ADMIN 角色且有 email 之使用者 email（KPI 週報收件）。去重、排序。"""
        rows = await db.scalars(
            select(DpUser.email)
            .join(DmUserRole, (DmUserRole.user_id == DpUser.user_id) & (DmUserRole.role_code == DM_ADMIN))
            .where(DmUserRole.deleted == 0, DpUser.deleted == 0, DpUser.email.isnot(None))
            .distinct()
        )
        return sorted({e for e in rows.all() if e})
