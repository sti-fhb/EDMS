"""一次性驗證 token 工具（US3 忘記密碼 / 後續 EMAIL_CHANGE 共用）。

明文 token 僅入信中連結，`DP_PWD_RESET` 表只存其 SHA-256（research §5），故該表外洩無法反推明文。
⚠️ 殘餘風險：信件內文（含明文 reset_link）會以快照存於 `DP_EMAIL_LOG.BODY`（US6 outbox）。
本模組產生之 token 所屬的四種系統信（PWD_RESET / EMAIL_CHANGE_VERIFY / ACCOUNT_VERIFY /
ACCOUNT_INVITE，清單見 `app.dp.notify.redaction.ONE_TIME_LINK_TEMPLATES`）於寄出（SENT）後由
worker 遮罩 BODY、寄送失敗（FAILED）且超過連結時效後由 SCHDP001 遮罩（#50）；但**待寄 / 重試中
（PENDING，重試需原文）與 FAILED 未逾時效的列仍存原文**。
這些列在 token 有效期內讀得到該表者仍可取得可用連結；緩解靠一次性 + 短 TTL
（`LOGIN.RESET_TOKEN_TTL_MIN` / `EMAIL_CHANGE_TTL_MIN` 上限 120 分）。
"""

import hashlib
import secrets


def generate_reset_token() -> str:
    """產生 URL-safe 的一次性明文 token（256 bits 亂數）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """token 明文 → SHA-256 十六進位字串（64 字元，對應 DP_PWD_RESET.TOKEN_HASH）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
