"""課程邀請信寄送（US8 / #273）。

四條觸發路徑的共同出口：發布時標籤帶入、已發布課程新增標籤、貼標追溯（彙整信）、
教師 Email 邀請。

## 為何必須逐人一封、不能批次

`COURSE_INVITE` 的內文開頭是「{USER_NAME} 您好：」。平台 `send_email` 對整批收件人
**只渲染一次**（同批 params 相同），故 `recipients=[a, b, c]` 會讓三個人收到同一個
名字的信。個人化是規格要求（AC 5「每位被加入學員各收到**一封**通知信」），因此
一位收件人一次呼叫。

⚠️ 這代表掛「全體」標籤的課程發布時，會在該請求內產生 N 次「查範本 + 寫 outbox」。
實際寄送本身仍是非同步的（`DP_EMAIL_LOG` outbox + `dp/notify/worker.py`），符合
FR-ET-US3-03；但排入本身在交易內。若日後成為瓶頸，正解是讓平台 `send_email` 支援
「一次呼叫、逐收件人不同 params」，而不是在 ET 自建第二套佇列——已於 #273 列 follow-up。

## 寄信失敗不影響業務交易

由 `EtNotifier` 統一吞掉 `AppError`（見其 docstring）；本層不再重複 try/except，
但也**不因寄信結果改變任何業務判斷**——回傳的計數僅供稽核 log 與 API 回應顯示。
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtCourse
from app.et.notify.course_invite import (
    build_course_invite_params,
    build_digest_params,
    learn_link,
)
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`），由 #185 之 migration seed。
TEMPLATE_COURSE_INVITE: Final = "COURSE_INVITE"
TEMPLATE_COURSE_INVITE_DIGEST: Final = "COURSE_INVITE_DIGEST"


class CourseInviteMailer:
    """課程邀請 / 彙整通知信之寄送。"""

    def __init__(self, notifier: EtNotifier | None = None, repository: EtNotifyRepository | None = None) -> None:
        self._notifier = notifier or EtNotifier()
        self._repo = repository or EtNotifyRepository()

    async def send_course_invite(
        self,
        db: AsyncSession,
        *,
        course: EtCourse,
        invitation_code: str | None,
        user_ids: Sequence[str],
    ) -> int:
        """對**本次新加入**的學員逐人寄一封 `COURSE_INVITE`。

        Args:
            course: 課程列（取名稱、起訖時間與擁有者）。
            invitation_code: 課程邀請碼；發布當下由呼叫端傳入新產生的碼——`course` 物件
                可能仍是更新前的快照。
            user_ids: 本次真的被加進課程的人（`bulk_enroll_returning` 之結果）。

        Returns:
            成功排入 outbox 的封數（查無 Email 者不計）。
        """
        if not user_ids:
            return 0
        teacher_name = await self._repo.user_name(db, course.owner_id) or ""
        course_url = learn_link(course.course_id)
        queued = 0
        for recipient in await self._repo.recipients(db, user_ids):
            result = await self._notifier.notify(
                db,
                template_code=TEMPLATE_COURSE_INVITE,
                recipients=[recipient.email],
                params=build_course_invite_params(
                    user_name=recipient.user_name,
                    teacher_name=teacher_name,
                    course=course,
                    course_url=course_url,
                    invitation_code=invitation_code,
                ),
            )
            queued += result.queued_count
        return queued

    async def send_digest(self, db: AsyncSession, *, user_id: str, courses: Sequence[EtCourse]) -> int:
        """貼標追溯：對**一位**使用者寄**一封**彙整信（`COURSE_INVITE_DIGEST`）。

        管理者一次貼上的標籤可能對應多門課程，逐課一封會讓當事人同時收到十幾封信
        （FR-ET-US8-05 明定彙整一封）。

        Args:
            courses: 本次補加入之課程；空清單**不寄信**（不寄一封列表為空的信）。

        Returns:
            成功排入 outbox 的封數（0 或 1）。
        """
        if not courses:
            return 0
        recipients = await self._repo.recipients(db, [user_id])
        if not recipients:
            return 0
        recipient = recipients[0]
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_COURSE_INVITE_DIGEST,
            recipients=[recipient.email],
            params=build_digest_params(user_name=recipient.user_name, courses=courses),
        )
        return result.queued_count
