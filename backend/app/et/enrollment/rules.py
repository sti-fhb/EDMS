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
from app.et.constants import (
    COMPLETION_COMPLETED,
    COMPLETION_IN_PROGRESS,
    COMPLETION_NOT_STARTED,
    COURSE_CLOSED,
    COURSE_PUBLISHED,
)
from app.et.course.publish_rules import is_visible_to_student

#: 邀請碼長度（`ET_COURSE.INVITATION_CODE` 為 `VARCHAR(8)`）。
INVITATION_CODE_LENGTH: Final = 8

#: 邀請碼樣式：**ASCII** 數字。不可用 `str.isdigit()`——它對全形數字回 `True`
#: （`int("１")` 也吃），會讓全形碼一路查到 DB 才查無。
#:
#: 明確帶 `\A` / `\Z` 錨點，正確性就不依賴呼叫端記得用 `fullmatch`——若有人改成
#: `.match()`，沒有錨點的話 `"12345678abc"` 會通過，前 8 碼流進 DB 查詢。
_CODE_PATTERN: Final = re.compile(rf"\A[0-9]{{{INVITATION_CODE_LENGTH}}}\Z")

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

    ⚠️ **本函式不看 `OPEN_END_AT`，全後端目前也沒有任何地方看它**（它只用於顯示與
    發布檢核）。閱課期間結束後若 `STATUS` 仍是 `PUBLISHED`，課程依然可加入、也依然
    留在我的課程清單。spec 說「到期自動關閉」，但自動關閉屬 `ET-11`（未實作）——
    到期的執行點目前不存在，不是散落在別處。`ET-11` 設計時須決定「期間結束 = 不可
    加入」要落在這裡還是靠自動 `CLOSED`，別因為這裡查不到就假設有人已經做了。

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


def derive_completion_status(progress_pct: int) -> str:
    """由學習進度百分比導出完課三態（`data-model` §ET_ENROLLMENT：「**即時計算**」）。

    | `progress_pct` | 三態 |
    |---|---|
    | `0` | `NOT_STARTED` |
    | `1`–`99` | `IN_PROGRESS` |
    | `100` | `COMPLETED` |

    ## 為何即時計算而不維護儲存欄位

    `ET_ENROLLMENT.COMPLETION_STATUS` 在 #284 之前**只有加入課程時寫入的
    `NOT_STARTED`**，沒有任何路徑推進它——於是「我的課程」上方的四項統計永遠顯示
    全部「未開始」。#274 的 issue body 寫了要做完課判定，但那句話不在它的 15 條 AC
    內，所以 AC 逐條盤點與收尾摘要都沒抓到。

    補法有兩條，選了即時計算（#284 SA Q2 裁示 A）：進度變動的入口有**三個**
    （`progress` 的區段上報、`items/{id}/viewed`、`attempt` 的提交），維護儲存值就得
    在三處同步更新，漏掉任一個就產生「查詢查得到的」與「頁面看到的」不一致——而那
    正是 `data-model` 選「即時計算」要避開的問題。

    ⚠️ **`COMPLETION_STATUS` 與 `COMPLETED_AT` 兩個儲存欄位自此永遠停在初始值**
    （裁示 A：留著標記不使用、不加 migration）。日後 `ET-9`（完課率）、`ET-16`
    （週報）、`ET-16` 之線下核可前提檢核（`data-model` §ET_APPROVAL 明寫「僅當
    `COMPLETION_STATUS = COMPLETED` 時可寫入核可」）一律**不得讀那兩個欄位**——
    直接 `WHERE COMPLETION_STATUS = 'COMPLETED'` 會得到零筆，而且不會報錯。

    Args:
        progress_pct: 完成項目數 ÷ 總項目數（見
            `progress.repository.completion_pct_by_course`）。沒有任何項目的課程回
            `0` 而非 100——空課程按字面定義是 vacuous truth，但那會讓學員剛加入就看到
            課後問卷入口；且發布檢核強制 ≥1 章節 + ≥1 教材，已發布課程走不到那裡。
    """
    if progress_pct >= 100:
        return COMPLETION_COMPLETED
    if progress_pct <= 0:
        return COMPLETION_NOT_STARTED
    return COMPLETION_IN_PROGRESS


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
