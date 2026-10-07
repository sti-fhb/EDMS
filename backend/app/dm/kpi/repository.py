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
from sqlalchemy.orm import aliased

from app.core.like_escape import LIKE_ESCAPE_CHAR, contains
from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmCategory, DmTag
from app.dm.document.models import DmDocRead, DmDocTag, DmDocument, DmDocVersion
from app.dm.roles.authz import DM_ADMIN, DM_VIEWER
from app.dm.roles.models import DmUserRole
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外）

_AUDIENCE_GROUP = "AUDIENCE"
_ALL_AUDIENCE_TAG = "全體"
_UNIT_GROUP = "UNIT"  # 可見對象之單位維度（#437）
_ALL_UNITS_TAG = "全單位"
_ACTIVE = "ACTIVE"  # DP_USER.STATUS：ACTIVE / DISABLED（停用）；停用者無法登入閱讀（auth 擋），不列入 KPI
_PUBLISHED = "PUBLISHED"
_PENDING_OBSOLETE = "PENDING_OBSOLETE"
# 在架（對外有效、閱覽者仍在下載）＝已發布 + 廢止待簽核（對齊 dashboard `_LIVE_STATUSES`）；
# PENDING_OBSOLETE 文件仍可被下載並寫入 DM_DOC_READ（見 detail.write_read），故其閱讀落實度應納入 KPI。
# OBSOLETE（已下架）/ 送審 / 草稿 / SUPERSEDED（舊版）不計。
_LIVE_STATUSES = (_PUBLISHED, _PENDING_OBSOLETE)
_TRAINING = "TRAINING"


def audience_label(unit_name: str, role_name: str) -> str:
    """可見對象組名（#567 A）：通用值不入名稱。

    「全體」（全系統）／職位名（不限單位）／「單位．職位」。分隔用全形句點以免與單位名
    本身的連字號混淆——實測最長單位名 18 字（「國防醫學院三軍總醫院松山分院捐血站」）。
    """
    unit_general = unit_name == _ALL_UNITS_TAG
    role_general = role_name == _ALL_AUDIENCE_TAG
    if unit_general and role_general:
        return _ALL_AUDIENCE_TAG
    if unit_general:
        return role_name
    if role_general:
        return f"{unit_name}．{_ALL_AUDIENCE_TAG}"
    return f"{unit_name}．{role_name}"


class KpiRepository:
    """KPI 計算所需之集合式唯讀查詢。"""

    def published_docs_select(
        self, *, keyword: str | None, category: str | None, only_training: bool = False
    ) -> Select:
        """在架文件（母體：STATUS ∈ PUBLISHED / PENDING_OBSOLETE 且有目前發布版）+ 分類名 / 版本號。

        依文件名排序（穩定、可預期）；keyword 比對文件名、category 比對分類碼。

        `only_training` 切出兩個互斥母體（#567 B）：預設排除 TRAINING（閱讀統計母體），
        `True` 則只取 TRAINING（訓練教材區，不計閱讀率）。

        ⚠️ **按分類切，不是按「有沒有可見對象」切。** 理由是 ET 代學員取檔刻意不寫
        `DM_DOC_READ`（`app/et/common/dm_client.py` D-2），所以 TRAINING 的閱讀率在結構上
        保證低報——這與該文件當下有沒有掛可見對象無關。用「無可見對象」當判準會把一個
        結構性事實綁在可變的資料狀態上，且漏掉 #377 之前建立、仍帶著可見對象的既有教材。
        """
        conds = [
            DmDocument.status.in_(_LIVE_STATUSES),
            DmDocument.current_version_id.isnot(None),
            DmDocument.category_code == _TRAINING if only_training else DmDocument.category_code != _TRAINING,
        ]
        if keyword:
            conds.append(DmDocument.doc_name.ilike(contains(keyword), escape=LIKE_ESCAPE_CHAR))
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

    async def list_published_docs(
        self, db: AsyncSession, *, keyword: str | None, category: str | None, only_training: bool = False
    ) -> list[Row]:
        stmt = self.published_docs_select(keyword=keyword, category=category, only_training=only_training)
        return list((await db.execute(stmt)).all())

    async def viewer_ids(self, db: AsyncSession) -> set[str]:
        """具 DM_VIEWER 角色且帳號有效（未刪除、未停用）之使用者集（應看母體）。

        join DP_USER 並過濾 DELETED=0 且 STATUS='ACTIVE'：已刪除 / 已停用之帳號無法登入閱讀，不列入應看
        分母（與 admin_emails / viewer_profiles 一致，避免停用帳號永久拉低閱讀率）。SA 裁示：純 EDITOR/ADMIN
        無 VIEWER 不計。
        """
        rows = await db.scalars(
            select(DmUserRole.user_id)
            .join(DpUser, DmUserRole.user_id == DpUser.user_id)
            .where(
                DmUserRole.role_code == DM_VIEWER,
                DmUserRole.deleted == 0,
                DpUser.deleted == 0,
                DpUser.status == _ACTIVE,
            )
            .distinct()
        )
        return set(rows.all())

    async def viewer_audience_tags(
        self, db: AsyncSession, viewer_ids: Iterable[str]
    ) -> dict[str, set[tuple[int | None, int]]]:
        """各閱覽者之有效 (單位, 職位) 授權配對（DELETED=0）；無授權者不出現於回傳（視為空集）。

        單位為 `None` 代表**未指定**（#437 導入配對前之既有授權），僅能匹配文件側之「全單位」——
        與 `visibility.audience_pair_match` 之 NULL 語意一致。人側不會持有通用值（`list_audiences`
        已排除「全體」/「全單位」，那是文件端語意）。
        """
        ids = list(viewer_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DmUserTag.user_id, DmUserTag.tag_id, DmUserTag.unit_tag_id)
            .join(DmTag, DmUserTag.tag_id == DmTag.tag_id)
            .where(
                DmUserTag.user_id.in_(ids),
                DmUserTag.deleted == 0,
                DmTag.tag_group_code == _AUDIENCE_GROUP,
            )
        )
        result: dict[str, set[tuple[int | None, int]]] = {}
        for user_id, tag_id, unit_tag_id in rows.all():
            result.setdefault(user_id, set()).add((unit_tag_id, tag_id))
        return result

    async def viewer_profiles(self, db: AsyncSession, viewer_ids: Iterable[str]) -> dict[str, Row]:
        """各閱覽者之 email / 姓名（未讀提醒收件用）；查無 / 已刪除者不出現。"""
        ids = list(viewer_ids)
        if not ids:
            return {}
        rows = await db.execute(
            select(DpUser.user_id, DpUser.email, DpUser.user_name).where(
                DpUser.user_id.in_(ids), DpUser.deleted == 0, DpUser.status == _ACTIVE
            )
        )
        return {r.user_id: r for r in rows.all()}

    async def doc_audience(
        self, db: AsyncSession, doc_ids: Iterable[str]
    ) -> dict[str, dict[tuple[int | None, int | None], str]]:
        """各文件之有效可見對象 (單位, 職位) 配對 → **組名**。

        **通用值一律正規化為 `None`**（單位「全單位」／職位「全體」），使比對端只需判斷 `is None`
        而不必再查那兩個標籤的 ID：`(None, None)` 即全系統可見。配對不完整者（`UNIT_TAG_ID IS NULL`）
        **略過**——其於 `visibility.audience_pair_match` 不賦予任何可見性，計入會灌大應看母體。

        回傳 `dict` 而非 `set`（#567 A）：值為顯示用組名，供 DM06 呈現逐組完成度。**迭代 dict
        取得的即配對本身**，故既有的 `_pair_visible` 迴圈不受影響。名稱在原查詢中本就取出，
        先前只用來判斷是不是通用值、取完即丟。
        """
        ids = list(doc_ids)
        if not ids:
            return {}
        unit_tag = aliased(DmTag, name="dm_unit_tag")
        rows = await db.execute(
            select(DmDocTag.doc_id, DmDocTag.tag_id, DmTag.tag_name, DmDocTag.unit_tag_id, unit_tag.tag_name)
            .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
            .join(unit_tag, DmDocTag.unit_tag_id == unit_tag.tag_id)
            .where(
                DmDocTag.doc_id.in_(ids),
                DmDocTag.deleted == 0,
                DmTag.tag_group_code == _AUDIENCE_GROUP,
                unit_tag.tag_group_code == _UNIT_GROUP,
            )
        )
        result: dict[str, dict[tuple[int | None, int | None], str]] = {}
        for doc_id, tag_id, tag_name, unit_tag_id, unit_name in rows.all():
            unit = None if unit_name == _ALL_UNITS_TAG else unit_tag_id
            role = None if tag_name == _ALL_AUDIENCE_TAG else tag_id
            result.setdefault(doc_id, {})[(unit, role)] = audience_label(unit_name, tag_name)
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
            .where(
                DmUserRole.deleted == 0,
                DpUser.deleted == 0,
                DpUser.status == _ACTIVE,
                DpUser.email.isnot(None),
            )
            .distinct()
        )
        return sorted({e for e in rows.all() if e})
