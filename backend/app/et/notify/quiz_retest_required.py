"""測驗變更需重新測驗通知（`QUIZ_RETEST_REQUIRED`；US3 / US6 / #361）。

教師變更測驗內容並選擇「要求已通過的學員重新測驗」時，對每位受影響的學員各寄一封。

⚠️ **逐人一封、不合批**：範本內文含 `{USER_NAME}`，而平台 `send_email` 對整批收件人
**只渲染一次**——合批會讓所有人收到同一個名字的信。與 `ApprovalPassedMailer` /
`CourseUpdateMailer` 同一個理由與同一個作法。
"""

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtCourse
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`），由 #361 之 migration seed。
TEMPLATE_QUIZ_RETEST_REQUIRED: Final = "QUIZ_RETEST_REQUIRED"

#: `QUIZ_RETEST_REQUIRED` 之佔位，須與 `DP_NOTIFY_TEMPLATE.VARIABLES` **逐字一致**。
#:
#: 🔴 對不上不會拋例外：平台 `_SafeFormatter` 會 KeyError → 寄出空信、記 FAILED、
#: `queued_count=0`，而呼叫端什麼也看不到。改任一邊都要同步改 migration。
QUIZ_RETEST_REQUIRED_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "USER_NAME",
        "COURSE_NAME",
        "QUIZ_NAME",
        "COURSE_URL",
    }
)


def build_quiz_retest_params(*, user_name: str, course: EtCourse, quiz_name: str, course_url: str) -> dict[str, str]:
    """組 `QUIZ_RETEST_REQUIRED` 的渲染參數。

    Args:
        user_name: 收件學員姓名（渲染於稱謂）。
        course: 課程列（取名稱）。
        quiz_name: 被變更的測驗名稱。
        course_url: 學習連結。

    Returns:
        與 `QUIZ_RETEST_REQUIRED_PARAM_KEYS` 同鍵的字典。
    """
    return {
        "USER_NAME": user_name,
        "COURSE_NAME": course.course_name,
        "QUIZ_NAME": quiz_name,
        "COURSE_URL": course_url,
    }


class QuizRetestRequiredMailer:
    """對受影響學員寄送「請重新測驗」通知。"""

    def __init__(self, repo: EtNotifyRepository | None = None, notifier: EtNotifier | None = None) -> None:
        self._repo = repo or EtNotifyRepository()
        self._notifier = notifier or EtNotifier()

    async def send_quiz_retest_required(
        self, db: AsyncSession, *, course: EtCourse, quiz_name: str, course_url: str, user_id: str
    ) -> int:
        """對單一學員寄一封 `QUIZ_RETEST_REQUIRED`。

        Args:
            course: 課程列（取名稱）。
            quiz_name: 被變更的測驗名稱。
            course_url: 學習連結。
            user_id: 受影響學員之 `USER_ID`。

        Returns:
            成功排入 outbox 的封數（0 或 1；查無 Email 者回 0）。

        Notes:
            **寄送失敗不拋例外、也不改變任何業務判斷**——重置已經寫進去了，那是業務
            事實；信只是通知。學員下次進課程就會看到該測驗回到未通過狀態。

            比照 `ApprovalPassedMailer`：這與 ET-12 `resend()` 寄信失敗要回滾的不對稱
            是刻意的——那裡 token 已被換掉，不回滾會毀掉一條還能用的連結。
        """
        recipients = await self._repo.recipients(db, [user_id])
        if not recipients:
            return 0
        recipient = recipients[0]
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_QUIZ_RETEST_REQUIRED,
            recipients=[recipient.email],
            params=build_quiz_retest_params(
                user_name=recipient.user_name,
                course=course,
                quiz_name=quiz_name,
                course_url=course_url,
            ),
        )
        return result.queued_count
