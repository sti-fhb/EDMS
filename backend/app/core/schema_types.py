"""共用 Pydantic 欄位型別。

email 正規化（#35）：一律 `strip + 轉小寫`，使查詢 / 限流 key / 冷卻 key / 儲存一致。
格式檢核沿用既有輕量 regex，**不引 `EmailStr`**（避免 email-validator 依賴，見 US1 決策 / #35）。

前提：email 視為 **ASCII**（EDMS 實務情境）。`to_lower` 底層為 Python `str.lower()`，對少數
Unicode 特殊字元（如土耳其文 `İ`）之小寫規則可能與 Postgres `lower()`（見既有資料 migration）
不完全一致；純 ASCII email 無此問題，屬已知取捨。
"""

from typing import Annotated

from pydantic import BeforeValidator, StringConstraints

# 輕量 email 格式（同 US1/US2 既有 regex；大小寫無關，正規化前後皆適用）
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# 有格式檢核的 email 進入點（註冊 / 忘記密碼 / 重寄 / 管理者邀請）：strip + lower + 格式 + 長度
NormalizedEmailStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=255, pattern=_EMAIL_PATTERN),
]

# 登入 email：僅 strip + lower（**不做格式驗證**——維持「格式錯→認證失敗訊息」而非 422）
LoginEmailStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, max_length=255),
]

# 姓名欄位不得含控制字元或斷行字元（#225）：拒 C0 / DEL / C1 全段 / U+2028 / U+2029（見下方推導）。
#
# 為何要擋：`user_name` 會直接進通知信**內文**（`ACCOUNT_VERIFY` / `ACCOUNT_INVITE` 範本的
# `{user_name}`），而自助註冊端點是**匿名**的——任何人可用他人 Email 送出並自填姓名。姓名若可含
# 換行，攻擊者就能在一封 SPF/DKIM 全正常、來自本組織網域的信裡插入自選文字（例如
# 「【重要】帳號異常，請至 http://evil.tw 處理」），而受害者不需做任何事就會收到。
#
# 為何擋在輸入端而非發信層：姓名**本質單行**，發信層分不出「這個參數該不該有換行」——DM 的退回 /
# 廢止理由就是真的多行使用者輸入（前端為 multiline），在發信層全域剝換行會把它壓平。發信層只做
# 結構性防護（剝 CR 與其餘 C0、保留 LF / TAB，見 `dp/notify/service.py` 的 `_SafeFormatter`）。
#
# 排除範圍以 **stdlib 對「換行」的定義**為準，不自己列字元範圍：`str.splitlines()` 的切點是
# `\n \r \v \f \x1c \x1d \x1e \x85 \u2028 \u2029`，而 Python 的 email 模組正是用同一語意判定
# header 是否含斷行。若只擋 C0 + DEL（本函式的第一版），會漏掉 **U+0085（NEL）/ U+2028 /
# U+2029**——三者在 UAX #14 都是強制換行（class BK），部分郵件用戶端會渲染成真的換行，等於
# 注入防線只做一半。C1 全段（U+0080–U+009F）一併擋：正常姓名不會用到，成本為零。
#
# 刻意不擋的範圍：雙向覆寫（U+202E）與 ZWJ 等格式字元不在此列——那屬顯示欺騙（同形字）的議題、
# 與信件結構無關，且部分書寫系統的正常姓名會用到格式字元，一併擋會誤傷真人姓名。
#
# ⚠️ 本型別**不**消除信件內文注入，只降低其保真度：姓名長度上限 50，攻擊者仍可放入同一行的
# 完整句子（範本內文首行為 `{user_name} 您好：`，故「帳號異常請立即至 http://evil.tw 重設密碼」
# 會渲染成一句看似系統訊息的文字）。真正要消除需改範本設計或不回顯使用者自填姓名，屬產品決策。
#
# 順序：pydantic 先 strip 再驗 pattern（已實測），故前後空白（含換行）維持既有的 strip 行為，
# 只有**內部**的控制字元會被拒。
# 公開常數：長度上限不同、但同樣會進入信件內文的欄位需要重用這條 pattern
# （如 `ET_COURSE.COURSE_NAME`，上限 100——見 `app/et/course/schemas.py`）。
# `SafeNameStr` 只是「這條 pattern + strip + 長度 50」的組合。
# ⚠️ 字元類別抽成 `_UNSAFE_LINE_CHARS` 由兩條 pattern 共用（見下方 `*` 版），理由有二：
# ①兩份手寫會分岔——改了其中一條、另一條悄悄留在舊字元集；
# ②`\u2028` / `\u2029` 若不慎寫成**字面字元**而非跳脫序列，在編輯器與 diff 裡看起來
#   就是兩個空白，下一個人「順手清空白」就會靜默拆掉這道防線。本檔 `*` 版初版正是如此
#   （行為當時仍正確，但原始碼已含隱形字元）。`tests/unit/test_core_schema_types.py`
#   有一條 `isascii()` 守門盯著它。
_UNSAFE_LINE_CHARS = r"\x00-\x1f\x7f-\x9f\u2028\u2029"

SAFE_SINGLE_LINE_PATTERN = rf"^[^{_UNSAFE_LINE_CHARS}]+$"

# 姓名進入點（自助註冊 / 本人改姓名 / 管理者代建與維護）：strip + 長度 + 拒控制字元。
# 長度 50 對齊 `DP_USER.USER_NAME`。管理者輸入的姓名同樣會進邀請信內文，故不因「已認證」而放寬。
SafeNameStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=SAFE_SINGLE_LINE_PATTERN),
]

# ── multipart（`Form()`）欄位專用：允許空值的單行 pattern 與「先 strip」的前置驗證 ──────────
#
# 為何需要第二個 pattern：上面的 `SAFE_SINGLE_LINE_PATTERN` 是 `+`（至少一字元）。DM 編輯器的
# 存草稿路徑**刻意允許空值**——`dm/editor/service.create_document` 的 docstring 明載「存草稿不卡
# 必填（US5）：名稱 / 版號 / 摘要 / 檔案皆可空，送簽時才完整檢核」。把 `+` 版直接掛上去，
# 會讓「新增文件按存草稿」一律 422，而且只有實際點過才看得到。
SAFE_SINGLE_LINE_OR_EMPTY_PATTERN = rf"^[^{_UNSAFE_LINE_CHARS}]*$"

# 多行欄位（摘要 / 理由）用：**只**拒 NUL，換行與 TAB 照常放行。
#
# 為何非擋不可：PostgreSQL 的文字型別存不下 `\x00`——實測寫入會拋 asyncpg 的
# `CharacterNotInRepertoireError`，而 `main.py` 沒有 `DataError` 系列的處理器，於是落到最後的
# catch-all 冒成 **500**。這與「超過 `String(N)` 回 500」是同一類缺陷，只是觸發字元不同；
# 無界 `Text` 欄位不會因長度越界，卻仍會因這一個字元越界。
#
# ⚠️ 刻意**不**沿用 `_UNSAFE_LINE_CHARS`：那一組連 LF 都擋，套到摘要 / 退回理由上會把
# 多行輸入壓成不合法——`SafeNameStr` 的 docstring 已說明「DM 的退回 / 廢止理由就是真的多行
# 使用者輸入」。
SAFE_MULTILINE_PATTERN = r"^[^\x00]*$"


def _strip_if_str(value: object) -> object:
    """字串先去頭尾空白，其餘型別原樣放行（供 `BeforeValidator` 使用）。"""
    return value.strip() if isinstance(value, str) else value


#: 先 strip 再驗的前置驗證器。
#:
#: `StringConstraints(strip_whitespace=True, ...)` 只適用於 Pydantic 模型欄位；FastAPI 的
#: `Form()` 繼承自 `Param`，支援 `max_length` / `pattern` 但**沒有** `strip_whitespace`。
#: 少了它，長度與 pattern 都會驗到「未 strip 的原值」：使用者在文字框尾端多打一個空白，
#: 剛好滿長度的輸入就被判超限；尾端換行則由「今天被靜默 strip」變成 422。
#:
#: 已實測 `BeforeValidator` 先於 `Form()` 的約束執行，故
#: `Annotated[str, STRIP_BEFORE_VALIDATE, Form(max_length=..., pattern=...)]` 的語意是
#: 「strip 後再檢查長度與字元」。
STRIP_BEFORE_VALIDATE = BeforeValidator(_strip_if_str)
