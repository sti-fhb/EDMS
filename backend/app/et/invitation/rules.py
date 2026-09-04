"""Email 邀請之純業務規則（US8 / #273）。

不碰 DB、不碰 ORM——收件人清單的解析與課程狀態守則都是純函式，故可用 unit test 涵蓋
全部分支（`sti-testing` §integration vs unit 取捨）。
"""

import re
from typing import Final

from app.core.exceptions import AppError
from app.et.constants import COURSE_PUBLISHED

#: 單次可邀請之 Email 數上限。
#:
#: 取與平台 `NotifyService` 收件人上限**相同的值**——本模組雖是逐人一次呼叫（撞不到
#: 平台那道檢核），但教師看到的上限與平台的規模假設各說各話，日後任一邊調整都不會有
#: 人記得另一邊。
#:
#: ⚠️ 這裡**不 import 平台的常數**：那是 `app.dp.notify.service` 的私有符號，跨模組
#: 直接取用違反 `sti-backend-boundaries`（跨模組只走 `app/services`），而為了一個數字
#: 在公開出口加一個匯出也不成比例。兩者是否同步由
#: `tests/unit/et/test_et_invitation_rules.py` 釘住——那是測試，讀得到內部。
MAX_EMAILS_PER_REQUEST: Final[int] = 50

#: 收件人分隔字元：換行、逗號、分號，以及從 Excel / 通訊軟體貼進來常見的全形版本。
_SEPARATORS: Final = re.compile(r"[\s,;，、；]+")

#: Email 格式。刻意保守（不追求 RFC 5322 全集）：這是「教師手貼的清單」，寬鬆比對只會
#: 讓錯字變成一封永遠寄不到的信，而使用者要到 US12 待加入清單才會發現。
_EMAIL_PATTERN: Final = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_INVALID = AppError(status_code=422, detail="Email 格式不正確或數量超過上限", error_code="ET_INVITE_003")


def parse_emails(raw: str) -> list[str]:
    """收件人輸入字串 → 正規化、去重後之 Email 清單。

    教師是從通訊錄 / Excel / 通訊軟體貼進來的，分隔符與大小寫都不固定。

    - 以換行 / 逗號 / 分號（含全形）切分
    - 一律轉小寫（`DP_USER.EMAIL` 以小寫儲存，不正規化會使帳號比對落空）
    - **去重後才計上限**：貼了 60 筆但只有 2 個不同的人不該被擋
    - 保留首次出現順序（預覽以第 1 筆為範例，順序須符合教師預期）

    Args:
        raw: 使用者輸入的整段文字。

    Returns:
        正規化後之 Email 清單；輸入為空白時回空清單（「還沒輸入」不是錯誤，
        由呼叫端決定要不要擋）。

    Raises:
        AppError: 任一筆格式不合法，或去重後仍超過 `MAX_EMAILS_PER_REQUEST`
            （422 `ET_INVITE_003`）。
    """
    tokens = [t for t in _SEPARATORS.split(raw or "") if t]
    seen: dict[str, None] = {}
    for token in tokens:
        email = token.lower()
        if not _EMAIL_PATTERN.match(email):
            raise _INVALID
        seen.setdefault(email, None)
    if len(seen) > MAX_EMAILS_PER_REQUEST:
        raise _INVALID
    return list(seen)


def ensure_invitable(*, course_status: str) -> None:
    """僅「已發布」課程可邀請學員（FR-ET-US8-01）。

    草稿尚無邀請碼、學員端也看不到課程；已關閉課程的學習頁為唯讀，把人邀請進去只會
    讓他點開後什麼都不能做。再開課後 `STATUS` 回 `PUBLISHED`，本檢核自然恢復通過——
    不需要額外的「恢復」邏輯。

    Raises:
        AppError: 課程非已發布（422 `ET_INVITE_004`）。
    """
    if course_status != COURSE_PUBLISHED:
        raise AppError(status_code=422, detail="僅已發布課程可邀請學員", error_code="ET_INVITE_004")
