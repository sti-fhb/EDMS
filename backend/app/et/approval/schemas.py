"""線下核可之請求 / 回應 schema（US16 / #352）。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

#: 批次核可時「這一筆沒有寫入」的理由。
#:
#: | 值 | 來源 |
#: |---|---|
#: | `NOT_COMPLETED` | `FR-ET-US16-03` 明訂「對名單中未完課者 MUST 跳過並提示」|
#: | `ALREADY_APPROVED` | SA 裁示 2026-09-17 Q2 = A |
#: | `NOT_ENROLLED` | **SD 自決**（見下）|
#:
#: `ALREADY_APPROVED` 的由來：wireframe 的單列 UI 對已有結果者**只給「撤銷」**（刻意
#: 不讓人直接改判），但已通過那列的勾選框並未停用，批次不通過因此能把「已通過」翻成
#: 「未通過」而不留任何原因、繞過 `FR-ET-US16-06` 的原因必填。
#:
#: `NOT_ENROLLED` 的由來：`tracking.completion_counts_by_student` **不濾在籍**——它數
#: 的是 `ET_PROGRESS` 的列，而移除學員走 `IS_REMOVED`、學習歷史刻意保留。所以一位曾
#: 完課、之後被移除的學員，完課判定仍會成立。少了這道閘會替不在班上的人建核可列，
#: 而他在 US17 核可查詢裡看得到。正常 UI 走不到（清單本來就不列已移除者），這是防繞過
#: 與「載入後才被移除」的競態。
#:
#: 📌 `NOT_ENROLLED` 於 `spec_us16.md` §訊息類型**尚無對應訊息碼**，已列為 SA 同步項。
SkipReason = Literal["NOT_COMPLETED", "ALREADY_APPROVED", "NOT_ENROLLED"]


class SkippedItem(BaseModel):
    """批次中被跳過的一位學員。

    帶 `reason` 而非只回總數——兩種跳過對教師的**下一步不同**（未完課要等他完課，
    已核可要先撤銷並填原因），壓成同一句「已跳過 N 筆」會讓他不知道該做什麼。
    前端據此分別顯示 `ET-MSG-ET03-303` 與 `ET-MSG-ET03-309`。
    """

    user_id: str
    reason: SkipReason


class ApproveReq(BaseModel):
    """核可請求（單筆即 `user_ids` 長度為 1）。

    ## 為何單筆與批次共用同一支端點

    分兩支會讓「跳過」的回應格式有兩種，而那正是最容易分岔的地方——單筆端點若回
    204，前端就無從得知那一筆其實被跳過了。

    ## 為何不收 `version`

    批次的對象多半是「待核可」的學員，他們**根本還沒有 `ET_APPROVAL` 列**，沒有版本號
    可帶。防並發覆寫改由 repository 的條件式 `WHERE` 承擔（見 `repository` 模組
    docstring 的不對稱說明）。
    """

    # ⚠️ `Field(min_length/max_length)` 在 list 上限的是**陣列長度**，不是元素長度。
    # 元素另外標註 `max_length=20` 對齊 `DP_USER.USER_ID VARCHAR(20)` 與撤銷路徑的
    # `Path(max_length=20)`——沒有它的話，100 個各數 MB 的字串會完整進入記憶體、
    # 被塞進兩支查詢的 IN 清單，並**原樣反射**回 `skipped[].user_id`。
    # （本專案未掛 request body 大小限制的 middleware。）
    user_ids: list[Annotated[str, Field(min_length=1, max_length=20)]] = Field(min_length=1, max_length=100)
    result: Literal["PASS", "FAIL"]
    #: 選填備註（如不通過原因、考核情形）。`FR-ET-US16-04` 明訂 FAIL 得附備註；
    #: PASS 亦允許填寫，spec 未限制。
    result_note: str | None = Field(default=None, max_length=1000)


class RevokeReq(BaseModel):
    """撤銷請求。

    `reason` 的必填由 `rules.ensure_revoke_reason` 檢核而非 Pydantic `min_length=1`
    ——後者放行 `"   "`，且驗證失敗回 `COMMON_422` 不帶欄位名，前端無從把
    `ET-MSG-ET03-305` 掛回那個輸入框。此處只擋長度上限。
    """

    reason: str = Field(max_length=1000)
    #: 操作者在畫面上看到的那一版。不符即 409 `ET_APPROVAL_004`。
    version: int = Field(ge=0)


class ApproveResult(BaseModel):
    """核可（含批次）之結果。

    `approved` 與 `skipped` 相加**不一定等於**請求的人數——理論上不會，但若日後新增
    跳過理由而漏了計數，讓兩者相加對不上比悄悄少一筆好查。
    """

    approved: int
    skipped: list[SkippedItem]


class ApprovalRow(BaseModel):
    """一位學員於一門課程的核可事實——供 `tracking` 併進學員清單。

    ⚠️ **不含綜合狀態**：那個值要由完課狀態 × 本列即時導出
    （`rules.derive_approval_status`），而完課狀態只有 `tracking` 那邊算得出來。
    在這裡多開一個 `status` 欄位，等於邀請呼叫端跳過完課判定直接用它——而那正是
    `FR-ET-US16-02`「MUST NOT 另存狀態欄位」要防的事。
    """

    model_config = {"from_attributes": True}

    user_id: str
    result: str
    result_note: str | None
    is_revoked: bool
    revoke_reason: str | None
    approved_by: str
    approved_at: datetime
    version: int
