"""標籤式可見性判定（T020a）。

回傳可 AND 進 DM_DOCUMENT 查詢的可見性條件：
- 編輯者 / 審核者 / 管理者：不過濾（回 None，見全部）
- 閱覽者：文件掛「全體」 OR（文件 DM_DOC_TAG 之 AUDIENCE 標籤 ∩ 使用者 DM_USER_TAG ≠ 空）

後端 API 亦套此過濾（防繞過 UI），對應 spec_us3 FR-008 / research §5b。

⚠️ 契約：本條件**僅**處理 AUDIENCE 標籤可見性，不含文件狀態（STATUS）。呼叫端對閱覽者
（VIEWER）**必須另外 AND `DM_DOCUMENT.STATUS = 'PUBLISHED'`**，否則閱覽者將看見草稿 / 未發布
文件（US3 查詢端點須含此過濾並附測試）。編輯者 / 審核者 / 管理者回 None 不過濾，其可見範圍由端點自訂。
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.sql import exists

from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocTag, DmDocument
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER

_AUDIENCE_GROUP = "AUDIENCE"
_ALL_AUDIENCE_TAG = "全體"
_UNFILTERED_ROLES = frozenset({DM_ADMIN, DM_EDITOR, DM_REVIEWER})


def visible_docs_condition(user_id: str, roles: Iterable[str]) -> ColumnElement[bool] | None:
    """回傳套用於 DM_DOCUMENT 之可見性條件。

    Args:
        user_id: 目前使用者。
        roles: 使用者之 DM 角色集。

    Returns:
        SQLAlchemy 布林條件（AND 進文件查詢）；若具編輯者 / 審核者 / 管理者角色則回 None（不過濾）。
    """
    if set(roles) & _UNFILTERED_ROLES:
        return None

    # 僅計有效授權 / 有效文件標籤（DELETED=0）：撤銷之可見對象授權、移除之文件標籤皆不再賦予可見性。
    user_audience_tags = select(DmUserTag.tag_id).where(DmUserTag.user_id == user_id, DmUserTag.deleted == 0)
    return exists(
        select(1)
        .select_from(DmDocTag)
        .join(DmTag, DmDocTag.tag_id == DmTag.tag_id)
        .where(
            DmDocTag.doc_id == DmDocument.doc_id,
            DmDocTag.deleted == 0,
            DmTag.tag_group_code == _AUDIENCE_GROUP,
            or_(DmTag.tag_name == _ALL_AUDIENCE_TAG, DmTag.tag_id.in_(user_audience_tags)),
        )
    )
