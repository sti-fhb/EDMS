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
