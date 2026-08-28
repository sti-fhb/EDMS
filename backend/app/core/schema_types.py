"""共用 Pydantic 欄位型別。

email 正規化（#35）：一律 `strip + 轉小寫`，使查詢 / 限流 key / 冷卻 key / 儲存一致。
格式檢核沿用既有輕量 regex，**不引 `EmailStr`**（避免 email-validator 依賴，見 US1 決策 / #35）。

前提：email 視為 **ASCII**（EDMS 實務情境）。`to_lower` 底層為 Python `str.lower()`，對少數
Unicode 特殊字元（如土耳其文 `İ`）之小寫規則可能與 Postgres `lower()`（見既有資料 migration）
不完全一致；純 ASCII email 無此問題，屬已知取捨。
"""

from typing import Annotated

from pydantic import StringConstraints

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
_SAFE_NAME_PATTERN = r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029]+$"

# 姓名進入點（自助註冊 / 本人改姓名 / 管理者代建與維護）：strip + 長度 + 拒控制字元。
# 長度 50 對齊 `DP_USER.USER_NAME`。管理者輸入的姓名同樣會進邀請信內文，故不因「已認證」而放寬。
SafeNameStr = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=_SAFE_NAME_PATTERN),
]
