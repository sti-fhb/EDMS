"""SCHET001 之週統計快照（T145 / US14 / #325）。

每週對**開放中**課程各寫一筆 `ET_WEEKLY_STAT`，供週報之「與上週比較」與歷史回查。

## 統計與寄信分離

FR-ET-US14-09 明訂「寄送失敗 MUST NOT 影響已寫入之統計快照資料」。故本模組**只負責
快照**、完全不碰寄信；週報與提醒由 `notify` 側在快照完成之後才進行。分離的方式是各自
獨立的方法與各自的交易，不是 try/except——後者仍會讓兩件事共用同一個交易邊界。

## 逐課各自 commit

理由同 `schedules/service`：單一課程的資料異常不該讓整批停擺，且 `except` 內必須
`rollback()`，否則後面每一筆都連坐 `PendingRollbackError`。
"""

import logging
from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.params.service import ParamService
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.enrollment.service import EtEnrollmentService
from app.et.stats.repository import EtStatsRepository
from app.et.stats.rules import days_left, percent, summarize
from app.et.stats.schemas import AdminCard, StudentCard, TeacherCard, TeacherCourseLine, UnitRate
from app.et.tracking.repository import EtTrackingRepository

logger = logging.getLogger(__name__)

_SYSTEM_OPERATOR: Final = OperatorInfo(user_id="SYSTEM")

#: 訖止前幾天算「即將截止」。**與加急提醒信共用同一個 `DP_PARAM`**
#: （`schedules/service` 的 `_URGENT_PARAM_ID`）——首頁與信件若用不同門檻，會出現
#: 「首頁說要注意了、信還沒寄」或反過來，而兩者都宣稱依據同一條規則。
_URGENT_PARAM_ID: Final = "ET_URGENT_REMIND_DAYS"
_URGENT_DAYS_DEFAULT: Final = 3


class EtStatsService:
    """週統計快照之編排。"""

    def __init__(
        self,
        repository: EtStatsRepository | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        tracking: EtTrackingRepository | None = None,
        params: ParamService | None = None,
        enrollment_service: EtEnrollmentService | None = None,
    ) -> None:
        self._repo = repository or EtStatsRepository()
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._tracking = tracking or EtTrackingRepository()
        self._params = params or ParamService()
        # 學員卡走 service 而非 repository：要的是 `my_courses()` **整支**的輸出，
        # 那四個數字由它內部的 `_summarize` 產生（見 `student_card`）。
        self._enrollment_service = enrollment_service or EtEnrollmentService()

    async def take_snapshots(self, db: AsyncSession, *, now: datetime | None = None) -> int:
        """對每門開放中課程寫入一筆快照（FR-ET-US14-02 / -03）。

        Returns:
            實際寫入的快照數（同日重跑已存在者不計）。
        """
        now = now or utcnow()
        stat_date = now.date()
        written = 0
        for course_id in await self._repo.open_course_ids(db, now):
            try:
                if await self._snapshot_one(db, course_id, stat_date=stat_date):
                    await db.commit()
                    written += 1
                else:
                    await db.rollback()
            except Exception:
                await db.rollback()
                logger.exception("SCHET001 統計快照失敗 course_id=%s", course_id)
        return written

    async def _snapshot_one(self, db: AsyncSession, course_id: int, *, stat_date) -> bool:
        """單門課的快照；回傳是否真的由本次寫入。"""
        stat = await self.course_stat(db, course_id)
        return await self._repo.insert_snapshot(
            db, course_id=course_id, stat_date=stat_date, stat=stat, operator=_SYSTEM_OPERATOR
        )

    # ── 首頁儀表板（#453 / #89 的 P3）────────────────────────────────────────

    async def student_card(self, db: AsyncSession, *, user_id: str) -> StudentCard:
        """學員卡：四個數字**取自 `my_courses()` 的 `summary`，不另算一份**。

        ⚠️ 看起來只為了四個數字就跑了整支 `my_courses`（含標籤、章節數、逐課進度），
        那是刻意的：ET03 頁面與本卡顯示同一組數字，各算一次的話會在課程剛開放 / 剛
        關閉的瞬間分歧，而**兩個數字都看起來合理**，沒有人會知道哪個錯。同源是靠
        「呼叫同一支」保證，不是靠兩邊小心。
        """
        summary = (await self._enrollment_service.my_courses(db, user_id=user_id)).summary
        return StudentCard(
            joined=summary.joined,
            in_progress=summary.in_progress,
            not_started=summary.not_started,
            completed=summary.completed,
            pending_open=summary.pending_open,
        )

    async def teacher_card(self, db: AsyncSession, *, owner_id: str, now: datetime | None = None) -> TeacherCard:
        """教師卡：即將截止且仍有人未完課的課程 + 草稿未發布數。

        `urgent_days` 取自 `ET_URGENT_REMIND_DAYS`（`DP_PARAM`）——與加急提醒信同一個
        門檻，理由見 `EtStatsRepository.courses_ending_soon`。

        **未完課人數以 `course_stat()` 即時算**，與週報、ET02 頁面同一支。⛔ 不可改讀
        `ET_ENROLLMENT.COMPLETION_STATUS`：該欄只在建立選課列時寫一次 `NOT_STARTED`、
        **之後永不更新**（全專案無任何 update 寫它），讀它會讓「未完課人數」恆等於
        在籍人數，而畫面上看不出異常。
        """
        now = now or utcnow()
        urgent_days = await self._params.get_int_param(db, _URGENT_PARAM_ID, "VALUE", _URGENT_DAYS_DEFAULT)
        lines = []
        for course in await self._repo.courses_ending_soon(db, owner_id=owner_id, now=now, urgent_days=urgent_days):
            stat = await self.course_stat(db, course.course_id)
            not_completed = stat.cnt_enrolled - stat.cnt_completed
            # 全班都完課的課程不列：它不需要教師做任何事，留著只會稀釋真正要處理的那幾門
            if not_completed <= 0:
                continue
            lines.append(
                TeacherCourseLine(
                    course_id=course.course_id,
                    course_name=course.course_name,
                    days_left=days_left(course.open_end_at, now),
                    not_completed=not_completed,
                )
            )
        return TeacherCard(ending_soon=lines, draft_count=await self._repo.draft_count(db, owner_id))

    async def admin_card(self, db: AsyncSession, *, now: datetime | None = None) -> AdminCard:
        """管理者卡：全站逾期未完課、整體完成率、各單位達成率。

        兩支查詢共用 `_completion_base`（全站「每筆在籍 × 是否完課」），故整體與分單位
        的完課定義**不可能分歧**——分開寫兩份推導才是分歧的來源。

        各單位依達成率**由低到高**排序：管理者要找的是落後的那一個，把最好的排在最前
        面等於要他自己從尾巴讀起。
        """
        now = now or utcnow()
        enrolled, completed, overdue = await self._repo.overall_completion(db, now)
        units = [
            UnitRate(
                tag_name=name,
                enrolled=unit_enrolled,
                completed=unit_completed,
                completion_rate=percent(unit_completed, unit_enrolled),
            )
            for name, unit_enrolled, unit_completed in await self._repo.unit_rates(db, now)
        ]
        units.sort(key=lambda u: (u.completion_rate, u.tag_name))
        return AdminCard(
            overdue_incomplete=overdue,
            completion_rate=percent(completed, enrolled),
            by_unit=units,
        )

    async def course_stat(self, db: AsyncSession, course_id: int):
        """該課程當下的統計（不寫入）——快照與週報渲染共用同一份計算。

        母體為**在籍**學員（`enrolled_user_ids` 已濾 `IS_REMOVED`）；逐學員完成數取自
        `tracking` 的「一門課 × 多位學員」聚合。

        ⚠️ 不可改用 `progress.completion_counts_by_course()`：那支是「一位學員 × 多門
        課程」，形狀相反，逐人呼叫會讓一門 500 人的課每週打出 1000 次查詢。
        """
        user_ids = await self._enrollments.enrolled_user_ids(db, course_id)
        counts = await self._tracking.completion_counts_by_student(db, course_id=course_id, user_ids=user_ids)
        return summarize(counts)
