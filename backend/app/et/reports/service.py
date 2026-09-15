"""週報逐學員明細 CSV（T164 / US14 / #325）。

## 範圍由**呼叫者自己的角色**決定，不由參數決定

| 呼叫 | 範圍 |
|---|---|
| 不帶 `course_id` | 管理者 → 全部開放中課程；教師 → 自己擁有的開放中課程 |
| 帶 `course_id` | 該課程；教師須為其 `OWNER_ID`，否則 403 |

不帶 `course_id` 的那條是週報信裡 `{REPORT_CSV_URL}` 用的——範本只有一個佔位，而一份
週報涵蓋多門課程，故產出的 CSV 必須與收件人在信中看到的摘要範圍一致。

## 內容於請求當下即時產生

FR-ET-US14-11 (3) 明訂非寄信當下之凍結檔，故可能與信中摘要有時間差（範本內文已註明
此點）。因此本模組**不讀 `ET_WEEKLY_STAT`**——那是快照，讀它會變成「凍結檔」。

## 課程關閉後仍可下載

FR-ET-US14-11 (4)：連結不另設有效期，授權由登入與角色把關。故帶 `course_id` 的路徑
**不檢查課程是否開放中**——教師課程結束後要調歷史明細是正常需求。
"""

import csv
import io
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csv_export import sanitize_csv_cell
from app.core.exceptions import AppError
from app.et.constants import COMPLETION_COMPLETED, COMPLETION_IN_PROGRESS, COMPLETION_NOT_STARTED
from app.et.deps import EtContext
from app.et.enrollment.repository import EtEnrollmentRepository
from app.et.enrollment.rules import derive_completion_status
from app.et.notify.course_invite import format_open_at
from app.et.notify.repository import EtNotifyRepository
from app.et.progress.repository import completion_pct
from app.et.reports.repository import EtReportsRepository
from app.et.roles.authz import ET_ADMIN
from app.et.stats.repository import EtStatsRepository
from app.et.tracking.repository import EtTrackingRepository

_CSV_HEADERS: Final = ["課程名稱", "姓名", "Email", "進度%", "完課狀態", "最後活動時間"]

#: 三態代碼 → 中文。CSV 是給人看的，不是 API 回應。
_STATUS_LABEL: Final[dict[str, str]] = {
    COMPLETION_NOT_STARTED: "未開始",
    COMPLETION_IN_PROGRESS: "進行中",
    COMPLETION_COMPLETED: "已完課",
}

_NOT_FOUND: Final = AppError(status_code=404, detail="查無此課程", error_code="ET_COURSE_001")
_FORBIDDEN: Final = AppError(status_code=403, detail="僅課程擁有者可下載", error_code="ET_COURSE_002")


class EtReportsService:
    """週報明細之產生與授權。"""

    def __init__(
        self,
        repository: EtReportsRepository | None = None,
        stats: EtStatsRepository | None = None,
        enrollments: EtEnrollmentRepository | None = None,
        tracking: EtTrackingRepository | None = None,
        notify_repo: EtNotifyRepository | None = None,
    ) -> None:
        self._repo = repository or EtReportsRepository()
        self._stats = stats or EtStatsRepository()
        self._enrollments = enrollments or EtEnrollmentRepository()
        self._tracking = tracking or EtTrackingRepository()
        self._notify_repo = notify_repo or EtNotifyRepository()

    async def weekly_csv(self, db: AsyncSession, *, ctx: EtContext, course_id: int | None) -> str:
        """產生逐學員明細 CSV（UTF-8 文字，BOM 由 router 補）。"""
        courses = await self._scope(db, ctx=ctx, course_id=course_id)
        buf = io.StringIO()
        writer = csv.writer(buf)  # csv 模組處理逗號 / 換行 / 引號跳脫，禁手拼
        writer.writerow(_CSV_HEADERS)
        for course in courses:
            for row in await self._rows(db, course):
                writer.writerow(row)
        return buf.getvalue()

    async def _scope(self, db: AsyncSession, *, ctx: EtContext, course_id: int | None):
        """依角色與參數決定要輸出哪些課程。"""
        if course_id is not None:
            course = await self._repo.course_for_report(db, course_id)
            if course is None:
                raise _NOT_FOUND
            # 404 用於「不存在」，403 用於「存在但不是你的」——此處 id 由使用者持有
            # （來自他自己的週報連結），不構成可用來枚舉全站課程的訊號
            if ET_ADMIN not in ctx.roles and course.owner_id != ctx.user_id:
                raise _FORBIDDEN
            return [course]

        open_courses = await self._stats.open_courses(db, self._repo.now())
        if ET_ADMIN in ctx.roles:
            return open_courses
        return [c for c in open_courses if c.owner_id == ctx.user_id]

    async def _rows(self, db: AsyncSession, course) -> list[list[str]]:
        """一門課的逐學員列。

        全部即時計算：進度與完課狀態經 `completion_pct` / `derive_completion_status`，
        與 ET03 頁面、週報摘要**同一組函式**。讀 `ET_ENROLLMENT.COMPLETION_STATUS` 會
        讓整份 CSV 的完課狀態全部變成「未開始」。
        """
        user_ids = await self._enrollments.enrolled_user_ids(db, course.course_id)
        if not user_ids:
            return []
        counts = await self._tracking.completion_counts_by_student(db, course_id=course.course_id, user_ids=user_ids)
        last_activity = await self._repo.last_activity_by_student(db, course_id=course.course_id)
        by_user = {r.user_id: r for r in await self._notify_repo.recipients(db, user_ids)}
        names = await self._tracking.user_names(db, set(user_ids))

        rows = []
        for user_id in user_ids:
            done, total = counts.get(user_id, (0, 0))
            recipient = by_user.get(user_id)
            rows.append(
                [
                    sanitize_csv_cell(course.course_name),
                    sanitize_csv_cell(names.get(user_id) or user_id),
                    # 查無 Email 者留空而非略過整列——那位學員仍在籍、進度仍要呈現
                    sanitize_csv_cell(recipient.email if recipient else ""),
                    str(completion_pct(done, total)),
                    _STATUS_LABEL[derive_completion_status(done=done, total=total)],
                    format_open_at(last_activity.get(user_id)),
                ]
            )
        return rows
