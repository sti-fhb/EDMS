"""Email 邀請之請求 / 回應 schema（US8 / #273）。"""

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
