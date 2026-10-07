"""受訓對象 `(單位, 職位)` 配對（#538，比照 DM #437）。

## 判定規則

```
課程配對 (cu, cp) 涵蓋使用者配對 (uu, up)  ⟺  (cu 為全單位 OR cu = uu) AND (cp 為全體 OR cp = up)
```

`uu` 為 NULL（單位未指定）時 `cu = uu` 自然為 false，故只匹配課程端的「全單位」——這就是
#538 導入前既有指派的向後相容依據，不需另外處理 NULL。

課程配對為 `(全單位, 全體)` 時代表**全部具學員角色者**，含身上沒有任何配對的人；那一支不經
本模組，由呼叫端展開（見 `enrollment/tag_invite.py`）。

## ⭐ 通用值以 `IS_ALL` 判定，不以名稱判定

DM 以 `TAG_NAME` 辨識「全單位」/「全體」，把某個具體單位改名為「全單位」即等於擴權（#437
follow-up 1，DM 以名稱唯一約束先擋住）。ET 本來就有 `IS_ALL` 旗標，判定一律看它。

## 🔴 為何用明確的 JOIN，不用巢狀 EXISTS

DM 的 `audience_pair_match` 是巢狀 `EXISTS`，在「由文件找人」的方向上曾因關聯（correlation）
失效而退化成「只要**存在任何人**相符即為真」——所有人都通過（#437 差異 3）。**ET 的主路徑
（由課程找要帶入的人）正是那個方向**，而 ET 判錯的後果是把人加進課程並寄出通知信。

本模組把課程配對、兩個標籤、使用者配對以 JOIN 串成一張「(課程, 使用者) 相符表」，不依賴
子查詢的關聯推斷。⚠️ 改寫成 `EXISTS` 之前，先讀 `test_et_tag_invite.py` 的反向探針測試。
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, Select, and_, false, not_, or_, select
from sqlalchemy.orm import aliased

from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag

Pair = tuple[int | None, int]
"""`(單位 TAG_ID, 職位 TAG_ID)`；單位為 None 表示未指定（僅使用者端可能出現）。"""

_SEP = ":"


def encode_pair(unit_tag_id: int | None, tag_id: int) -> str:
    """配對編為 `"{單位}:{職位}"`；單位未指定時為 `":{職位}"`。

    格式與 DM（`dm/roles/assign_service.encode_pair`）相同——DP02 權限管理的前端以同一組
    `encodeAudiencePair` / `decodeAudiencePair` 處理兩個模組。
    """
    return f"{'' if unit_tag_id is None else unit_tag_id}{_SEP}{tag_id}"


def decode_pair(value: str) -> Pair | None:
    """解析 `"{單位}:{職位}"`；格式不合法時回 None（由呼叫端決定錯誤碼）。

    職位必填、單位可空；兩者皆須為正整數（`isdecimal` 而非 `isdigit`——後者對 Unicode
    數字如「²」回 True，`int()` 會拋未攔截的 500，#437 security review MEDIUM）。
    """
    unit_str, sep, role_str = value.partition(_SEP)
    if not sep or not _is_positive_id(role_str):
        return None
    if unit_str and not _is_positive_id(unit_str):
        return None
    return (int(unit_str) if unit_str else None), int(role_str)


def _is_positive_id(value: str) -> bool:
    # 先限長度再 int()：Python 對超過 4300 位的十進位字串 int() 會拋 ValueError（未攔截即 500，
    # security review LOW）。BIGINT 最多 19 位；上界另比——超出時 int() 雖不炸，送進 DB 會變成 500
    return value.isdecimal() and len(value) <= 19 and 0 < int(value) <= 9_223_372_036_854_775_807


def pair_in(unit_col, role_col, pairs: Iterable[Pair]) -> ColumnElement[bool]:
    """「(單位欄, 職位欄) 屬於 `pairs` 之一」——單位為 None 時以 `IS NULL` 比對。

    不用 `tuple_(...).in_(...)`：SQL 的 `(x, NULL) IN (...)` 永遠不為真，單位未指定的
    配對會靜默比對不到。
    """
    conds = [and_(unit_col.is_(None) if unit is None else unit_col == unit, role_col == role) for unit, role in pairs]
    return or_(*conds) if conds else false()


def matched_course_users() -> tuple[Select, object, object]:
    """「課程配對 × 使用者配對」中**相符**者：`SELECT 課程 ID, 使用者 ID`。

    呼叫端再以 `.where(...)` 限定課程端或使用者端（例如只看某門課、只看某人新增的配對）。

    Returns:
        `(stmt, unit_tag, role_tag)`——後兩者為課程配對的單位 / 職位標籤別名，供呼叫端組
        WHERE 條件（課程配對與使用者配對直接以 `EtCourseTag` / `EtUserTag` 引用）。

    ⚠️ **不含**「課程配對為 `(全單位, 全體)` → 全部學員」那一支（身上沒有任何配對的人也算），
    也**不含**學員角色過濾——兩者由呼叫端處理。
    """
    unit_tag = aliased(EtTag, name="et_unit_tag")
    role_tag = aliased(EtTag, name="et_role_tag")
    stmt = (
        select(EtCourseTag.course_id, EtUserTag.user_id)
        .select_from(EtCourseTag)
        # 濾已刪除之標籤——與卡片顯示（`pairs_by_course`）一致：看不到的配對不得繼續帶人
        .join(unit_tag, and_(unit_tag.tag_id == EtCourseTag.unit_tag_id, unit_tag.deleted == 0))
        .join(role_tag, and_(role_tag.tag_id == EtCourseTag.tag_id, role_tag.deleted == 0))
        .join(
            EtUserTag,
            and_(
                EtUserTag.deleted == 0,
                or_(unit_tag.is_all.is_(True), EtUserTag.unit_tag_id == EtCourseTag.unit_tag_id),
                or_(role_tag.is_all.is_(True), EtUserTag.tag_id == EtCourseTag.tag_id),
            ),
        )
        .where(EtCourseTag.deleted == 0)
        .distinct()
    )
    return stmt, unit_tag, role_tag


def is_universal(unit_tag, role_tag) -> ColumnElement[bool]:
    """課程配對為 `(全單位, 全體)`——代表全部具學員角色者。"""
    return and_(unit_tag.is_all.is_(True), role_tag.is_all.is_(True))


def not_universal(unit_tag, role_tag) -> ColumnElement[bool]:
    return not_(is_universal(unit_tag, role_tag))


def pair_label(*, unit_name: str, unit_is_all: bool, role_name: str) -> str:
    """配對的顯示文字——卡片 badge、唯讀模式、我的課程共用這一份。

    | 配對 | 顯示 |
    |---|---|
    | (全單位, 全體) | 全體 |
    | (全單位, 護理師) | 護理師 |
    | (松山分院, 護理師) | 松山分院 + 護理師 |
    | (松山分院, 全體) | 松山分院 + 全體 |

    「全單位」省略：#538 之前所有課程都只有職位，回填後全部是 `(全單位, X)`，省略之後
    卡片看起來與改版前相同。`(全單位, 全體)` 不需特判——職位名稱本身就是「全體」。
    """
    if unit_is_all:
        return role_name
    return f"{unit_name} + {role_name}"
