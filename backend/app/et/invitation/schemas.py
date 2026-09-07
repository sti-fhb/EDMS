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
    """寄出結果。

    `failed` 為**排入 outbox 失敗**者（範本停用 / 渲染失敗）；真實 SMTP 結果於此刻
    尚不可知（平台為 outbox 架構），故不代表「對方收不到」。見 `service.py` 說明。
    """

    sent: int
    failed: list[str]


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
