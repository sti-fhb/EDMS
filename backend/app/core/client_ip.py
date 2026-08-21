"""client IP 判定（#23）——safe-by-default，不採信用戶端自稱的來源 IP。

`X-Forwarded-For` 最左段是「用戶端自稱」的來源、可完全偽造。此值同時餵給
速率限制的 IP 維度（`app/core/rate_limit.rate_limit_by_ip`）與稽核日誌
（`AuditLogService.log_action` 的 source_ip）：偽造即可讓每個請求落到不同
限流桶（繞過 IP 維度限流、密碼噴灑不受保護），並污染稽核軌跡、嫁禍他人。

因此預設完全忽略 XFF、一律用連線對端（`request.client.host`，不可偽造）；
僅在部署方明確設定 `TRUSTED_PROXY_COUNT`（應用前方我方代理台數）時，才從
XFF 右側取該代理鏈追加的段落。部署層設定見 `docs/ref/deployment-client-ip.md`。
"""

import ipaddress
from typing import Optional


def _parse_ip(raw: str) -> Optional[str]:
    """將 XFF 單一段落解析為正規化 IP 字串；非合法 IP 回 None。

    容許代理附帶 port 的兩種常見寫法：IPv4 `1.2.3.4:5678`、IPv6 `[::1]:443`。
    正規化（如 IPv6 縮寫與大小寫）避免同一來源在限流 key 中被算成多個桶。
    """
    value = raw.strip()
    if not value:
        return None
    if value.startswith("["):  # [IPv6]:port
        value = value[1:].split("]", 1)[0]
    elif value.count(":") == 1:  # IPv4:port（IPv6 至少 2 個冒號，不會被誤切）
        value = value.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def resolve_client_ip(*, peer: Optional[str], forwarded_for: Optional[str], trusted_proxy_count: int) -> Optional[str]:
    """判定 client IP：預設用連線對端；設有信任代理時取 XFF 右數第 N 段。

    Args:
        peer: 連線對端 IP（`request.client.host`），不可偽造。
        forwarded_for: `X-Forwarded-For` header 原始值。
        trusted_proxy_count: 應用前方「我方掌控」的反向代理台數（含最靠近 app 的那一台）；
            0 表示應用直接對外，完全忽略 XFF。

    Returns:
        判定後的 client IP；無法可靠判定時回 `peer`（fail-safe——寧可整組代理後方
        共用一個限流桶，也不讓偽造值打散限流或污染稽核）。

    語意：N 台信任代理會在 XFF 追加 N 段，其中最左那段（即右數第 N 段）才是真實
    client，更左邊的段落皆為用戶端自帶、不可信。故 N=1 取最右段、N=2 跳過最內層
    代理追加的那段。段數不足或該段非合法 IP 時退回 `peer`。
    """
    if trusted_proxy_count <= 0 or not forwarded_for:
        return peer
    segments = [seg for seg in (part.strip() for part in forwarded_for.split(",")) if seg]
    if len(segments) < trusted_proxy_count:
        return peer
    return _parse_ip(segments[-trusted_proxy_count]) or peer
