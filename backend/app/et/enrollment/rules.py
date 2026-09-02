"""ET04 加入課程與我的課程清單之純業務規則（US4 / #247）。

**完全不碰 DB**：邀請碼格式、加入資格、清單可見性三件事都能以純函式表達，故全部
以 unit test 涵蓋，integration 只驗接線與 DB 寫入。

## 為何清單可見性不直接用 `publish_rules.is_visible_to_student`

`is_visible_to_student` 問的是「學員能否**開始學習**」——它對 `CLOSED` 回 `False`。
但 AC 5 / AC 13 明訂已關閉課程**要出現在我的課程清單**並可唯讀回看。兩者是不同的
問題，故本模組以 `is_listed_in_my_courses` 表達清單語意，並在其中**呼叫**前者處理
「已發布」那一側——不重寫那條規則（它有 5 條 unit 測試釘著邊界），也不改動它
（改了會讓發布檢核跟著變）。
"""

import re
from datetime import datetime
from typing import Final

from app.core.exceptions import AppError
from app.et.constants import COURSE_CLOSED, COURSE_PUBLISHED
from app.et.course.publish_rules import is_visible_to_student

#: 邀請碼長度（`ET_COURSE.INVITATION_CODE` 為 `VARCHAR(8)`）。
INVITATION_CODE_LENGTH: Final = 8

#: 邀請碼樣式：**ASCII** 數字。不可用 `str.isdigit()`——它對全形數字回 `True`
#: （`int("１")` 也吃），會讓全形碼一路查到 DB 才查無。
_CODE_PATTERN: Final = re.compile(rf"[0-9]{{{INVITATION_CODE_LENGTH}}}")

_CODE_INVALID = AppError(status_code=404, detail="邀請碼無效，請確認後重試", error_code="ET_ENROLL_001")


def normalize_invitation_code(raw: str) -> str | None:
    """正規化邀請碼；格式不符回 `None`（AC 5）。

    僅去除前後空白——使用者從通訊軟體複製邀請碼時常帶空白，那不是輸入錯誤。
    中間的空白 / 換行不予容忍：那已經不是「一組碼」了。
    """
    candidate = raw.strip()
    return candidate if _CODE_PATTERN.fullmatch(candidate) else None


def ensure_course_joinable(*, course_status: str) -> None:
    """課程當前狀態是否允許加入（AC 9 / ET-MSG-ET04-002）。

    判定依據是**課程當前狀態**而非碼是否存在——邀請碼於課程關閉期間失效、
    再開課後恢復有效（`spec_us4` Clarifications），碼本身自始至終不變。

    Raises:
        AppError: 409 `ET_ENROLL_002` 課程關閉中；404 `ET_ENROLL_001` 非已發布課程。
    """
    if course_status == COURSE_CLOSED:
        raise AppError(status_code=409, detail="此課程目前關閉中", error_code="ET_ENROLL_002")
    if course_status != COURSE_PUBLISHED:
        # 邀請碼於發布時才產生，草稿課程照理取不到碼；真的走到這裡只可能是資料異常。
        # 回 404 而非「關閉中」——後者等於向未受邀者確認「有這麼一門課，只是還沒開」。
        raise _CODE_INVALID


def ensure_not_removed(*, is_removed: bool) -> None:
    """被教師移除之學員不可自行重新加入（#247 SA Q1 裁示 C）。

    必須在**應用層**明確擋下：若放它掉進 INSERT，會撞
    `UQ_ET_ENROLLMENT_USER_COURSE` 而變成 500，且衝突對象是一筆學員在前台看不見的
    列，錯誤訊息對他毫無意義。

    移除是教師的管理動作（US9 AC 22 明訂被移除者不計入完課率分母），若學員能用同一
    組碼立刻回來，該動作形同虛設。重新加入須由教師重新邀請（`ET-8`）。

    Raises:
        AppError: 409 `ET_ENROLL_003`。
    """
    if is_removed:
        raise AppError(
            status_code=409,
            detail="您已被移除出此課程，如需重新加入請聯繫教師",
            error_code="ET_ENROLL_003",
        )


def is_listed_in_my_courses(*, status: str, open_start_at: datetime | None, now: datetime) -> bool:
    """課程是否出現在學員的「我的課程」清單（AC 4 / AC 5）。

    - **已發布**：委由 `is_visible_to_student` 判定（須 `now >= OPEN_START_AT`）；
      起始時間未到者不顯示（AC 4）。
    - **已關閉**：一律顯示（AC 5 / AC 13）——卡片標「已關閉」，點擊可唯讀回看。
      `open_start_at` 不影響結果：課程能被關閉，必然已經發布並開放過。
    """
    if status == COURSE_CLOSED:
        return True
    return is_visible_to_student(status=status, open_start_at=open_start_at, now=now)
