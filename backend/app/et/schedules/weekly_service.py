"""SCHET001 之週報與每週未看提醒（T146 / T147 / US14 / #325）。

快照由 `stats/service` 負責；本模組只做**寄信**。FR-ET-US14-09 明訂「寄送失敗
MUST NOT 影響已寫入之統計快照資料」，故兩者是各自獨立的方法與各自的交易，不是
try/except——後者仍會讓兩件事共用同一個交易邊界。

## 讀階段與寄階段分離

先一次算完所有課程的統計與名單、轉成純值；再逐人寄信、逐人 commit。

**不可邊算邊寄**：寄信階段每封一個交易，而 `commit()` / `rollback()` 會讓已載入的 ORM
實體過期，下一圈存取屬性即 lazy refresh → `MissingGreenlet`。分兩階段之後，寄送階段完全
不持有 session 狀態。

## 收件人

| 對象 | 母體 | 內容 |
|---|---|---|
| 管理者 | 仍持有 `ADMIN` 角色者 | **全域**所有開放中課程 |
| 教師 | 仍持有 `TEACHER` 角色**且**為某開放中課程之 `OWNER_ID` | 僅自己的課程 |

**兼任者只收管理者版**（SA Q3 裁示 A）：全域版的內容完全涵蓋教師版，同一次排程對同一
人寄兩封主旨相同的信，收件者會直接視為系統異常。

名下無開放中課程的教師**不寄**（沿用 `COURSE_INVITE_DIGEST` 的「空清單不寄信」）。
"""

import logging
from datetime import datetime
from typing import Final, NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.et.constants import ROLE_ADMIN, ROLE_TEACHER
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.schedule_mail import (
    TEMPLATE_WEEKLY_REMIND,
    TEMPLATE_WEEKLY_REPORT,
    CourseReportLine,
    RemindCourse,
    build_weekly_remind_params,
    build_weekly_report_params,
)
from app.et.notify.service import EtNotifier
from app.et.reports.links import weekly_report_link
from app.et.schedules.repository import EtScheduleRepository
from app.et.stats.repository import EtStatsRepository, OpenCourse
from app.et.stats.rules import progress_delta, summarize
from app.et.tracking.repository import EtTrackingRepository

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY: Final = 86400


class _CourseFacts(NamedTuple):
    """一門開放中課程於本次執行的全部衍生值（純值，與 session 無關）。"""

    course: OpenCourse
    line: CourseReportLine
    not_started_user_ids: list[str]


class EtWeeklyReportService:
    """SCHET001 之週報與未看提醒編排。"""

    def __init__(
        self,
        stats: EtStatsRepository | None = None,
        schedules: EtScheduleRepository | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        tracking: EtTrackingRepository | None = None,
        notifier: EtNotifier | None = None,
        notify_repo: EtNotifyRepository | None = None,
    ) -> None:
        self._stats = stats or EtStatsRepository()
        self._schedules = schedules or EtScheduleRepository()
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._tracking = tracking or EtTrackingRepository()
        self._notifier = notifier or EtNotifier()
        self._notify_repo = notify_repo or EtNotifyRepository()

    async def send_weekly(self, db: AsyncSession, *, now: datetime | None = None) -> tuple[int, int]:
        """寄出週報與每週未看提醒。

        Returns:
            `(週報封數, 未看提醒封數)`——僅供 log 與測試，不影響任何業務判斷。
        """
        now = now or utcnow()
        facts = await self._collect(db, now)
        reports = await self._send_reports(db, facts)
        reminds = await self._send_reminds(db, facts)
        return reports, reminds

    # ── 讀階段 ──────────────────────────────────────────────────────────────

    async def _collect(self, db: AsyncSession, now: datetime) -> list[_CourseFacts]:
        """一次算完所有開放中課程的統計、與上週比較、未開始名單。"""
        facts: list[_CourseFacts] = []
        for course in await self._stats.open_courses(db, now):
            user_ids = await self._enrollments.enrolled_user_ids(db, course.course_id)
            counts = await self._tracking.completion_counts_by_student(
                db, course_id=course.course_id, user_ids=user_ids
            )
            stat = summarize(counts)
            previous = await self._stats.previous_avg_progress(db, course_id=course.course_id, before=now.date())
            # 未開始者的 id 只用於「寄未看提醒給誰」，**不進週報內文**——姓名不得出現在
            # 可轉寄的信件裡（見 `schedule_mail.CourseReportLine`）
            not_started = [uid for uid, (done, _total) in counts.items() if done == 0]
            facts.append(
                _CourseFacts(
                    course=course,
                    line=CourseReportLine(
                        course_name=course.course_name,
                        stat=stat,
                        delta=progress_delta(stat.avg_progress_pct, previous),
                        days_left=_days_left(course.open_end_at, now),
                    ),
                    not_started_user_ids=not_started,
                )
            )
        return facts

    # ── 寄階段 ──────────────────────────────────────────────────────────────

    async def _send_reports(self, db: AsyncSession, facts: list[_CourseFacts]) -> int:
        """教師 / 管理者週報（FR-ET-US14-04）。"""
        admins = await self._schedules.active_role_user_ids(db, ROLE_ADMIN)
        teachers = await self._schedules.active_role_user_ids(db, ROLE_TEACHER)

        by_recipient: dict[str, list[CourseReportLine]] = {}
        if facts:
            # 管理者：全域。兼任教師者也只出現在這裡（SA Q3 裁示 A）
            for admin_id in admins:
                by_recipient[admin_id] = [f.line for f in facts]
        for fact in facts:
            owner = fact.course.owner_id
            if owner in admins or owner not in teachers:
                continue
            by_recipient.setdefault(owner, []).append(fact.line)

        sent = 0
        for user_id, lines in by_recipient.items():
            if not lines:
                continue
            try:
                if await self._send_one_report(db, user_id, lines):
                    await db.commit()
                    sent += 1
                else:
                    await db.rollback()
            except Exception:
                await db.rollback()
                logger.exception("SCHET001 週報寄送失敗 user_id=%s", user_id)
        return sent

    async def _send_one_report(self, db: AsyncSession, user_id: str, lines: list[CourseReportLine]) -> bool:
        recipients = await self._notify_repo.active_recipients(db, [user_id])
        if not recipients:
            return False
        recipient = recipients[0]
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_WEEKLY_REPORT,
            recipients=[recipient.email],
            params=build_weekly_report_params(
                recipient_name=recipient.user_name,
                lines=lines,
                csv_url=weekly_report_link(),
            ),
        )
        return result.queued_count > 0

    async def _send_reminds(self, db: AsyncSession, facts: list[_CourseFacts]) -> int:
        """每週未看提醒：**僅**進度 0% 者，一人一信彙整（FR-ET-US14-05）。"""
        by_user: dict[str, list[RemindCourse]] = {}
        for fact in facts:
            entry = RemindCourse(fact.course.course_id, fact.course.course_name, fact.course.open_end_at)
            for user_id in fact.not_started_user_ids:
                by_user.setdefault(user_id, []).append(entry)

        sent = 0
        for user_id, courses in by_user.items():
            try:
                if await self._send_one_remind(db, user_id, courses):
                    await db.commit()
                    sent += 1
                else:
                    await db.rollback()
            except Exception:
                await db.rollback()
                logger.exception("SCHET001 未看提醒寄送失敗 user_id=%s", user_id)
        return sent

    async def _send_one_remind(self, db: AsyncSession, user_id: str, courses: list[RemindCourse]) -> bool:
        recipients = await self._notify_repo.active_recipients(db, [user_id])
        if not recipients:
            return False
        recipient = recipients[0]
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_WEEKLY_REMIND,
            recipients=[recipient.email],
            params=build_weekly_remind_params(user_name=recipient.user_name, courses=courses),
        )
        return result.queued_count > 0


def _days_left(open_end_at: datetime, now: datetime) -> int:
    """距訖止天數（無條件捨去，最小 0）。

    捨去而非四捨五入：剩 1.9 天顯示「1 天」比「2 天」保守，而這是一個催促用的數字。
    """
    return max(0, int((open_end_at - now).total_seconds() // _SECONDS_PER_DAY))
