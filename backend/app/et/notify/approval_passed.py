"""核可通過通知信（US16 / #352）。

教師 / 管理者於 ET03 對學員線下核可「**通過**」時寄出；**不通過與撤銷不寄**
（`FR-ET-US16-08`）。

## 本模組是 `APPROVAL_PASSED` 的第一個也是唯一的引用點

該範本於 `c4e8f1a6d372`（#185）就已 seed 進 `DP_NOTIFY_TEMPLATE`，但在本 issue 之前
**全 codebase 沒有任何地方寄過它**。也就是說沒有既有行為可以參照——params 的 key 若
打錯，平台 `_SafeFormatter` 會拋 `KeyError` → 整批寫 `DP_EMAIL_LOG.STATUS='FAILED'`、
`queued_count=0` 且**不外拋**，呼叫端看起來一切正常，只是沒有人收到信。key 集合由
`tests/unit/et/test_et_approval_mail.py` 釘死。

## 為何用 `recipients()` 而非 `active_recipients()`

核可是**事件觸發**的信（教師剛按下按鈕），不是週期性的。`active_recipients` 那支多濾
一道帳號狀態，是為了擋「離職者的信箱無限期每週收到全站統計」；事件信只在當下寄一次、
且以一個明確動作為前提，濾掉會出現「核可了 3 個人卻只寄 2 封」而無人知道少了誰——與
`recipients()` docstring 所述的取捨相同。
"""

from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtCourse
from app.et.notify.course_invite import format_open_at
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`），由 #185 之 migration seed。
TEMPLATE_APPROVAL_PASSED: Final = "APPROVAL_PASSED"

#: `APPROVAL_PASSED` 之佔位（`DP_NOTIFY_TEMPLATE.VARIABLES` 與
#: `contracts/ext-et-email-server.md` §APPROVAL_PASSED）。
APPROVAL_PASSED_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "USER_NAME",
        "COURSE_NAME",
        "APPROVED_BY_NAME",
        "APPROVED_AT",
    }
)

#: 核可人姓名查無（帳號已刪）時的替代值。空字串會讓內文變成「已由  核可通過」。
_UNKNOWN_APPROVER: Final = "系統管理者"


def build_approval_passed_params(
    *, user_name: str, course: EtCourse, approved_by_name: str, approved_at: datetime
) -> dict[str, str]:
    """組 `APPROVAL_PASSED` 之範本參數。

    Args:
        user_name: 收件學員的顯示名稱（`DP_USER.USER_NAME`）。範本開頭為
            「{USER_NAME} 您好：」。
        course: 課程列（取名稱）。
        approved_by_name: 核可人姓名；查無時傳空字串，本函式以 `系統管理者` 替代。
        approved_at: 核可時間（`TIMESTAMPTZ`）。**本函式負責換算與格式化**，
            呼叫端不要先轉字串。

    Returns:
        key 與 `APPROVAL_PASSED_PARAM_KEYS` 完全一致之 dict（由 unit test 釘住），
        且所有值皆為 `str`。

    ## 時間沿用 `format_open_at`

    直接輸出 UTC 會讓信裡的核可時間比教師在 ET03 看到的**早 8 小時**。共用
    `course_invite.format_open_at` 而不另寫一份：那支已對齊前端
    `utils/date.ts::formatDateTime` 的 `YYYY/MM/DD HH:mm`，兩份遲早分岔，而分岔的表現
    是同一個時間在畫面與信件上長得不一樣。
    """
    return {
        "USER_NAME": user_name,
        "COURSE_NAME": course.course_name,
        "APPROVED_BY_NAME": approved_by_name or _UNKNOWN_APPROVER,
        "APPROVED_AT": format_open_at(approved_at),
    }


class ApprovalPassedMailer:
    """核可通過通知信之寄送。"""

    def __init__(self, notifier: EtNotifier | None = None, repository: EtNotifyRepository | None = None) -> None:
        self._notifier = notifier or EtNotifier()
        self._repo = repository or EtNotifyRepository()

    async def send_approval_passed(
        self, db: AsyncSession, *, course: EtCourse, approved_by_name: str, approved_at: datetime, user_id: str
    ) -> int:
        """對單一學員寄一封 `APPROVAL_PASSED`。

        Args:
            course: 課程列（取名稱）。
            approved_by_name: 核可人姓名（呼叫端查一次即可，批次時不必逐人查）。
            approved_at: 本次核可時間。
            user_id: 受核可學員之 `USER_ID`。

        Returns:
            成功排入 outbox 的封數（0 或 1；查無 Email 者回 0）。

        Notes:
            **逐人一封、不合批**：`FR-ET-US16-05` 明訂批次核可「逐一寫入並各自套用通知
            規則」，且範本內文含 `{USER_NAME}`，而平台 `send_email` 對整批收件人**只渲染
            一次**——合批會讓所有人收到同一個名字的信。與 `CourseUpdateMailer` 同一個
            理由與同一個作法。

            寄送失敗不拋例外（`EtNotifier` 於唯一出口吞掉 `AppError`），**本層亦不因寄信
            結果改變任何業務判斷**：核可已經寫進去了，那是業務事實；信只是通知，學員仍
            可於 ET10 核可查詢（US17）看到結果。這與 ET-12 `resend()` 寄信失敗要回滾的
            不對稱是刻意的——那裡 token 已被換掉，不回滾會毀掉一條還能用的連結。
        """
        recipients = await self._repo.recipients(db, [user_id])
        if not recipients:
            return 0
        recipient = recipients[0]
        result = await self._notifier.notify(
            db,
            template_code=TEMPLATE_APPROVAL_PASSED,
            recipients=[recipient.email],
            params=build_approval_passed_params(
                user_name=recipient.user_name,
                course=course,
                approved_by_name=approved_by_name,
                approved_at=approved_at,
            ),
        )
        return result.queued_count
