"""週報明細之查詢（T164 / US14 / #325）。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import utcnow
from app.et.course.models import EtCourse
from app.et.progress.models import EtEnrollment
from app.et.stats.repository import OpenCourse


class EtReportsRepository:
    """明細 CSV 所需之課程與活動時間查詢。"""

    def now(self) -> datetime:
        """目前時間——單獨成一支供測試注入，避免 service 直接綁 `utcnow`。"""
        return utcnow()

    async def course_for_report(self, db: AsyncSession, course_id: int) -> OpenCourse | None:
        """取單一課程之報表欄位；不存在或已軟刪回 `None`。

        **不檢查是否開放中**：FR-ET-US14-11 (4) 明訂連結不另設有效期，課程關閉後仍可
        下載歷史明細——教師在課程結束後調明細是正常需求。

        回傳型別與 `stats.open_courses` 相同，讓 service 的兩條路徑（單課 / 範圍）之後
        的處理完全一致。
        """
        row = (
            await db.execute(
                select(EtCourse.course_id, EtCourse.course_name, EtCourse.owner_id, EtCourse.open_end_at).where(
                    EtCourse.course_id == course_id, EtCourse.deleted == 0
                )
            )
        ).first()
        return OpenCourse(*row) if row else None

    async def last_activity_by_student(self, db: AsyncSession, *, course_id: int) -> dict[str, datetime | None]:
        """`{user_id: 最後活動時間}`（`ET_ENROLLMENT.LAST_ACTIVITY_AT`）。

        **不是**「最後一次測驗提交時間」——該欄由進度上報與作答提交共同維護，涵蓋只看
        教材、沒有任何測驗的課程；只看 attempt 會讓那類課程整欄空白。
        """
        rows = await db.execute(
            select(EtEnrollment.user_id, EtEnrollment.last_activity_at).where(
                EtEnrollment.course_id == course_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
            )
        )
        return {user_id: last for user_id, last in rows.all()}
