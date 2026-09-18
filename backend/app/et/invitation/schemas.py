"""Email 邀請之請求 / 回應 schema（US8 / #273）。"""

from datetime import datetime

from pydantic import BaseModel, Field

#: 收件人輸入框的整段文字上限。50 筆 × 254（Email 長度上限）+ 分隔符仍有餘裕；
#: 設上限是為了讓超長貼上在 Pydantic 就被擋下，而非走完 regex 再拒絕。
_RAW_EMAILS_MAX_LEN = 16_000

#: `secrets.token_urlsafe(32)` 產出 43 字元；留餘裕但仍擋掉明顯的灌大字串。
_TOKEN_MAX_LEN = 128


class EmailInviteReq(BaseModel):
    """教師輸入的 Email 清單（整段文字，後端負責切分）。

    **不在此拆成 `list[str]`**：分隔符可能是換行 / 逗號 / 分號（含全形），拆分規則屬
    業務規則、由 `rules.parse_emails` 一處決定；schema 只管「是一段不太離譜的文字」。
    """

    emails: str = Field(min_length=1, max_length=_RAW_EMAILS_MAX_LEN)


class InvitePreview(BaseModel):
    """寄送預覽（唯讀）。

    `subject` / `body` 由平台範本渲染而來，教師**不可編輯**（FR-ET-US8-07：範本由管理者
    於 DP 後台統一維護）。前端據此以唯讀欄位呈現。

    **不回傳收件人範例或筆數**：預覽以 `PREVIEW_NAME_MASK` 取代收件人姓名、以 `…` 取代
    token，內容因此與「這次要寄給誰」完全無關——回傳收件人資訊只會讓教師以為預覽是
    針對某一位產生的。筆數前端自己算得出來（同一套 `parseEmails` 規則）。
    """

    subject: str
    body: str


class EmailInviteResult(BaseModel):
    """邀請結果（#362：邀請即加入）。

    ## 🔴 `joined` 與 `mail_failed` 是兩件事，刻意分開

    原欄位是 `sent`（寄信封數）+ `failed`，因為當時「加入」還要等對方點連結，寄信
    成功與否幾乎等同於邀請成功與否。**#362 之後不是了**——加入在寄信之前就完成，
    所以「已加入但信沒寄出」是一個真實的結果組合。

    合成一個數字會讓教師以為「沒寄出 ＝ 沒加入」，而那個人其實已經在學員清單裡；
    ⚠️ 而且「待加入」清單移除後**沒有重寄的途徑**（US12 的補救隨功能一起消失），
    教師只能從 DP 的通知紀錄查寄信結果。故兩個欄位都必須讓他看到。

    `mail_failed` 為**排入 outbox 失敗**者（範本停用 / 渲染失敗）；真實 SMTP 結果於此
    刻尚不可知（平台為 outbox 架構），故不代表「對方收不到」。
    """

    #: 實際加入此課程的人數（AC 5：與學員清單一致）。已在課程中者亦計入——他們在
    #: 清單上，教師看到的數字必須對得上那份清單。
    joined: int
    #: 加入成功但信件**排入 outbox 失敗**者之 Email。
    mail_failed: list[str]


class InviteAcceptReq(BaseModel):
    """受邀者點擊連結後送出的 token。"""

    token: str = Field(min_length=1, max_length=_TOKEN_MAX_LEN)


class InviteAcceptResult(BaseModel):
    """加入結果——供前端導向 ET05 學習頁。

    `already_joined=true` 代表「本來就在課程中」（AC 8：不重複加入、直接導向），
    非錯誤。
    """

    course_id: int
    course_name: str
    already_joined: bool


class PendingInviteRow(BaseModel):
    """ET-12 待加入清單的一列（`FR-ET-US12-01`）。

    ## 時間欄回 `LAST_SENT_AT`，不回 `SENT_AT`

    Wireframe 的欄位標題寫「邀請寄出日」，但教師按下「再次寄送」後若畫面日期不變，
    他會以為沒寄出去而重複點。`SENT_AT`（首次寄出）本 issue 不回——需要時再加。

    ## `status` 恆為 `PENDING`，仍照 spec 回

    清單已過濾為只有待加入者，故本欄目前是常數。`FR-ET-US12-01` 明訂欄位須含邀請
    狀態，且日後若清單擴及其他狀態不必改結構。
    """

    model_config = {"from_attributes": True}

    invitation_id: int
    email: str
    #: 最近一次寄出時間（再次寄送會更新）。
    last_sent_at: datetime
    status: str
