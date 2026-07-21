"""一次性驗證 token 工具（US3 忘記密碼 / 後續 EMAIL_CHANGE 共用）。

明文 token 僅存在於信中連結，DB 只存其 SHA-256（research §5）——即使 DB 外洩也無法反推明文。
"""

import hashlib
import secrets


def generate_reset_token() -> str:
    """產生 URL-safe 的一次性明文 token（256 bits 亂數）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """token 明文 → SHA-256 十六進位字串（64 字元，對應 DP_PWD_RESET.TOKEN_HASH）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
