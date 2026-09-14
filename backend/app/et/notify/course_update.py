"""課程內容更新通知信（ET-13 / US3 補強 / #303）。

教師於**已發布**課程新增章節時，通知所有在籍學員（`spec_us3` 場景 29 /
FR-ET-US3-14）。params 組法與寄送放在同一個模組——這條路徑只有一個觸發點
（`course/service.py::add_chapter`），不像 `COURSE_INVITE` 有四個觸發點需要把
params 組法抽出去共用。

## 範本代碼是 `COURSE_UPDATE`，不是 `ET_NEW_CHAPTER`

`docs/specs/et/issues.md` §Issue #13 的 AC 1 寫「寄送 **ET_NEW_CHAPTER** 通知信」，
但同一條 issue 的 T113、`data-model.md:696`、`contracts/ext-et-email-server.md:105`
三處皆為 **`COURSE_UPDATE`**，實際 seed 進 `DP_NOTIFY_TEMPLATE` 的也是它
（`20260820_1700_c4e8f1a6d372`），且 ET-14 AC 1 明訂 ET 僅有 7 類固定範本、不可由 ET
新增，清單中不含 `ET_NEW_CHAPTER`。以 `COURSE_UPDATE` 為準，`issues.md` 字面待 SA 同步。

## 為何必須逐人一封

`COURSE_UPDATE` 的內文有 `{{USER_NAME}}`，而平台 `send_email` 對整批收件人**只渲染
一次**（同批 params 相同）。`recipients=[a, b, c]` 會讓三個人收到同一個名字的信。
與 `CourseInviteMailer` 同一個理由與同一個作法。

## 通知量

`contracts` 明寫「每次新增即寄」且 `{{NEW_CHAPTER_NAME}}` 為單數——一個章節一封信。
ET02 的新增章節視窗有「儲存並繼續新增」（#203），教師一次建 5 個章節會呼叫 5 次
`add_chapter`；50 位學員的課程即 250 封。規格已如此規定，故不自行改成彙整；若日後
成為問題，`COURSE_INVITE_DIGEST` 是可沿用的前例（已記於 #303 規劃 §12）。
"""

from collections.abc import Sequence
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.et.course.models import EtCourse
from app.et.notify.course_invite import learn_link
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`），由 #185 之 migration seed。
TEMPLATE_COURSE_UPDATE: Final = "COURSE_UPDATE"

#: `COURSE_UPDATE` 之佔位（`contracts/ext-et-email-server.md` §COURSE_UPDATE）。
COURSE_UPDATE_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {
        "USER_NAME",
        "COURSE_NAME",
        "NEW_CHAPTER_NAME",
        "COURSE_URL",
    }
)


def build_course_update_params(*, user_name: str, course: EtCourse, new_chapter_name: str) -> dict[str, str]:
    """組 `COURSE_UPDATE` 之範本參數。

    Args:
        user_name: 收件人顯示名稱（`DP_USER.USER_NAME`）。**不可留空**——範本開頭為
            「{USER_NAME} 您好：」，空字串會渲染成「 您好：」。
        course: 課程列（取 ID 與名稱）。
        new_chapter_name: 本次新增的章節名稱。

    Returns:
        key 與 `COURSE_UPDATE_PARAM_KEYS` 完全一致之 dict（由 unit test 釘住）。
    """
    return {
        "USER_NAME": user_name,
        "COURSE_NAME": course.course_name,
        "NEW_CHAPTER_NAME": new_chapter_name,
        # 收件人**已在課程中**（只寄給在籍學員），故連結是 ET05 學習頁而非邀請頁
        "COURSE_URL": learn_link(course.course_id),
    }


class CourseUpdateMailer:
    """課程內容更新通知信之寄送。"""

    def __init__(self, notifier: EtNotifier | None = None, repository: EtNotifyRepository | None = None) -> None:
        self._notifier = notifier or EtNotifier()
        self._repo = repository or EtNotifyRepository()

    async def send_course_update(
        self, db: AsyncSession, *, course: EtCourse, new_chapter_name: str, user_ids: Sequence[str]
    ) -> int:
        """對在籍學員逐人寄一封 `COURSE_UPDATE`。

        Args:
            course: 課程列（取 ID 與名稱）。
            new_chapter_name: 本次新增的章節名稱。
            user_ids: 在籍學員之 `USER_ID`（呼叫端已過濾 `IS_REMOVED`）。

        Returns:
            成功排入 outbox 的封數（查無 Email 者不計）。

        Notes:
            寄送失敗不拋例外——`EtNotifier` 於唯一出口吞掉 `AppError`（見其 docstring）。
            本層亦**不因寄信結果改變任何業務判斷**：章節已經建立了。
        """
        if not user_ids:
            return 0
        queued = 0
        for recipient in await self._repo.recipients(db, user_ids):
            result = await self._notifier.notify(
                db,
                template_code=TEMPLATE_COURSE_UPDATE,
                recipients=[recipient.email],
                params=build_course_update_params(
                    user_name=recipient.user_name,
                    course=course,
                    new_chapter_name=new_chapter_name,
                ),
            )
            queued += result.queued_count
        return queued
