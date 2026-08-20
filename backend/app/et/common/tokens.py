"""ET 邀請 token 產生器（T031）。

僅涵蓋**邀請 token**——密碼重設 / Email 變更驗證 token 屬帳號安全，由平台 DP 產生與
驗證（2026-08-19 裁減，見 issues.md Issue #0）。

ET 不重用 `app/dp/user/token.py`：該模組為 DP 內部實作、未經 `app/services` 公開出口
匯出，跨模組直接 import 違反 sti-backend-boundaries。
"""

import secrets

# ET_INVITATION.TOKEN 為 VARCHAR(64)；token_urlsafe(32) 產出 43 字元，留有餘裕
_TOKEN_BYTES = 32


def generate_invitation_token() -> str:
    """產生 URL-safe 之邀請 token（256 bits 亂數，cryptographically secure）。"""
    return secrets.token_urlsafe(_TOKEN_BYTES)
