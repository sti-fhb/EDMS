"""client IP 解析單元測試（#23）。

驗證 safe-by-default：未設定信任代理時完全忽略 X-Forwarded-For；
設定 TRUSTED_PROXY_COUNT=n 時只採信我方代理鏈追加的那 n 段，
用戶端自行前置的偽造段一律無效。
"""

import pytest

from app.core.client_ip import resolve_client_ip

pytestmark = pytest.mark.unit


def test_ignores_forwarded_for_when_no_trusted_proxy():
    """預設（0 台信任代理）：XFF 完全不採信，一律用連線對端。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="203.0.113.7", trusted_proxy_count=0) == "10.0.0.9"


def test_returns_peer_when_header_absent():
    """有信任代理但無 XFF（如直連健康檢查）：退回連線對端。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for=None, trusted_proxy_count=1) == "10.0.0.9"


def test_single_trusted_proxy_takes_rightmost_segment():
    """1 台信任代理：client IP 為 XFF 最右段（該代理親自追加者）。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="203.0.113.7", trusted_proxy_count=1) == "203.0.113.7"


def test_forged_prefix_cannot_override_client_ip():
    """核心防偽造：用戶端自行前置的段落被忽略，不影響判定結果。"""
    forged = resolve_client_ip(peer="10.0.0.9", forwarded_for="9.9.9.9, 203.0.113.7", trusted_proxy_count=1)
    assert forged == "203.0.113.7"


def test_two_trusted_proxies_skip_inner_proxy():
    """2 台信任代理：跳過最內層代理追加的那段，取右數第 2 段。"""
    assert (
        resolve_client_ip(peer="10.0.0.9", forwarded_for="203.0.113.7, 10.0.0.8", trusted_proxy_count=2)
        == "203.0.113.7"
    )
    assert (
        resolve_client_ip(peer="10.0.0.9", forwarded_for="9.9.9.9, 203.0.113.7, 10.0.0.8", trusted_proxy_count=2)
        == "203.0.113.7"
    )


def test_falls_back_to_peer_when_chain_shorter_than_configured():
    """XFF 段數少於設定的代理台數（設定錯誤或請求繞過代理）：fail-safe 用連線對端。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="203.0.113.7", trusted_proxy_count=2) == "10.0.0.9"


def test_falls_back_to_peer_when_segment_is_not_an_ip():
    """該段不是合法 IP（代理設定錯誤 / 注入嘗試）：不寫入稽核與限流 key，退回連線對端。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="not-an-ip", trusted_proxy_count=1) == "10.0.0.9"
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="unknown", trusted_proxy_count=1) == "10.0.0.9"


def test_strips_port_and_brackets():
    """部分代理會附帶 port：IPv4 去尾 port、IPv6 去方括號，取回純 IP。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="192.0.2.5:41234", trusted_proxy_count=1) == "192.0.2.5"
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="[2001:db8::1]:443", trusted_proxy_count=1) == "2001:db8::1"


def test_normalizes_ipv6_casing():
    """IPv6 大小寫正規化，避免同一來源在限流 key 中被算成兩個桶。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="2001:DB8::1", trusted_proxy_count=1) == "2001:db8::1"


def test_ignores_empty_segments():
    """空白 / 連續逗號段落不計入段數。"""
    assert (
        resolve_client_ip(peer="10.0.0.9", forwarded_for=" , 203.0.113.7 ,, ", trusted_proxy_count=1) == "203.0.113.7"
    )


def test_returns_none_when_peer_unknown():
    """連線對端不明（如 ASGI lifespan / 測試 transport 未帶 client）：回 None，由呼叫端處理。"""
    assert resolve_client_ip(peer=None, forwarded_for=None, trusted_proxy_count=0) is None


def test_count_larger_than_actual_chain_is_forgeable():
    """⚠️ 釘住已知界線：`TRUSTED_PROXY_COUNT` 設過大**不是** fail-safe。

    段數由攻擊者可控（自行前置段落即可墊高），故只要總段數 ≥ N，右數第 N 段就會
    落在攻擊者填的值上並被採信。此行為無法在程式層以「固定段數」模型修掉——
    唯一防線是設定值精確等於實際追加段數（見 docs/ref/deployment-client-ip.md）。
    本測試把行為固定下來，避免日後誤以為此情境已被保護。
    """
    forged = resolve_client_ip(
        peer="10.0.0.9",
        forwarded_for="9.9.9.9, 203.0.113.7",  # 實際只有 1 台代理追加，卻設成 2
        trusted_proxy_count=2,
    )
    assert forged == "9.9.9.9"


def test_rejects_scoped_ipv6():
    """帶 zone id 的 scoped IPv6 不採信：zone 屬本機語意，且長度不受控（超過稽核欄位上限）。"""
    assert resolve_client_ip(peer="10.0.0.9", forwarded_for="fe80::1%eth0", trusted_proxy_count=1) == "10.0.0.9"


def test_unwraps_ipv4_mapped_ipv6():
    """IPv4-mapped IPv6 還原為 IPv4，避免運維以 IPv4 查稽核卻查不到。"""
    assert (
        resolve_client_ip(peer="10.0.0.9", forwarded_for="::ffff:203.0.113.7", trusted_proxy_count=1) == "203.0.113.7"
    )


def test_normalizes_peer_as_well():
    """連線對端也正規化，避免 XFF 路徑與 fallback 路徑寫出不同格式的同一位址。"""
    assert resolve_client_ip(peer="::FFFF:192.0.2.5", forwarded_for=None, trusted_proxy_count=0) == "192.0.2.5"


def test_keeps_non_ip_peer_as_is():
    """非 IP 的對端字串（如某些測試 transport）原樣保留，不因無法解析而變成 None。"""
    assert resolve_client_ip(peer="testclient", forwarded_for=None, trusted_proxy_count=0) == "testclient"
