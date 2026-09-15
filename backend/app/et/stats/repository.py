"""週統計快照之查詢與寫入（US14 / #325）。

`ET_WEEKLY_STAT` 為 **append-only**：只 INSERT，不回頭修改既有快照——它是「那一週當下
長什麼樣」的歷史證據，事後任何資料變動都不該改寫它（同 `attempt` 之閱卷結果不重算）。

⚠️ 本表繼承 `AuditLogBaseModel`，**沒有 `DELETED` 欄位**（append-only 記錄表只有
`CREATED_USER` / `CREATED_DATE`）。照其他 ET 表的慣例補上 `DELETED=0` 會在寫入時拋
`CompileError: Unconsumed column names`，查詢加 `deleted == 0` 則是 `AttributeError`。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import COURSE_PUBLISHED
from app.et.course.models import EtCourse
from app.et.stats.models import EtWeeklyStat
from app.et.stats.rules import CourseStat


class EtStatsRepository:
    """`ET_WEEKLY_STAT` 之讀寫與「開放中課程」母體查詢。"""

    async def open_course_ids(self, db: AsyncSession, now: datetime) -> list[int]:
        """**開放中**課程：已發布且 `now` 落在起訖之間（FR-ET-US14-01）。

        三個條件缺一不可，而漏掉任一個的表徵都是「數字看起來對、母體卻錯了」：

        | 漏掉 | 後果 |
        |---|---|
        | `status == PUBLISHED` | 草稿課程進統計，教師收到一份還沒開的課的週報 |
        | `now >= OPEN_START_AT` | **尚未開始**的課程被統計為「全班未開始」，完課率 0% |
        | `now <= OPEN_END_AT` | 已到期者仍被統計並寄提醒——而 SCHET002 正要把它關掉 |

        `OPEN_START_AT` / `OPEN_END_AT` 為 `NULL` 者一併排除（已發布課程理論上必有兩者，
        但被清空的情況實際存在，見 `schedules/repository` 之說明）。
        """
        rows = await db.scalars(
            select(EtCourse.course_id)
            .where(
                EtCourse.status == COURSE_PUBLISHED,
                EtCourse.open_start_at.is_not(None),
                EtCourse.open_start_at <= now,
                EtCourse.open_end_at.is_not(None),
                EtCourse.open_end_at >= now,
                EtCourse.deleted == 0,
            )
            .order_by(EtCourse.course_id)
        )
        return list(rows.all())

    async def previous_avg_progress(self, db: AsyncSession, *, course_id: int, before: date) -> Decimal | None:
        """該課程**在 `before` 之前**最近一次快照的平均進度；沒有則 `None`（AC 5 的「—」）。

        取「前一筆」而非「上週同一天」：排程時點可調、也可能某週執行失敗，用日期硬算
        會在那種情況下比對到不存在的列而永遠顯示「—」。
        """
        return await db.scalar(
            select(EtWeeklyStat.avg_progress_pct)
            .where(EtWeeklyStat.course_id == course_id, EtWeeklyStat.stat_date < before)
            .order_by(EtWeeklyStat.stat_date.desc())
            .limit(1)
        )

    async def insert_snapshot(
        self, db: AsyncSession, *, course_id: int, stat_date: date, stat: CourseStat, operator: OperatorInfo
    ) -> bool:
        """寫入一筆快照；回傳是否真的由本次寫入。

        `ON CONFLICT DO NOTHING`（唯一鍵 `(COURSE_ID, STAT_DATE)`）：同日重跑不拋例外、
        也**不覆寫**既有快照。append-only 的意思就是那一筆一旦寫下就定案——重跑時課程
        資料可能已經變了，覆寫等於用今天的狀態偽造成當時的快照。
        """
        result = await db.execute(
            pg_insert(EtWeeklyStat)
            .values(
                COURSE_ID=course_id,
                STAT_DATE=stat_date,
                AVG_PROGRESS_PCT=stat.avg_progress_pct,
                CNT_NOT_STARTED=stat.cnt_not_started,
                CNT_IN_PROGRESS=stat.cnt_in_progress,
                CNT_COMPLETED=stat.cnt_completed,
                COMPLETION_RATE=stat.completion_rate,
                CNT_ENROLLED=stat.cnt_enrolled,
                CREATED_USER=operator.user_id,
                CREATED_DATE=utcnow(),
            )
            .on_conflict_do_nothing(constraint="UQ_ET_WEEKLY_STAT_COURSE_DATE")
        )
        return result.rowcount > 0
