"""client IP 判定（#23）——safe-by-default，不採信用戶端自稱的來源 IP。

`X-Forwarded-For` 最左段是「用戶端自稱」的來源、可完全偽造。此值同時餵給
速率限制的 IP 維度（`app/core/rate_limit.rate_limit_by_ip`）與稽核日誌
（`AuditLogService.log_action` 的 source_ip）：偽造即可讓每個請求落到不同
限流桶（繞過 IP 維度限流、密碼噴灑不受保護），並污染稽核軌跡、嫁禍他人。

因此預設完全忽略 XFF、一律用連線對端（`request.client.host`，不可偽造）；
僅在部署方明確設定 `TRUSTED_PROXY_COUNT`（應用前方我方代理台數）時，才從
XFF 右側取該代理鏈追加的段落。部署層設定見 `docs/ref/deployment-client-ip.md`。

⚠️ **`TRUSTED_PROXY_COUNT` 必須精確等於實際追加段數**：設定值大於實際段數時
**不是** fail-safe——攻擊者只要自行前置足夠段落把總段數墊到 N 以上，右數第 N 段
就會落在他可控的段落上並被採信（等同原漏洞復活）。設定值小於實際段數則會把
內層代理的 IP 當成 client（全體共用一個限流桶）。兩種誤設都危險。
"""

import ipaddress
from typing import Optional


def _parse_ip(raw: Optional[str]) -> Optional[str]:
    """將單一段落解析為正規化 IP 字串；非合法或不宜落庫者回 None。

    - 容許代理附帶 port 的兩種常見寫法：IPv4 `1.2.3.4:5678`、IPv6 `[::1]:443`
    - 拒絕帶 zone id 的 scoped IPv6（`fe80::1%eth0`）：zone 屬本機語意、對稽核無意義，
      且長度不受控（Python 3.9+ 的 `ip_address` 會接受它）。排除後合法 IPv6 字串最長
      39 字元，落在 `DP_AUDIT_LOG.SOURCE_IP` 的 VARCHAR(45) 內——超長值會在稽核寫入時
      觸發 DataError，而稽核於呼叫方交易內 flush → 整筆操作 500 且不留紀錄（反鑑識）
    - IPv4-mapped IPv6（`::ffff:203.0.113.7`）還原為 IPv4，避免運維用 IPv4 查稽核查不到
    - 正規化（IPv6 縮寫與大小寫）避免同一來源在限流 key 中被算成多個桶
    """
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.startswith("["):  # [IPv6]:port
        value = value[1:].split("]", 1)[0]
    elif value.count(":") == 1:  # IPv4:port（IPv6 至少 2 個冒號，不會被誤切）
        value = value.split(":", 1)[0]
    if "%" in value:
        return None
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped
    return str(parsed)


def resolve_client_ip(*, peer: Optional[str], forwarded_for: Optional[str], trusted_proxy_count: int) -> Optional[str]:
    """判定 client IP：預設用連線對端；設有信任代理時取 XFF 右數第 N 段。

    Args:
        peer: 連線對端 IP（`request.client.host`），不可偽造。
        forwarded_for: `X-Forwarded-For` 的值（多個同名 header 需先依 RFC 7230 以逗號合併）。
        trusted_proxy_count: 應用前方「我方掌控」的反向代理台數（含最靠近 app 的那一台）；
            0 表示應用直接對外，完全忽略 XFF。必須精確等於實際追加段數（見模組 docstring）。

    Returns:
        判定後的 client IP；無法從 XFF 可靠取值時回連線對端（能正規化則正規化，
        否則原樣保留，如測試用的非 IP 對端字串）。

    語意：N 台信任代理會在 XFF 追加 N 段，其中最左那段（即右數第 N 段）才是真實
    client。故 N=1 取最右段、N=2 跳過最內層代理追加的那段。段數不足或該段非合法
    IP 時退回連線對端。
    """
    fallback = _parse_ip(peer) or peer
    if trusted_proxy_count <= 0 or not forwarded_for:
        return fallback
    segments = [seg for seg in (part.strip() for part in forwarded_for.split(",")) if seg]
    if len(segments) < trusted_proxy_count:
        return fallback
    return _parse_ip(segments[-trusted_proxy_count]) or fallback
