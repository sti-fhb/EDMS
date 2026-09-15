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
狀態推到 `CLOSED`），於是那條窄縫在時間軸上沒有上界。

上界由 `rules.should_settle` 定義，**不是「課程一關就結清」**：限時測驗等作答時限過完，
不限時測驗等課程關閉滿 `SETTLE_GRACE_HOURS`。否則「學員還剩多少合法作答時間」會取決於
課程訖止與排程時點的相對位置——07:30 開始一份 60 分鐘測驗、課程 08:00 到期、排程 08:00
執行，他還有 30 分鐘卻被強制交卷，那正是場景 27 要保障的情境。

## 為何掃「所有視同關閉」而非「本次剛關的」

只結清本次剛到期者的話，教師**手動**按下關閉的課程永遠掃不到——而那正是 #317 的原始
觸發情境。故第 2 步的母體與第 1 步無關，各自獨立掃。

## 逐筆各自 commit（**兩個理由，缺一不可**）

比照 `app/dp/users/service.py::disable_idle_accounts`（同為 `daily_*_job` 呼叫的批次）：

1. **容錯**：`except` 內必須 `rollback()`。整批共用一個 `AsyncSession`，任一筆觸發 DB 層
   例外後 session 即進入待回滾狀態，不 rollback 就繼續跑的話，**排在它後面的每一筆都會
   跟著失敗**（`PendingRollbackError`），還各自記一行看似獨立的錯誤，把「只有第一筆是
   根因」這件事蓋掉。而查詢是 `order_by(id)`，於是同一筆壞資料會讓它之後的所有課程
   **每天連坐**。
2. **不長持稽核鏈鎖**：`AuditLogService` 取的 `pg_advisory_xact_lock` 是**交易層級**鎖，
   持有到外層交易 commit。整批一次 commit 等於 N 筆關閉全程握著**全平台唯一**的稽核鏈
   鎖，期間任何人的登入、DM 送審、DP 帳號異動的稽核寫入都得排隊。逐筆 commit 讓持鎖
   時間縮到單筆。（同一個坑見 #325 的 `add_chapter`。）
"""

import logging
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.attempt.repository import EtAttemptRepository, to_answers
from app.et.attempt.rules import grade_details, is_timed_out
from app.et.constants import ATTEMPT_IN_PROGRESS, ATTEMPT_TIMEOUT, COURSE_CLOSED, COURSE_PUBLISHED
from app.et.course.repository import EtCourseRepository
from app.et.course.rules import is_effectively_closed
from app.et.learning.repository import EtLearningRepository
from app.et.progress.repository import EtProgressRepository
from app.et.schedules.repository import EtScheduleRepository
from app.et.schedules.rules import should_settle
from app.services import AuditLogService

logger = logging.getLogger(__name__)

_MODULE: Final = "ET"
_FUNC_NAME: Final = "ET-COURSE"
#: 系統代替學員交卷屬「破例與關鍵狀態變更」（spec.md §稽核來源功能碼），與學員自己按提交
#: 不同——後者不寫稽核。
_FUNC_NAME_ATTEMPT: Final = "ET-ATTEMPT"

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
        learning: EtLearningRepository | None = None,
        audit: AuditLogService | None = None,
    ) -> None:
        self._repo = repository or EtScheduleRepository()
        self._courses = courses or EtCourseRepository()
        self._attempts = attempts or EtAttemptRepository()
        self._progress = progress or EtProgressRepository()
        self._learning = learning or EtLearningRepository()
        self._audit = audit or AuditLogService()

    async def close_expired_courses(self, db: AsyncSession) -> int:
        """已逾閱課期間之課程轉 `CLOSED` + 稽核（FR-ET-US14-06）。

        沿用 `mark_closed`（與教師手動關閉同一支）：狀態機、`CLOSED_AT`、樂觀鎖的行為
        因此一致，不會出現「排程關的課」與「手動關的課」在後續判定上有差異。

        **稽核與手動關閉對等**（`func_name=ET-COURSE`，`operator_id=SYSTEM`）：關閉一門課
        會立刻影響全部在籍學員，兩條路徑只有一條留紀錄的話，事後查「這門課為什麼關了」
        會在自動關閉的案例上一無所獲。不帶 `source_ip`——排程沒有請求來源，硬填會讓那個
        欄位變成不可信。

        `mark_closed` 回 `None` 表示版本不符——有人在本次掃描與寫入之間改了那門課。
        不重試：下一次每日執行會再掃到它。

        Returns:
            實際轉為 `CLOSED` 的課程數。
        """
        now = utcnow()
        closed = 0
        for course_id in await self._repo.expired_published_course_ids(db, now):
            try:
                if await self._close_one(db, course_id, now=now):
                    await db.commit()
                    closed += 1
                else:
                    await db.rollback()
            except Exception:
                await db.rollback()
                logger.exception("SCHET002 到期關閉失敗 course_id=%s", course_id)
        return closed

    async def _close_one(self, db: AsyncSession, course_id: int, *, now) -> bool:
        """單門課關閉 + 稽核；回傳是否真的由本次關閉。

        **逐筆重取**而非沿用掃描時的實體：`rollback()` 會讓已載入的 ORM 物件過期，沿用
        會在第一次失敗之後死於 `MissingGreenlet`（見 repository 的說明）。重取順帶讓
        下面的「狀態是否仍符合」檢查讀到最新值。
        """
        course = await self._courses.get(db, course_id)
        if course is None or course.status != COURSE_PUBLISHED or course.open_end_at is None:
            # 掃描與處理之間被再開課 / 手動關閉 / 刪除——本次略過，下次重掃
            return False
        if course.open_end_at >= now:
            return False
        version = await self._courses.mark_closed(
            db, course_id, course.version, closed_at=now, operator=_SYSTEM_OPERATOR
        )
        if version is None:
            logger.info("到期關閉略過（版本不符，下次重掃）course_id=%s", course_id)
            return False
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=_SYSTEM_OPERATOR.user_id,
            target_id=str(course_id),
            description="閱課期間已過，系統自動關閉",
        )
        return True

    async def settle_stale_attempts(self, db: AsyncSession) -> int:
        """視同關閉之課程下仍未提交的 attempt → `TIMEOUT` 並計分（#317）。

        閱卷走 `rules.grade_details`——與學員自己按提交時**完全同一支**。兩邊若各寫一份，
        表徵會是同一份考卷因「誰按的提交」而及格與否不同，且沒有任何錯誤訊息。

        **不是「課程一關就全部結清」**：每一筆還要通過 `rules.should_settle`（限時測驗
        等時限過完、不限時測驗等關閉滿 24 小時），否則會把學員手上還有合法作答時間的
        考卷收走——`spec_us6` 場景 27 明訂那是不可以的。未達門檻者留到下一輪重掃。

        **寫稽核（`ET-ATTEMPT`）**：學員自己按提交不寫稽核（那是他自己的動作，追溯來源
        是 `ET_QUIZ_ATTEMPT_D`），但本路徑是**系統代替他交卷**——屬 spec.md §稽核來源功能碼
        所稱的「破例與關鍵狀態變更」，與 `ET-QUIZ-RESET`（教師破例重置重考次數）同類。
        少了它，學員問「我的考卷為什麼被交出去、分數哪來的」時，系統唯一能拿出的只有
        `UPDATED_USER='SYSTEM'`。

        Returns:
            實際結清的 attempt 數。
        """
        now = utcnow()
        settled = 0
        for attempt_id in await self._repo.stale_in_progress_attempt_ids(db, now):
            try:
                if await self._settle_one(db, attempt_id, now=now):
                    await db.commit()
                    settled += 1
                else:
                    await db.rollback()
            except Exception:
                await db.rollback()
                logger.exception("SCHET002 結清逾期作答失敗 attempt_id=%s", attempt_id)
        return settled

    async def _settle_one(self, db: AsyncSession, attempt_id: int, *, now) -> bool:
        """單筆結清；回傳是否真的由本次完成轉移。

        **逐筆重取**而非沿用掃描時的實體，理由同 `_close_one`。

        ## 寫入前重驗兩件事

        1. **課程是否仍視同關閉**：掃描與寫入之間教師可能按了再開課。沿用掃描結果會把
           一門已經重新開放的課程裡、學員**正在寫**的考卷結清掉。
        2. **是否真的沒有合法作答時間了**：見 `rules.should_settle`——限時測驗要等時限
           過完，不限時測驗要等關閉滿寬限期。少了這道，`spec_us6` 場景 27 會被本作業
           推翻。
        """
        attempt = await self._attempts.get_attempt(db, attempt_id)
        if attempt is None or attempt.status != ATTEMPT_IN_PROGRESS:
            return False
        course = await self._learning.get_course(db, attempt.course_id)
        if course is None or not is_effectively_closed(status=course.status, open_end_at=course.open_end_at, now=now):
            return False
        closed_since = course.closed_at if course.status == COURSE_CLOSED else course.open_end_at
        timed_out = is_timed_out(started_at=attempt.started_at, time_limit_min=attempt.time_limit_snapshot, now=now)
        if not should_settle(closed_since=closed_since, timed_out=timed_out, now=now):
            return False
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
        if graded.is_pass and not await self._is_preview(db, attempt, course):
            await self._mark_item_completed(db, attempt)
        await self._audit.log_action(
            db,
            module=_MODULE,
            func_name=_FUNC_NAME_ATTEMPT,
            action_type="UPDATE",
            result="SUCCESS",
            operator_id=_SYSTEM_OPERATOR.user_id,
            target_id=str(attempt.attempt_id),
            description=(
                f"課程關閉後逾期未提交，系統結清並計分"
                f"（course_id={attempt.course_id}、逾時={timed_out}、及格={graded.is_pass}）"
            ),
            before_value={"status": ATTEMPT_IN_PROGRESS},
            after_value={"status": ATTEMPT_TIMEOUT, "score": str(graded.total), "is_pass": graded.is_pass},
        )
        return True

    async def _is_preview(self, db: AsyncSession, attempt, course) -> bool:
        """該 attempt 是否為擁有者預覽（是擁有者且**不在籍**）。

        ⚠️ **本判定不可省略**，即使結清路徑不經 `AttemptService`：教師可對自己課程開
        attempt 而不必在籍（`ensure_can_access(enrolled, is_owner)`），而 #255 裁示 Q1
        明訂教師預覽**不得寫入** `ET_PROGRESS`——否則教師預覽完就出現在自己課程的完課
        統計裡。`AttemptService.submit()` 於同一位置以 `_is_preview` 擋下；漏掉這道，
        一筆被遺忘的預覽 attempt 會在課程關閉後由排程悄悄寫進進度表，而且不會有任何
        錯誤訊息。

        `course` 由呼叫端傳入（`_settle_one` 已為了重驗關閉狀態取過一次），不重查。
        """
        enrolled = await self._learning.is_enrolled(db, user_id=attempt.user_id, course_id=attempt.course_id)
        return course.owner_id == attempt.user_id and not enrolled

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
