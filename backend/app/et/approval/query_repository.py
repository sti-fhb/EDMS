"""核可查詢之資料存取（US17 / #385）——**唯讀**。

## 為何與 `repository.py` 分檔

那一檔的六個方法全是寫入語意（`reapprove` / `insert_approval` / `mark_revoked`），
而本檔是跨三張表的查詢。混在一起會讓那一檔的職責變成「核可的所有事」，且日後改查詢
時得在一堆 `ON CONFLICT` 之間找路。

## `paginate()` 只取第一個欄位

`core/pagination.py:111` 是 `result.scalars().all()`——**JOIN 進來的額外欄位會被丟掉**。
所以分頁語句雖然 JOIN 了 `ET_COURSE`（範圍判定 + 課程名）與 `DP_USER`（姓名過濾），
`select()` 裡仍只放 `EtApproval`；其餘顯示用欄位在拿到該頁之後另以批次查詢補齊。

這與 `tracking/repository.py:182` 的既有作法一致（分頁主表、再查姓名），也順帶避開
「兩個一對多 JOIN 會灌大計數」那個坑——此處三個關聯都是多對一、不會膨脹，但分開查
之後連日後有人加上一對多 JOIN 都不會影響分頁數字。
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.like_escape import LIKE_ESCAPE_CHAR
from app.core.like_escape import contains as like_contains
from app.dp.users.models import DpUser
from app.et.approval.models import EtApproval
from app.et.constants import APPROVAL_PASS
from app.et.course.models import EtCourse


class EtApprovalQueryRepository:
    """核可紀錄之查詢（教師 / 管理者依姓名查、學員查自己已通過）。"""

    def teacher_query_stmt(self, *, user_name: str, visible, result: str | None = None) -> Select:
        """教師 / 管理者依學員姓名查詢的語句（未套 offset/limit，供 `paginate()`）。

        🔴 **姓名比對必須跳脫 LIKE 萬用字元**：未跳脫時使用者輸入 `%` 會變成「查全部」，
        讓「姓名必填」（SA Q2 裁示 A）形同虛設，**而且沒有任何錯誤訊息**。`escape=` 要給
        具名字元，不能省——省略時 PostgreSQL 用預設的 `\\`，與 `like_contains()` 跳脫時
        用的字元不一致，跳脫就失效了。前例見 `course/repository.py:277`。

        Args:
            user_name: 學員姓名關鍵字（呼叫端已確認非空白）。
            visible: `query_rules.visible_clause()` 的結果。
            result: 選填的結果篩選（`PASS` / `FAIL`）；`None` 表不篩。

        Returns:
            已套 where / order_by 的 `Select`，**只 select `EtApproval`**（見模組 docstring）。
        """
        stmt = (
            select(EtApproval)
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .join(DpUser, DpUser.user_id == EtApproval.user_id)
            .where(
                EtApproval.deleted == 0,
                EtCourse.deleted == 0,
                DpUser.deleted == 0,
                DpUser.user_name.ilike(like_contains(user_name), escape=LIKE_ESCAPE_CHAR),
                visible,
            )
            .order_by(EtApproval.approved_at.desc(), EtApproval.approval_id.desc())
        )
        if result is not None:
            stmt = stmt.where(EtApproval.result == result)
        return stmt

    def mine_stmt(self, *, user_id: str) -> Select:
        """學員自查：**自己**、`RESULT = PASS`、**未撤銷**（`FR-ET-US17-03`）。

        ⚠️ 三個條件缺一不可。少了 `IS_REVOKED = false`，一筆被撤銷的通過會出現在學員的
        「已通過課程」裡——而那個通過已經被教師推翻了。
        """
        return (
            select(EtApproval)
            .join(EtCourse, EtCourse.course_id == EtApproval.course_id)
            .where(
                EtApproval.user_id == user_id,
                EtApproval.result == APPROVAL_PASS,
                EtApproval.is_revoked.is_(False),
                EtApproval.deleted == 0,
                EtCourse.deleted == 0,
            )
            .order_by(EtApproval.approved_at.desc(), EtApproval.approval_id.desc())
        )

    async def course_names(self, db: AsyncSession, course_ids: list[int]) -> dict[int, str]:
        """本頁涉及的課程名稱。"""
        if not course_ids:
            return {}
        rows = await db.execute(
            select(EtCourse.course_id, EtCourse.course_name).where(EtCourse.course_id.in_(course_ids))
        )
        return {cid: name for cid, name in rows}

    async def user_names(self, db: AsyncSession, user_ids: list[str]) -> dict[str, str]:
        """本頁涉及的使用者姓名（學員 / 核可人 / 撤銷人共用一次查詢）。

        ⚠️ **不濾 `DELETED`**：核可人可能已離職，但那筆核可仍是歷史事實，姓名要顯示得
        出來。（`DP_USER.DELETED` 在本系統實務上恆為 0，此處是語意宣告而非防禦。）
        """
        if not user_ids:
            return {}
        rows = await db.execute(select(DpUser.user_id, DpUser.user_name).where(DpUser.user_id.in_(user_ids)))
        # ⚠️ 不可寫成 `dict(rows)`——`Result` 本身不是可直接建字典的映射
        # （`TypeError: 'ChunkedIteratorResult' object is not subscriptable`），
        # 要先逐列取出。與上面的 `course_names` 保持同一種寫法。
        return {uid: name for uid, name in rows}
