"""標籤式可見性判定（T020a；配對語意見 #437）。

回傳可 AND 進 DM_DOCUMENT 查詢的可見性條件：
- 編輯者 / 審核者 / 管理者：不過濾（回 None，見全部）
- 閱覽者：文件之可見對象 (單位, 職位) 配對與其授權配對相符者

可見對象為**配對清單**而非兩個獨立集合（#437）：文件掛 [(軍醫局, 護理師), (三總, 行政人員)]
意為「僅此兩種人」，不含「軍醫局的行政人員」與「三總的護理師」。故比對必須以**整組配對**
進行——拆成「單位集 ∧ 職位集」會讓持有 [(松山, 護理師), (三總, 行政)] 的使用者誤見
(松山, 行政) 之文件。

後端 API 亦套此過濾（防繞過 UI），對應 spec_us3 FR-008 / research §5b。

⚠️ 契約：本條件**僅**處理可見對象配對，不含文件狀態（STATUS）。呼叫端對閱覽者（VIEWER）
**必須另外 AND `DM_DOCUMENT.STATUS = 'PUBLISHED'`**，否則閱覽者將看見草稿 / 未發布文件
（US3 查詢端點須含此過濾並附測試）。編輯者 / 審核者 / 管理者回 None 不過濾，其可見範圍由端點自訂。
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import exists

from app.dm.audience.models import DmUserTag
from app.dm.catalog.models import DmTag
from app.dm.document.models import DmDocTag, DmDocument
from app.dm.roles.authz import DM_ADMIN, DM_EDITOR, DM_REVIEWER

_AUDIENCE_GROUP = "AUDIENCE"
_UNIT_GROUP = "UNIT"
_ALL_AUDIENCE_TAG = "全體"
_ALL_UNITS_TAG = "全單位"
_UNFILTERED_ROLES = frozenset({DM_ADMIN, DM_EDITOR, DM_REVIEWER})


def is_privileged(roles: Iterable[str]) -> bool:
    """是否具編輯 / 審核 / 管理者角色（不受可見性與未發布內容限制）。

    純閱覽者回 False——其可見範圍受 `visible_docs_condition` 過濾，且不得見未發布之文件 / 版本。
    """
    return bool(set(roles) & _UNFILTERED_ROLES)


def audience_pair_match(*, doc_id, user_id) -> ColumnElement[bool]:
    """(單位, 職位) 配對匹配條件——**文件端與使用者端皆以參數傳入，故可雙向使用**。

    兩個呼叫方向共用本條件，不各寫一份：

    - 「這個人能看哪些文件」：`doc_id=DmDocument.doc_id`（欄位）、`user_id="U1"`（定值）
    - 「這份文件能被誰看見」：`doc_id="DM-SOP-000001"`（定值）、`user_id=DpUser.user_id`（欄位）

    ⚠️ **為何必須共用**：#437 之前兩邊各寫一份，發布通知的收件名單（`review/repository.py`
    之 `recipient_emails`）雖於 docstring 自稱「反向於 `visible_docs_condition`」，卻在可見性
    改為配對後沒跟著改——文件開給「三總的護理師」時，**所有單位的護理師**都會收到含文件名稱的
    通知，且不會有任何測試變紅。兩個方向只要還是兩份程式碼，這種 drift 就會再發生。

    判定規則見 `visible_docs_condition` 之 docstring。

    Args:
        doc_id: 文件識別——欄位（如 `DmDocument.doc_id`）或定值字串。
        user_id: 使用者識別——欄位（如 `DpUser.user_id`）或定值字串。

    Returns:
        可 AND 進查詢之布林條件。
    """
    unit_tag = aliased(DmTag, name="dm_unit_tag")
    # 僅計有效授權 / 有效文件標籤（DELETED=0）：撤銷之授權、移除之文件標籤皆不再賦予可見性。
    matching_user_pair = exists(
        select(1)
        .select_from(DmUserTag)
        .where(
            DmUserTag.user_id == user_id,
            DmUserTag.deleted == 0,
            or_(DmTag.tag_name == _ALL_AUDIENCE_TAG, DmUserTag.tag_id == DmDocTag.tag_id),
            or_(unit_tag.tag_name == _ALL_UNITS_TAG, DmUserTag.unit_tag_id == DmDocTag.unit_tag_id),
        )
        # ⚠️ 必須明示關聯：`user_id` 為外層欄位時（「此文件能被誰看見」方向），SQLAlchemy 會把該
        # 外層表也拉進本子查詢的 FROM，條件退化為「只要**存在任何人**有相符授權即為真」——所有
        # 閱覽者都會通過。`user_id` 為定值時不會發生，故單測另一個方向驗不出來。
        .correlate_except(DmUserTag)
    )
    return exists(
        select(1)
        .select_from(DmDocTag)
        .join(DmTag, and_(DmDocTag.tag_id == DmTag.tag_id, DmTag.tag_group_code == _AUDIENCE_GROUP))
        .join(unit_tag, and_(DmDocTag.unit_tag_id == unit_tag.tag_id, unit_tag.tag_group_code == _UNIT_GROUP))
        .where(
            DmDocTag.doc_id == doc_id,
            DmDocTag.deleted == 0,
            or_(
                and_(unit_tag.tag_name == _ALL_UNITS_TAG, DmTag.tag_name == _ALL_AUDIENCE_TAG),
                matching_user_pair,
            ),
        )
        .correlate_except(DmDocTag, DmTag, unit_tag)  # 同上：`doc_id` 為外層欄位時亦須明示
    )


def visible_docs_condition(user_id: str, roles: Iterable[str]) -> ColumnElement[bool] | None:
    """回傳套用於 DM_DOCUMENT 之可見性條件。

    判定規則（#437）::

        可見 ⟺ ∃ 文件配對 (du, dp) 使得
                (du = 「全單位」 AND dp = 「全體」)                      -- 全系統，不需任何授權
                OR ∃ 使用者配對 (uu, up):
                     (du = 「全單位」 OR du = uu) AND (dp = 「全體」 OR up = dp)

    第一項不可省：未授予任何配對之閱覽者，其「∃ 使用者配對」恆假，少了這項連全系統公開文件
    都看不到——那是對導入單位維度前之行為的迴歸。

    NULL 的處理由 SQL 語意自然達成，不需額外條件：
    - 文件側 `UNIT_TAG_ID IS NULL`（配對不完整）→ INNER JOIN 排除，該列不賦予任何可見性
    - 人側 `UNIT_TAG_ID IS NULL`（單位未指定，導入前之既有授權）→ `du = uu` 為 NULL 即 false，
      故僅能匹配 `du =「全單位」` 之文件；此即既有授權可見範圍不變之依據

    Args:
        user_id: 目前使用者。
        roles: 使用者之 DM 角色集。

    Returns:
        SQLAlchemy 布林條件（AND 進文件查詢）；若具編輯者 / 審核者 / 管理者角色則回 None（不過濾）。
    """
    if set(roles) & _UNFILTERED_ROLES:
        return None
    return audience_pair_match(doc_id=DmDocument.doc_id, user_id=user_id)
