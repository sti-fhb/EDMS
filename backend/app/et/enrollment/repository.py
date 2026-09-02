"""ET04 選課查詢與寫入（US4 / #247）。

## 我的課程為何一次撈完再於 Python 過濾可見性

可見性判定（`rules.is_listed_in_my_courses`）需要 `now`、課程狀態與 `OPEN_START_AT`
三者，其中「已關閉一律可見、已發布須已到開放時間」不是單一 SQL 述詞能自然表達的
形狀。一名學員的選課數是**個位數到數十**（`ET_ENROLLMENT` 以 `USER_ID` 過濾後），
把判定留在純函式換取「規則只有一份、且有 unit 測試釘住」是划算的。

若日後單一學員的課程數成長到需要分頁，再把「已關閉 OR 已到開放時間」下推成 SQL
述詞——屆時仍應讓 `rules` 保有那份判定，兩邊以測試對齊。
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.operator import OperatorInfo
from app.core.utils import utcnow
from app.dp.users.models import DpUser  # 唯讀 join（報表/查詢例外，已列於 et/spec.md §外模組 table 引用清單）
from app.et.catalog.models import EtCourseTag, EtTag
from app.et.course.models import EtChapter, EtCourse
from app.et.progress.models import EtEnrollment


class EtEnrollmentRepository:
    """`ET_ENROLLMENT` 之查詢與寫入。"""

    async def list_active_enrollments(self, db: AsyncSession, user_id: str) -> list[tuple[EtEnrollment, EtCourse]]:
        """該學員**仍具成員資格**之選課與其課程。

        兩個過濾條件都必要且語意不同：`IS_REMOVED=false` 是成員資格未終止，
        `DELETED=0` 是資料未作廢（見 `EtEnrollment` docstring）。
        """
        rows = await db.execute(
            select(EtEnrollment, EtCourse)
            .join(EtCourse, EtCourse.course_id == EtEnrollment.course_id)
            .where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.is_removed.is_(False),
                EtEnrollment.deleted == 0,
                EtCourse.deleted == 0,
            )
            .order_by(EtEnrollment.joined_at.desc(), EtEnrollment.enrollment_id.desc())
        )
        return [(enrollment, course) for enrollment, course in rows.all()]

    async def tags_by_course(self, db: AsyncSession, course_ids: list[int]) -> dict[int, list[str]]:
        """各課程之受訓單位標籤名稱（AC 3）。

        一次查完再分組，避免每張卡片各發一次查詢。**不濾 `EtTag.is_active`**——
        標籤被停用後，已掛在課程上的標籤仍應顯示，否則卡片會憑空少一個 badge
        而學員無從得知原因。
        """
        if not course_ids:
            return {}
        rows = await db.execute(
            select(EtCourseTag.course_id, EtTag.tag_name)
            .join(EtTag, EtTag.tag_id == EtCourseTag.tag_id)
            .where(
                EtCourseTag.course_id.in_(course_ids),
                EtCourseTag.deleted == 0,
                EtTag.deleted == 0,
            )
            .order_by(EtCourseTag.course_id, EtTag.tag_id)
        )
        grouped: dict[int, list[str]] = {}
        for course_id, tag_name in rows.all():
            grouped.setdefault(course_id, []).append(tag_name)
        return grouped

    async def chapter_counts(self, db: AsyncSession, course_ids: list[int]) -> dict[int, int]:
        """各課程之章節數（AC 3）。"""
        if not course_ids:
            return {}
        rows = await db.execute(
            select(EtChapter.course_id, func.count(EtChapter.chapter_id))
            .where(EtChapter.course_id.in_(course_ids), EtChapter.deleted == 0)
            .group_by(EtChapter.course_id)
        )
        return {course_id: count for course_id, count in rows.all()}

    async def chapter_count(self, db: AsyncSession, course_id: int) -> int:
        """單一課程之章節數（預覽用，AC 6）。"""
        return (
            await db.scalar(
                select(func.count())
                .select_from(EtChapter)
                .where(EtChapter.course_id == course_id, EtChapter.deleted == 0)
            )
            or 0
        )

    async def get_by_invitation_code(self, db: AsyncSession, code: str) -> EtCourse | None:
        """依邀請碼取課程。

        **不在此判斷課程狀態**——「關閉中」與「查無此碼」是兩種不同的回應
        （AC 8 / AC 9），判定屬 `rules.ensure_course_joinable`。
        """
        return await db.scalar(select(EtCourse).where(EtCourse.invitation_code == code, EtCourse.deleted == 0))

    async def owner_name(self, db: AsyncSession, owner_id: str) -> str | None:
        """課程教師姓名（AC 6）。查無回 `None`（比照 DM 之 `author_name`）。

        濾 `DELETED`——本檔其餘查詢皆濾，這裡漏掉會讓已刪除教師的姓名繼續出現在
        預覽畫面。
        """
        return await db.scalar(select(DpUser.user_name).where(DpUser.user_id == owner_id, DpUser.deleted == 0))

    async def get_enrollment(self, db: AsyncSession, *, user_id: str, course_id: int) -> EtEnrollment | None:
        """取該學員於該課程之選課列——**含已被移除者**。

        刻意不濾 `IS_REMOVED`：呼叫端要靠它區分「已加入」（AC 10，正常導航）與
        「曾加入但被移除」（`ET_ENROLL_003`，SA Q1 裁示 C）。濾掉的話兩者都會看起來
        像「沒加入過」，接著 INSERT 撞 `UQ_ET_ENROLLMENT_USER_COURSE` 變成 500。
        """
        return await db.scalar(
            select(EtEnrollment).where(
                EtEnrollment.user_id == user_id,
                EtEnrollment.course_id == course_id,
                EtEnrollment.deleted == 0,
            )
        )

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: str,
        course_id: int,
        join_source: str,
        completion_status: str,
        joined_at: datetime,
        operator: OperatorInfo,
    ) -> EtEnrollment:
        """建立選課列。

        `LAST_ACTIVITY_AT` 留 `None`——加入不是學習動作，寫入會讓 US9 的「最後活動
        時間」欄位對從未進過課程的學員顯示加入時間。
        """
        enrollment = EtEnrollment(
            user_id=user_id,
            course_id=course_id,
            join_source=join_source,
            joined_at=joined_at,
            completion_status=completion_status,
            is_removed=False,
            created_user=operator.user_id,
            created_date=utcnow(),
        )
        db.add(enrollment)
        await db.flush()
        return enrollment
