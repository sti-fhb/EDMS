"""一次性驗證 token 工具（US3 忘記密碼 / 後續 EMAIL_CHANGE 共用）。

明文 token 僅入信中連結，`DP_PWD_RESET` 表只存其 SHA-256（research §5），故該表外洩無法反推明文。
⚠️ 殘餘風險：寄出的信件內文（含明文 reset_link）會以快照存於 `DP_EMAIL_LOG.BODY`（US6 outbox），
在 token 有效期內具可用性——此為 outbox 架構取捨，敏感信 body 之遮罩 / 清除與存取控管另立 follow-up。
"""

import hashlib
import secrets


def generate_reset_token() -> str:
    """產生 URL-safe 的一次性明文 token（256 bits 亂數）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """token 明文 → SHA-256 十六進位字串（64 字元，對應 DP_PWD_RESET.TOKEN_HASH）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
