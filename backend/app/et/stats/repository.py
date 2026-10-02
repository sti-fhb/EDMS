"""週統計快照之查詢與寫入（US14 / #325）。

`ET_WEEKLY_STAT` 為 **append-only**：只 INSERT，不回頭修改既有快照——它是「那一週當下
長什麼樣」的歷史證據，事後任何資料變動都不該改寫它（同 `attempt` 之閱卷結果不重算）。

⚠️ 本表繼承 `AuditLogBaseModel`，**沒有 `DELETED` 欄位**（append-only 記錄表只有
`CREATED_USER` / `CREATED_DATE`）。照其他 ET 表的慣例補上 `DELETED=0` 會在寫入時拋
`CompileError: Unconsumed column names`，查詢加 `deleted == 0` 則是 `AttributeError`。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.et.constants import COURSE_DRAFT, COURSE_PUBLISHED
from app.et.course.models import EtChapter, EtCourse, EtItem
from app.et.progress.models import EtEnrollment, EtProgress
from app.et.stats.models import EtWeeklyStat
from app.et.stats.rules import CourseStat


class OpenCourse(NamedTuple):
    """開放中課程之週報所需欄位（純值，不是 ORM 實體——理由見 `open_courses`）。"""

    course_id: int
    course_name: str
    owner_id: str
    open_end_at: datetime


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

    async def open_courses(self, db: AsyncSession, now: datetime) -> list[OpenCourse]:
        """開放中課程之 `(id, 名稱, 擁有者, 訖止)`——週報渲染所需的欄位。

        **回純值而非 ORM 實體**：週報的寄送階段逐人 commit，而 `commit()` / `rollback()`
        會讓已載入的實體過期，下一圈存取屬性即觸發 lazy refresh 而死於 `MissingGreenlet`
        （同 `schedules/repository` 的說明）。讀階段一次取完轉成純值，寄階段就與 session
        狀態無關。
        """
        rows = await db.execute(
            select(EtCourse.course_id, EtCourse.course_name, EtCourse.owner_id, EtCourse.open_end_at)
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
        return [OpenCourse(*row) for row in rows.all()]

    # ── 首頁儀表板（#453 / #89 的 P3）────────────────────────────────────────

    async def courses_ending_soon(
        self, db: AsyncSession, *, owner_id: str, now: datetime, urgent_days: int
    ) -> list[OpenCourse]:
        """**該教師自己**開放中且即將截止的課程，訖止近者在前。

        母體與 `open_courses` 相同（已發布、`now` 落在起訖之間、兩個時間皆非 `NULL`），
        多兩個條件：

        - `OWNER_ID == owner_id`——教師卡只呈現他自己的課。非擁有者的課出現在這裡等於
          把別人班級的落後狀況攤給他看，而他對那門課什麼都做不了。
        - 訖止落在 `now + urgent_days` 之內。

        ⚠️ **`urgent_days` 由呼叫端傳入且必須是 `ET_URGENT_REMIND_DAYS`**（`DP_PARAM`），
        不可在此寫死：首頁與加急提醒信若用不同門檻，會出現「首頁說要注意了、信還沒寄」
        或反過來，而兩者都宣稱依據同一條規則。
        """
        deadline = now + timedelta(days=urgent_days)
        rows = await db.execute(
            select(EtCourse.course_id, EtCourse.course_name, EtCourse.owner_id, EtCourse.open_end_at)
            .where(
                EtCourse.owner_id == owner_id,
                EtCourse.status == COURSE_PUBLISHED,
                EtCourse.open_start_at.is_not(None),
                EtCourse.open_start_at <= now,
                EtCourse.open_end_at.is_not(None),
                EtCourse.open_end_at >= now,
                EtCourse.open_end_at <= deadline,
                EtCourse.deleted == 0,
            )
            .order_by(EtCourse.open_end_at)
        )
        return [OpenCourse(*row) for row in rows.all()]

    async def draft_count(self, db: AsyncSession, owner_id: str) -> int:
        """該教師建立但**尚未發布**的課程數（學員完全看不到它們）。

        不含已關閉：那些發布過、學員看得到過，不屬於「卡在我這」。
        """
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtCourse)
                .where(
                    EtCourse.owner_id == owner_id,
                    EtCourse.status == COURSE_DRAFT,
                    EtCourse.deleted == 0,
                )
            )
        ) or 0

    def _completion_base(self, now: datetime):
        """全站「每一筆在籍 × 是否完課」的基底查詢（管理者卡專用）。

        ## 🔴 完課**必須即時推導**，不可讀 `ET_ENROLLMENT.COMPLETION_STATUS`

        那一欄只在建立選課列時寫一次 `NOT_STARTED`，**全專案沒有任何 update 寫它**
        （`enrollment/service` 自己的註解也載明「由 counts 即時導出，不讀
        `enrollment.completion_status`」）。拿它彙總會讓完成率**恆為 0%**，而畫面上
        完全看不出異常——欄位存在、型別正確、數字合理。

        故完課 = 該課未刪項目數 `total > 0` 且該學員已完成項目數 `done >= total`，
        與 `progress.completion_counts_by_course` / `enrollment.rules.is_course_completed`
        同一個定義。

        ## ⚠️ 三個 join 全是「多對一」，不會灌大計數

        `enrollment → course`、`→ 項目總數`、`→ 已完成數` 對一筆在籍而言各自至多一列
        （後兩者已先 `GROUP BY` 收斂）。**這裡刻意不 join 任何一對多**——兩個一對多放在
        同一個 `GROUP BY` 就是笛卡兒積，算出偏大但看起來合理的數字。

        ⚠️ 唯一出現過一對多的是 #453 的 `unit_rates`（依單位分組，須 join `ET_USER_TAG`），
        它已於 #475 改為 `course_rates`，**本檔現在沒有任何一對多**。詳見 `course_rates`
        的 docstring——那裡說明了為什麼不可照抄舊的 join 形狀。

        母體排除草稿：學員根本看不到，計入會讓完成率被永遠學不了的課稀釋。
        """
        totals = (
            select(EtChapter.course_id.label("course_id"), func.count(EtItem.item_id).label("total"))
            .select_from(EtItem)
            .join(EtChapter, EtChapter.chapter_id == EtItem.chapter_id)
            .where(EtItem.deleted == 0, EtChapter.deleted == 0)
            .group_by(EtChapter.course_id)
            .subquery()
        )
        dones = (
            select(
                EtProgress.course_id.label("course_id"),
                EtProgress.user_id.label("user_id"),
                func.count().label("done"),
            )
            .where(EtProgress.is_completed.is_(True), EtProgress.deleted == 0)
            .group_by(EtProgress.course_id, EtProgress.user_id)
            .subquery()
        )
        done_col = func.coalesce(dones.c.done, 0)
        return (
            select(
                EtCourse.course_id.label("course_id"),
                EtCourse.course_name.label("course_name"),
                EtCourse.open_end_at.label("open_end_at"),
                case((and_(totals.c.total > 0, done_col >= totals.c.total), 1), else_=0).label("is_completed"),
            )
            .select_from(EtEnrollment)
            .join(EtCourse, EtCourse.course_id == EtEnrollment.course_id)
            .join(totals, totals.c.course_id == EtEnrollment.course_id)
            .outerjoin(
                dones,
                and_(dones.c.course_id == EtEnrollment.course_id, dones.c.user_id == EtEnrollment.user_id),
            )
            .where(
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
                EtCourse.deleted == 0,
                EtCourse.status != COURSE_DRAFT,
            )
        )

    async def overall_completion(self, db: AsyncSession, now: datetime) -> tuple[int, int, int]:
        """全站 `(在籍人次, 已完課人次, 逾期未完課人次)`。

        「逾期」＝課程訖止已過（`OPEN_END_AT < now`）且該學員未完課。`OPEN_END_AT` 為
        `NULL` 者不算逾期——沒有期限就無從逾期，計入會把「永遠開放的課」全數打成逾期。
        """
        base = self._completion_base(now).subquery()
        row = (
            await db.execute(
                select(
                    func.count().label("enrolled"),
                    func.coalesce(func.sum(base.c.is_completed), 0).label("completed"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        base.c.open_end_at.is_not(None),
                                        base.c.open_end_at < now,
                                        base.c.is_completed == 0,
                                    ),
                                    1,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("overdue"),
                ).select_from(base)
            )
        ).one()
        return int(row.enrolled), int(row.completed), int(row.overdue)

    async def course_rates(self, db: AsyncSession, now: datetime) -> list[tuple[str, int, int]]:
        """依**課程**分組之 `(課程名稱, 在籍人次, 已完課人次)`（#475）。

        ## 與 `_completion_base` 的關係：這裡沒有任何一對多

        一筆在籍只屬一門課程，故本查詢是純粹的分組聚合——**不像 #453 的各單位達成率
        那樣引入 `ET_USER_TAG` 的一對多**。因此 `_completion_base` 依舊維持全多對一，
        而本方法也不需要為笛卡兒積做任何防備。

        ⚠️ 正因如此，**不可照抄舊 `unit_rates` 的 join 形狀**：那裡的 `EtUserTag` join
        是刻意的一對多（一人屬多單位，各單位各自算自己的人），搬過來會把同一筆在籍
        算進多門課。

        ## 排除 `IS_ALL` 的那段說明不再適用

        #453 的各單位達成率要排除「全體」標籤（它不逐人建 `ET_USER_TAG` 列，直接 join
        會顯示 0 人）。改為課程分組後完全沒有標籤參與，該段已隨之移除——留著會指向
        一個不存在的 join。

        母體仍由 `_completion_base` 排除草稿課程（學員看不到，計入會稀釋完成率）。
        """
        base = self._completion_base(now).subquery()
        rows = await db.execute(
            select(
                base.c.course_name,
                func.count().label("enrolled"),
                func.coalesce(func.sum(base.c.is_completed), 0).label("completed"),
            )
            .select_from(base)
            # 以 `course_id` 分組而非名稱——同名課程是可能的（不同年度的年度訓練），
            # 用名稱分組會把它們合併成一列，數字偏大且看起來合理。
            .group_by(base.c.course_id, base.c.course_name)
        )
        return [(r.course_name, int(r.enrolled), int(r.completed)) for r in rows.all()]

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
