"""受訓對象配對的測試資料 helper（#538）。

#538 起課程配對的單位欄 NOT NULL，所有直接建 `EtCourseTag` 的測試都要帶單位。「不限單位」
用 migration seed 的「全單位」，以 `IS_ALL` 查出——不以名稱查，與正式判定同一個依據。
"""

from sqlalchemy import select

from app.core.utils import utcnow
from app.et.catalog.models import TAG_TYPE_AUDIENCE, TAG_TYPE_UNIT, EtCourseTag, EtTag, EtUserTag


async def all_units_id(db) -> int:
    """單位通用值「全單位」的 `TAG_ID`（migration seed）。"""
    return await db.scalar(select(EtTag.tag_id).where(EtTag.tag_type == TAG_TYPE_UNIT, EtTag.is_all.is_(True)))


async def all_roles_id(db) -> int:
    """職位通用值「全體」的 `TAG_ID`（migration seed）。"""
    return await db.scalar(select(EtTag.tag_id).where(EtTag.tag_type == TAG_TYPE_AUDIENCE, EtTag.is_all.is_(True)))


async def tag_id(db, name: str) -> int:
    """依名稱取 seed 之標籤 `TAG_ID`（`TAG_NAME` 全表唯一）。"""
    found = await db.scalar(select(EtTag.tag_id).where(EtTag.tag_name == name))
    assert found is not None, f"seed 中找不到標籤：{name}"
    return found


async def new_tag(db, name: str, *, tag_type: str = TAG_TYPE_AUDIENCE, is_active: bool = True) -> int:
    """新增一筆非通用值標籤。"""
    tag = EtTag(
        tag_name=name,
        tag_type=tag_type,
        is_active=is_active,
        is_all=False,
        is_builtin=False,
        created_user="SYSTEM",
        created_date=utcnow(),
        deleted=0,
    )
    db.add(tag)
    await db.flush()
    return tag.tag_id


async def pair_course(db, course_id: int, role_id: int, unit_id: int | None = None) -> None:
    """課程掛一組配對；`unit_id` 省略時為「全單位」（即 #538 之前「只掛職位」的語意）。"""
    db.add(
        EtCourseTag(
            course_id=course_id,
            tag_id=role_id,
            unit_tag_id=unit_id if unit_id is not None else await all_units_id(db),
            created_user="SYSTEM",
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


async def pair_user(db, user_id: str, role_id: int, unit_id: int | None = None) -> None:
    """使用者掛一組配對；`unit_id` 省略時為**單位未指定**（NULL）——與課程端的預設刻意不同。"""
    db.add(
        EtUserTag(
            user_id=user_id,
            tag_id=role_id,
            unit_tag_id=unit_id,
            created_user="SYSTEM",
            created_date=utcnow(),
            deleted=0,
        )
    )
    await db.flush()


def audiences_req(detail: dict) -> list[dict]:
    """課程詳細的 `audiences` → 請求格式（去掉回應才有的 `label`；請求 schema 為 `extra="forbid"`）。"""
    return [{"unit_tag_id": a["unit_tag_id"], "tag_id": a["tag_id"]} for a in detail["audiences"]]


async def role_pair(db, role_id: int) -> dict:
    """`(全單位, 職位)` 的請求格式——#538 之前「只掛這個職位」的同義寫法。"""
    return {"unit_tag_id": await all_units_id(db), "tag_id": role_id}
