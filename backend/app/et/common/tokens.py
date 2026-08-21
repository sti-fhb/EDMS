"""ET 邀請 token 產生器（T031）。

僅涵蓋**邀請 token**——密碼重設 / Email 變更驗證 token 屬帳號安全，由平台 DP 產生與
驗證（2026-08-19 裁減，見 issues.md Issue #0）。

ET 不重用 `app/dp/user/token.py`：該模組為 DP 內部實作、未經 `app/services` 公開出口
匯出，跨模組直接 import 違反 sti-backend-boundaries。
"""

import hashlib
import secrets

# ET_INVITATION.TOKEN 為 VARCHAR(64)；token_urlsafe(32) 產出 43 字元，留有餘裕
_TOKEN_BYTES = 32


def generate_invitation_token() -> str:
    """產生 URL-safe 之邀請 token 明文（256 bits 亂數，cryptographically secure）。

    **明文僅入信中連結、不落庫**——DB 只存 `hash_token()` 之結果
    （比照平台 `app/dp/user/token.py` + `DP_PWD_RESET.TOKEN_HASH`：該表外洩無法反推明文）。
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """token 明文 → SHA-256 十六進位字串（64 字元，對應 `ET_INVITATION.TOKEN_HASH`）。

    驗證時將收到的明文重新雜湊後比對，而非反向解密。跨模組不可 import DP 之同名函式
    （sti-backend-boundaries），故於此重實作。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
