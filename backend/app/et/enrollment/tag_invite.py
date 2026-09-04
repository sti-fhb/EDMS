"""發布課程時依受訓單位標籤自動帶入學員（US3 FR-ET-US3-12 前半 / #247 追加）。

## 為何在 #247 補這一段

`ET-8`（標籤帶入 / Email 邀請 / 寄通知信）尚未實作，#204 在 `publish_service` 留了
接點但沒實作。實測時發現：課程發布並掛了「護理師」標籤，具該標籤的學員卻沒有被帶
進課程——教師只能把 8 碼邀請碼一個一個發出去。**沒有這一段，「受訓單位標籤」在發布
流程裡完全沒有作用**，`ET-4` 的我的課程對多數學員也永遠是空的。

本模組**只做標籤帶入**。仍屬 `ET-8` 而不在此的：Email 邀請（另一種 `JOIN_SOURCE`）、
發布後寄通知信、`ET_INVITATION` 待加入清單。

## 演算法（`EtEnrollment` docstring 已載明）

`ET_COURSE_TAG × ET_USER_TAG` 取聯集去重，限具**學員角色**者；掛有 `IS_ALL` 標籤
（「全體」）時展開為全部具學員角色者。

## 為何整批 upsert 而非單純 INSERT

課程可重複編輯標籤後再次觸發（`ET-11` 再開課、日後的標籤異動）。已在課程中的人不
可重複建列——`UQ_ET_ENROLLMENT_USER_COURSE` 是全表唯一（刻意，見 `progress/models.py`）。

⚠️ **被移除的學員（`IS_REMOVED=true`）不會被標籤帶回來**。#247 SA Q1 裁示 C 的語意是
「移除是教師的管理動作」；若標籤帶入把他重新啟用，教師移除完只要有人再發布一次就
前功盡棄，而且**沒有任何人會發現**。要讓被移除者回來，須由教師明確重新邀請
（`ET-8`），那是一個有意識的動作。
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.catalog.models import EtCourseTag, EtTag, EtUserTag
from app.et.constants import COMPLETION_NOT_STARTED, ROLE_STUDENT, SOURCE_TAG_DEFAULT
from app.et.progress.models import EtEnrollment
from app.et.roles.models import EtUserRole


class EtTagInviteRepository:
    """依課程標籤解析出應帶入的學員，並批次建立選課列。"""

    async def target_user_ids(self, db: AsyncSession, course_id: int) -> list[str]:
        """課程標籤對應之學員 `USER_ID`（去重、已排除非學員）。

        `IS_ALL` 標籤（「全體」）展開為**全部具學員角色者**，不需該使用者實際掛上
        那個標籤——否則「全體」就只是一個名字叫全體的普通標籤。
        """
        tag_rows = await db.execute(
            select(EtTag.tag_id, EtTag.is_all)
            .join(EtCourseTag, EtCourseTag.tag_id == EtTag.tag_id)
            .where(
                EtCourseTag.course_id == course_id,
                EtCourseTag.deleted == 0,
                EtTag.deleted == 0,
            )
        )
        tags = tag_rows.all()
        if not tags:
            return []

        students = select(EtUserRole.user_id).where(
            EtUserRole.role == ROLE_STUDENT,
            EtUserRole.is_active.is_(True),
            EtUserRole.deleted == 0,
        )

        if any(is_all for _, is_all in tags):
            rows = await db.scalars(students)
            return sorted(set(rows))

        tag_ids = [tag_id for tag_id, _ in tags]
        rows = await db.scalars(
            select(EtUserTag.user_id).where(
                EtUserTag.tag_id.in_(tag_ids),
                EtUserTag.deleted == 0,
                EtUserTag.user_id.in_(students),
            )
        )
        return sorted(set(rows))

    async def bulk_enroll(
        self, db: AsyncSession, course_id: int, user_ids: list[str], *, operator: OperatorInfo
    ) -> int:
        """批次建立選課列，**已存在者略過**；回傳實際新增的列數。

        Returns:
            實際新增的列數（已存在者不計）。
        """
        return len(await self.bulk_enroll_returning(db, course_id, user_ids, operator=operator))

    async def bulk_enroll_returning(
        self, db: AsyncSession, course_id: int, user_ids: list[str], *, operator: OperatorInfo
    ) -> list[str]:
        """同 `bulk_enroll`，但回傳**實際新增者的 `USER_ID`**。

        `ET-8`（#273）要對「這次真的被加進來的人」逐人寄一封通知信，而列數回答不了
        「是誰」。以 `RETURNING` 取得——`ON CONFLICT DO NOTHING` 之下它只會吐出真正
        插入的列，與 `rowcount` 同義但多帶了身分。

        以 `ON CONFLICT DO NOTHING` 而非「先查後插」：後者在兩位教師同時發布 /
        重新發布時仍會撞 `UQ_ET_ENROLLMENT_USER_COURSE`。衝突目標明寫欄位組而非約束
        名稱，避免與該約束的名稱耦合。

        🔴 **不碰既有列**（`DO NOTHING` 而非 `DO UPDATE`）——這正是「被移除的學員不會被
        標籤帶回來」的實作方式：他那一列還在，衝突後原樣保留 `IS_REMOVED=true`
        （#247 SA Q1 裁示 C）。

        ⚠️ **本方法與 `app/et/invitation/repository.py` 的 `upsert_enrollment`
        （`DO UPDATE`，讓被移除者回到課程）刻意不共用實作**。兩者看起來只差一個
        `on_conflict_*` 參數，實際上是同一條裁示的兩側：標籤帶入不得把人帶回來、
        教師明確重新邀請可以。抽成共用 helper 之後，任何人把預設值一改就會靜默打開
        那條被否決的路徑，而兩邊各自的測試都還會過。

        Returns:
            實際新增之 `USER_ID` 清單（已存在者不在其中）；`user_ids` 為空時回空清單。
        """
        if not user_ids:
            return []
        now = utcnow()
        stmt = (
            pg_insert(EtEnrollment)
            .values(
                [
                    {
                        "USER_ID": user_id,
                        "COURSE_ID": course_id,
                        "JOIN_SOURCE": SOURCE_TAG_DEFAULT,
                        "JOINED_AT": now,
                        "COMPLETION_STATUS": COMPLETION_NOT_STARTED,
                        "IS_REMOVED": False,
                        "CREATED_USER": operator.user_id,
                        "CREATED_DATE": now,
                        "DELETED": 0,
                    }
                    for user_id in user_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=["USER_ID", "COURSE_ID"])
            .returning(EtEnrollment.user_id)
        )
        result = await db.execute(stmt)
        inserted = list(result.scalars().all())
        await db.flush()
        return inserted
