"""一次性驗證 token 工具（US3 忘記密碼 / 後續 EMAIL_CHANGE 共用）。

明文 token 僅入信中連結，`DP_PWD_RESET` 表只存其 SHA-256（research §5），故該表外洩無法反推明文。
⚠️ 殘餘風險：信件內文（含明文 reset_link）會以快照存於 `DP_EMAIL_LOG.BODY`（US6 outbox）。
PWD_RESET / EMAIL_CHANGE_VERIFY 於寄出（SENT）後由 worker 遮罩 BODY（#50），但**待寄 / 重試中
（PENDING，重試需原文）與寄送失敗（FAILED，SA 裁示保留）的列仍存原文**。
另外本模組產生的 token 也用於 ACCOUNT_VERIFY（註冊啟用）/ ACCOUNT_INVITE（邀請）——持有連結者
可為未啟用帳號設定密碼（帳號接管），但兩者不在 #50 裁示範圍，**SENT 後仍存原文**，待 SA 裁示。
上述列在 token 有效期內讀得到該表者仍可取得可用連結；緩解靠一次性 + 短 TTL
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
