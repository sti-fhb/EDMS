"""ET 排程作業之批次查詢（US14 / #325）。

單獨成檔而非併入各子模組的 `repository.py`：這裡的查詢形狀是**跨課程的批次掃描**（誰
到期了、誰還留著沒提交的考卷），與那些檔案的逐實體 CRUD 性質不同。同一個理由見
`course/publish_repository.py` 的開頭說明。

## 「視同關閉」在此以 SQL 表達，與 `course.rules.is_effectively_closed` 同義

那支純函式吃單一課程的 `(status, open_end_at)`，本檔要的是一次撈出全部符合者，故以
`or_()` 重述同一組條件。兩者若分岔，表徵是「應用層擋得住、排程掃不到」——沒有錯誤
訊息，只會有一批永遠不被結清的 attempt。改動任一邊時請一起看。
"""

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.et.constants import ATTEMPT_IN_PROGRESS, COURSE_CLOSED, COURSE_PUBLISHED
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.quiz.models import EtQuiz, EtQuizAttemptM
from app.et.roles.models import EtUserRole


def _effectively_closed(now: datetime):
    """`STATUS='CLOSED'` 或「已發布但期間已過」——與 `is_effectively_closed` 同義。"""
    return or_(
        EtCourse.status == COURSE_CLOSED,
        and_(EtCourse.status == COURSE_PUBLISHED, EtCourse.open_end_at.is_not(None), EtCourse.open_end_at < now),
    )


class EtScheduleRepository:
    """SCHET002 之批次掃描查詢。"""

    async def active_role_user_ids(self, db: AsyncSession, role: str) -> set[str]:
        """目前**仍持有**該 ET 角色者（`IS_ACTIVE` 為真且未軟刪）。

        週報收件人依此推導，而非只看 `ET_COURSE.OWNER_ID`：教師角色被停用是離職 / 轉調
        的標準第一步，而課程的 `OWNER_ID` 是不變的——只看擁有者會讓已離職者繼續每週收到
        課程週報（內含全班姓名）。該課程仍會出現在管理者的全域週報裡，不會沒人看到。
        """
        rows = await db.scalars(
            select(EtUserRole.user_id).where(
                EtUserRole.role == role,
                EtUserRole.is_active.is_(True),
                EtUserRole.deleted == 0,
            )
        )
        return set(rows.all())

    async def expired_published_course_ids(self, db: AsyncSession, now: datetime) -> list[int]:
        """已逾 `OPEN_END_AT` 但狀態仍為 `PUBLISHED` 之課程 id（FR-ET-US14-06）。

        **不含**已是 `CLOSED` 者——它們已經關過了，再關一次只會覆寫 `CLOSED_AT`，把
        「什麼時候關的」這個資訊每日往後推。

        `open_end_at.is_not(None)` 在 SQL 語意上可省略（`NULL < now` 不為真），寫出來是為了
        讓下面這件事在查詢裡看得見：

        ⚠️ **`OPEN_END_AT` 為 `NULL` 的已發布課程會被本查詢排除，因而永遠不會自動關閉**，
        其下的 attempt 也就永遠不會被結清。發布檢核要求起訖必填（`publish_rules`），但
        `PUT /courses/{id}` 曾可把已發布課程的訖止**清成 `NULL`**（全量覆寫表單少送一個欄位
        即可），而清成 `NULL` 是永久失效——`is_effectively_closed` 從此對該課程一律回
        `False`。該破口由 **#328** 於入口處堵上；本查詢刻意**不**在此另做補救，否則兩處
        對「什麼叫視同關閉」的定義就會分岔。

        ## 只回 id，不回 ORM 物件

        呼叫端**逐筆 commit / rollback**（見 `service` 的兩個理由）。`rollback()` 一律讓
        已載入的 ORM 物件過期——不論 session 是否設 `expire_on_commit=False`。若在此回傳
        實體，下一圈存取 `course.version` 會觸發 lazy refresh，而屬性存取無法 await，
        於是整批在**第一次失敗之後**死於 `MissingGreenlet`，而不是繼續處理其餘課程。
        呼叫端據 id 逐筆重取，順帶拿到最新版本與狀態。
        """
        rows = await db.scalars(
            select(EtCourse.course_id)
            .where(
                EtCourse.status == COURSE_PUBLISHED,
                EtCourse.open_end_at.is_not(None),
                EtCourse.open_end_at < now,
                EtCourse.deleted == 0,
            )
            .order_by(EtCourse.course_id)
        )
        return list(rows.all())

    async def stale_in_progress_attempt_ids(self, db: AsyncSession, now: datetime) -> list[int]:
        """視同關閉之課程下，仍為 `IN_PROGRESS` 的 attempt id（#317）。

        只回 id 的理由同 `expired_published_course_ids`。

        課程層以 `ET_CHAPTER.COURSE_ID` 反查而非 `ET_QUIZ_ATTEMPT_M.COURSE_ID`：後者是
        開始作答當下存下的冗餘欄位，前者才是當前的結構事實（同 `progress/repository`
        的 `completion_counts_by_course`）。

        軟刪除的章節 / 項目 / 測驗一併排除——教師刪掉整章之後，那些 attempt 的考卷已無
        對應題目，結清它們沒有意義，且 `_mark_item_completed` 的反查本來就會落空。
        """
        rows = await db.scalars(
            select(EtQuizAttemptM.attempt_id)
            .join(EtQuiz, EtQuiz.quiz_id == EtQuizAttemptM.quiz_id)
            # ⚠️ FK 方向是 `ET_ITEM.QUIZ_ID` → `ET_QUIZ`（測驗本體不帶 item_id），
            # 同 `attempt/repository.quiz_context`
            .join(EtItem, EtItem.quiz_id == EtQuiz.quiz_id)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .join(EtCourse, EtCourse.course_id == EtChapter.course_id)
            .where(
                EtQuizAttemptM.status == ATTEMPT_IN_PROGRESS,
                EtQuizAttemptM.deleted == 0,
                EtQuiz.deleted == 0,
                EtItem.deleted == 0,
                EtChapter.deleted == 0,
                EtCourse.deleted == 0,
                _effectively_closed(now),
            )
            .order_by(EtQuizAttemptM.attempt_id)
        )
        return list(rows.all())
