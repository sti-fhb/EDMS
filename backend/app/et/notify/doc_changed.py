"""引用之 DM 文件改版 / 廢止通知（#231）。

收件人為**課程擁有者**（教師），一位擁有者一封、多門課程彙整於 `COURSE_LIST`。

## 兩個範本不合併

改版與廢止的**處置不同**：改版是「去確認測驗題還對不對」（學員已經在讀新內容），
廢止是「移除引用或換一份，否則這門課再發布會被 `BLOCK_OBSOLETE_DOC` 擋下」。
合成一封帶狀態欄位的通用信，教師讀不出該做哪件事。

## 為何收件人用 `active_recipients` 而非 `recipients`

本通知由排程週期性觸發，沒有任何「使用者剛做了什麼」作為前提。依
`EtNotifyRepository.active_recipients` 的 docstring：停用的帳號擋得住 API、擋不住信，
週期性的信只要角色列還在就會一直寄下去。事件觸發的信才用 `recipients`。

⚠️ params key 須與 `20261012_1600_e8b4c2f17a93` 所 seed 之 `VARIABLES` **逐字一致**。
平台 `_SafeFormatter` 在 key 對不上時會 KeyError → 寄出空信並記 FAILED、
`queued_count=0` 且**不外拋**，症狀是「信沒到但程式沒錯」。
"""

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.et.notify.repository import EtNotifyRepository
from app.et.notify.service import EtNotifier

#: `DP_NOTIFY_TEMPLATE.TEMPLATE_CODE`（`MODULE='ET'`），由 `e8b4c2f17a93` seed。
TEMPLATE_DOC_VERSION_CHANGED: Final = "DOC_VERSION_CHANGED"
TEMPLATE_DOC_OBSOLETED: Final = "DOC_OBSOLETED"

#: 兩範本之佔位（與 seed 的 `VARIABLES` 逐字一致）。
DOC_VERSION_CHANGED_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {"USER_NAME", "DOC_ID", "DOC_NAME", "VERSION_NO", "COURSE_LIST", "COURSE_URL"}
)
DOC_OBSOLETED_PARAM_KEYS: Final[frozenset[str]] = frozenset(
    {"USER_NAME", "DOC_ID", "DOC_NAME", "COURSE_LIST", "COURSE_URL"}
)


def courses_link() -> str:
    """ET01 課程列表連結。

    ⚠️ 刻意指向**列表**而非單一課程：一封信可能涵蓋多門課（`COURSE_LIST`），
    放單一課程的網址會與信的內容矛盾。
    """
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/et/courses"


def format_course_list(course_names: list[str]) -> str:
    """多門課程 → 信中可讀的一行。

    排序後再組：同一批課程在不同次執行中若順序飄移，收件人會以為內容變了。
    """
    return "、".join(sorted(course_names))


class DocChangedMailer:
    """改版 / 廢止通知之寄送。"""

    def __init__(self, notifier: EtNotifier | None = None, repo: EtNotifyRepository | None = None) -> None:
        self._notifier = notifier or EtNotifier()
        self._repo = repo or EtNotifyRepository()

    async def send_version_changed(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        doc_id: str,
        doc_name: str,
        version_no: str,
        course_names: list[str],
    ) -> int:
        """寄「引用文件改版」。回傳 `queued_count`（0 ＝ 未寄出）。"""
        return await self._send(
            db,
            template_code=TEMPLATE_DOC_VERSION_CHANGED,
            owner_id=owner_id,
            extra={"DOC_ID": doc_id, "DOC_NAME": doc_name, "VERSION_NO": version_no},
            course_names=course_names,
        )

    async def send_obsoleted(
        self,
        db: AsyncSession,
        *,
        owner_id: str,
        doc_id: str,
        doc_name: str,
        course_names: list[str],
    ) -> int:
        """寄「引用文件廢止」。回傳 `queued_count`（0 ＝ 未寄出）。"""
        return await self._send(
            db,
            template_code=TEMPLATE_DOC_OBSOLETED,
            owner_id=owner_id,
            extra={"DOC_ID": doc_id, "DOC_NAME": doc_name},
            course_names=course_names,
        )

    async def _send(
        self,
        db: AsyncSession,
        *,
        template_code: str,
        owner_id: str,
        extra: dict[str, str],
        course_names: list[str],
    ) -> int:
        recipients = await self._repo.active_recipients(db, [owner_id])
        if not recipients:
            # 擁有者已停用 / 已刪除 / 無 Email——不是錯誤，但也沒有人可通知。
            # 回 0 使呼叫端**不前進簿記**：日後該帳號恢復時仍會收到當前狀態的通知。
            return 0
        owner = recipients[0]
        params = {
            "USER_NAME": owner.user_name or owner.user_id,
            "COURSE_LIST": format_course_list(course_names),
            "COURSE_URL": courses_link(),
            **extra,
        }
        result = await self._notifier.notify(db, template_code=template_code, recipients=[owner.email], params=params)
        return result.queued_count
