"""SCHET002 每日課程時窗檢查（US14 / #325、#317）。

兩件事，順序不可調換：

```
1. 到期自動關閉        OPEN_END_AT 已過且仍 PUBLISHED → CLOSED（T139 / FR-ET-US14-06）
2. 結清逾期未提交作答   視同關閉之課程下仍 IN_PROGRESS 的 attempt → TIMEOUT 並計分（#317）
```

## 為何「結清」是計分而不是沒收

`spec_us6` 場景 27 明訂「課程關閉當下已在作答的 attempt 仍可完成並計分」。本作業不推翻
它——結清走的是場景 10（逾時自動提交）的處理：標 `TIMEOUT` 但**照常閱卷**，及格照樣
回寫項目完成。學員寫到哪就算到哪。

實質上被收斂的只有「無限期地回來繼續寫」：在本作業存在之前，`IN_PROGRESS` 的 attempt
沒有任何生命週期上限，而「期間已過而 `STATUS` 仍是 `PUBLISHED`」是常態（沒有東西會把
狀態推到 `CLOSED`），於是那條窄縫在時間軸上沒有上界。本作業每日執行，上界因此收斂為
「關閉後到下一次排程」。

## 為何掃「所有視同關閉」而非「本次剛關的」

只結清本次剛到期者的話，教師**手動**按下關閉的課程永遠掃不到——而那正是 #317 的原始
觸發情境。故第 2 步的母體與第 1 步無關，各自獨立掃。

## 容錯

逐課 / 逐 attempt 獨立 try/except：單一課程的資料異常不該讓整批停擺（比照
`app/dp/schedules/handlers.py::daily_platform_job` 的批次隔離）。本層**不 commit**，
交由 handler 控制交易邊界。
"""

import logging
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.attempt.repository import EtAttemptRepository, to_answers
from app.et.attempt.rules import grade_details
from app.et.constants import ATTEMPT_TIMEOUT
from app.et.course.repository import EtCourseRepository
from app.et.progress.repository import EtProgressRepository
from app.et.schedules.repository import EtScheduleRepository

logger = logging.getLogger(__name__)

#: 排程沒有登入者。記成學員本人會讓稽核看起來像「他自己提交的」。
_SYSTEM_OPERATOR: Final = OperatorInfo(user_id="SYSTEM")


class EtScheduleService:
    """SCHET002 之業務編排。"""

    def __init__(
        self,
        repository: EtScheduleRepository | None = None,
        courses: EtCourseRepository | None = None,
        attempts: EtAttemptRepository | None = None,
        progress: EtProgressRepository | None = None,
    ) -> None:
        self._repo = repository or EtScheduleRepository()
        self._courses = courses or EtCourseRepository()
        self._attempts = attempts or EtAttemptRepository()
        self._progress = progress or EtProgressRepository()

    async def close_expired_courses(self, db: AsyncSession) -> int:
        """已逾閱課期間之課程轉 `CLOSED`（FR-ET-US14-06）。

        沿用 `mark_closed`（與教師手動關閉同一支）：狀態機、`CLOSED_AT`、樂觀鎖的行為
        因此一致，不會出現「排程關的課」與「手動關的課」在後續判定上有差異。

        `mark_closed` 回 `None` 表示版本不符——有人在本次掃描與寫入之間改了那門課。
        不重試：下一次每日執行會再掃到它。

        Returns:
            實際轉為 `CLOSED` 的課程數。
        """
        now = utcnow()
        closed = 0
        for course in await self._repo.expired_published_courses(db, now):
            try:
                version = await self._courses.mark_closed(
                    db, course.course_id, course.version, closed_at=now, operator=_SYSTEM_OPERATOR
                )
            except Exception:
                logger.exception("到期關閉失敗 course_id=%s", course.course_id)
                continue
            if version is None:
                logger.info("到期關閉略過（版本不符，下次重掃）course_id=%s", course.course_id)
                continue
            closed += 1
        return closed

    async def settle_stale_attempts(self, db: AsyncSession) -> int:
        """視同關閉之課程下仍未提交的 attempt → `TIMEOUT` 並計分（#317）。

        閱卷走 `rules.grade_details`——與學員自己按提交時**完全同一支**。兩邊若各寫一份，
        表徵會是同一份考卷因「誰按的提交」而及格與否不同，且沒有任何錯誤訊息。

        Returns:
            實際結清的 attempt 數。
        """
        now = utcnow()
        settled = 0
        for attempt in await self._repo.stale_in_progress_attempts(db, now):
            try:
                if await self._settle_one(db, attempt, now=now):
                    settled += 1
            except Exception:
                logger.exception("結清逾期作答失敗 attempt_id=%s", attempt.attempt_id)
        return settled

    async def _settle_one(self, db: AsyncSession, attempt, *, now) -> bool:
        """單筆結清；回傳是否真的由本次完成轉移。"""
        details = await self._attempts.list_details(db, attempt.attempt_id)
        graded = grade_details(to_answers(details), pass_score=attempt.pass_score_snapshot)
        moved = await self._attempts.submit(
            db,
            attempt=attempt,
            status=ATTEMPT_TIMEOUT,
            total=graded.total,
            is_pass=graded.is_pass,
            per_question=graded.per_question,
            submitted_at=now,
            operator=_SYSTEM_OPERATOR,
        )
        if not moved:
            # 學員在掃描與寫入之間自己按了提交——他的成績為準，不覆蓋
            return False
        if graded.is_pass:
            await self._mark_item_completed(db, attempt)
        return True

    async def _mark_item_completed(self, db: AsyncSession, attempt) -> None:
        """及格 → 回寫項目層完成。

        ⚠️ **直接呼叫 repository，不繞經 `EtProgressService`**——理由與
        `attempt/service._mark_item_completed` 完全相同：那支的 `_guard_write` 對視同關閉
        的課程一律 409，而本路徑處理的**全部**都是視同關閉的課程，繞不過去就一筆都寫不成。
        及格後的項目完成回寫是計分的一部分（`spec_us6` 場景 27），少做這一半等於結清只
        完成了一半。
        """
        context = await self._attempts.quiz_context(db, attempt.quiz_id)
        if context is None:
            return
        item_id, course_id = context
        await self._progress.set_item_completed(
            db,
            user_id=attempt.user_id,
            course_id=course_id,
            item_id=item_id,
            completed=True,
            operator=_SYSTEM_OPERATOR,
        )
