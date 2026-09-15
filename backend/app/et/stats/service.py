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
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.stats.repository import EtStatsRepository
from app.et.stats.rules import summarize
from app.et.tracking.repository import EtTrackingRepository

logger = logging.getLogger(__name__)

_SYSTEM_OPERATOR: Final = OperatorInfo(user_id="SYSTEM")


class EtStatsService:
    """週統計快照之編排。"""

    def __init__(
        self,
        repository: EtStatsRepository | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        tracking: EtTrackingRepository | None = None,
    ) -> None:
        self._repo = repository or EtStatsRepository()
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._tracking = tracking or EtTrackingRepository()

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
