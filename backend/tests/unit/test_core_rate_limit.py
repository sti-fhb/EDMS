"""速率限制（T015）純單元測試：滑動視窗 + IP dependency（注入 now，不連 DB）。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core import rate_limit as rate_limit_module
from app.core.exceptions import AppError
from app.core.rate_limit import SlidingWindowCounter, SlidingWindowRateLimiter, ip_bucket, rate_limit_by_ip
from app.core.request_context import set_client_ip

pytestmark = pytest.mark.unit


def test_init_rejects_non_positive_args():
    """建構子拒絕非正數門檻 / 視窗（防限流器被誤設為失效或永久拒絕）。"""
    with pytest.raises(ValueError, match="必須為正數"):
        SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
    with pytest.raises(ValueError, match="必須為正數"):
        SlidingWindowRateLimiter(max_requests=1, window_seconds=0)


def test_allows_within_limit():
    """視窗內未達上限皆放行。"""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("k", now=100.0)  # 同一瞬間 3 次剛好達上限、皆放行


def test_rejects_over_limit():
    """達上限後再一次 → 429 COMMON_429。"""
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.hit("k", now=100.0)
    with pytest.raises(AppError) as exc:
        limiter.hit("k", now=100.0)
    assert exc.value.status_code == 429
    assert exc.value.error_code == "COMMON_429"


def test_window_slides_allows_again():
    """視窗滑動後（舊時間戳過期）重新放行。"""
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.hit("k", now=100.0)
    limiter.hit("k", now=100.0)
    with pytest.raises(AppError):
        limiter.hit("k", now=130.0)  # 仍在視窗內（100~160）→ 拒
    limiter.hit("k", now=161.0)  # 前兩筆（100）已滑出視窗 → 放行


def test_keys_are_independent():
    """不同 key 各自獨立計數。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.hit("a", now=100.0)
    limiter.hit("b", now=100.0)  # 不受 a 影響
    with pytest.raises(AppError):
        limiter.hit("a", now=100.0)


def test_rejected_hit_not_counted():
    """被拒的請求不佔用配額：視窗滑動後仍以原始有效筆數計算。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    limiter.hit("k", now=100.0)
    for _ in range(5):
        with pytest.raises(AppError):
            limiter.hit("k", now=120.0)  # 連續被拒，不應累加
    # 首筆（100）滑出後應立即放行，證明被拒的 5 次未被記錄
    limiter.hit("k", now=161.0)


def test_sweep_reclaims_stale_keys():
    """一次性 key 於視窗過期後應被 sweep 回收，outer dict 不無限成長。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60)
    # 觸發一次 sweep 前先塞遠早於視窗的一次性 key，sweep 時應全數清掉
    for i in range(1500):
        limiter.hit(f"acct:user{i}", now=100.0 + i * 0.001)
    # 再前進到讓上述所有時間戳都滑出視窗，並持續 hit 直到跨過 sweep 週期
    for i in range(1500):
        limiter.hit(f"acct:late{i}", now=100_000.0 + i * 0.001)
    # 早期一次性 key 應已被 sweep 回收（不再殘留），outer dict 有界（遠小於 3000 總 key）
    assert not any(k.startswith("acct:user") for k in limiter._hits)
    assert len(limiter._hits) < 3000


def test_max_keys_hard_cap_fail_closed():
    """達 outer dict 硬上限且無可回收桶時，新 key 一律拒絕（界定記憶體上界）。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60, max_keys=3)
    # 3 個各自仍在視窗內的 key 填滿字典
    for i in range(3):
        limiter.hit(f"k{i}", now=100.0)
    # 第 4 個新 key：sweep 無可回收（全在視窗內）→ fail-closed 429
    with pytest.raises(AppError) as exc:
        limiter.hit("k3", now=100.0)
    assert exc.value.status_code == 429
    # 既有 key 仍可正常計數（未被硬上限誤擋）
    limiter.hit("k0", now=100.0)


async def test_rate_limit_by_ip_dependency():
    """IP dependency 依 get_client_ip 組 key，超限拋 429。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip("1.2.3.4")
    try:
        await dep()  # 首次放行
        with pytest.raises(AppError) as exc:
            await dep()
        assert exc.value.status_code == 429
    finally:
        set_client_ip(None)


async def test_rate_limit_by_ip_unknown_client():
    """無 client IP（get_client_ip 回 None）時以 fallback key 計數，不拋錯。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip(None)
    await dep()
    with pytest.raises(AppError):
        await dep()


async def test_scope_prefix_isolates_endpoints():
    """同一 IP、不同 scope 各自獨立配額（scope 前綴防污染）。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    login_dep = rate_limit_by_ip(limiter, scope="login")
    forgot_dep = rate_limit_by_ip(limiter, scope="forgot-password")
    set_client_ip("1.2.3.4")
    try:
        await login_dep()
        await forgot_dep()  # 不同 scope，不受 login 影響
        with pytest.raises(AppError):
            await login_dep()
    finally:
        set_client_ip(None)


async def test_dependency_resolves_in_fastapi_app():
    """回歸測試：dependency 掛上真實 FastAPI 路由能正常解析（非 422），並實際限流。"""
    import httpx
    from fastapi import Depends, FastAPI

    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(rate_limit_by_ip(limiter, scope="ping"))])
    async def ping():
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/ping")
        second = await client.get("/ping")
    assert first.status_code == 200  # 非 422：dependency 正確解析、未被當成 query 參數
    assert second.status_code == 429


# ── SlidingWindowCounter（#234 抽出）────────────────────────────────────────
# ⚠️ 本組刻意直接測 counter 而非只靠 limiter 間接帶到：三個性質與 limiter **方向相反**
#   （不拋、fail-open、上限由呼叫端決定），靠 limiter 的測試一條都驗不到。
#   2026-10-14 code review MEDIUM-4 指出此缺口。


def test_counter_count_不新增_key():
    """`count` 必須無副作用。

    原本的 `_hits` 是 defaultdict——照抄 `self._hits[key]` 會在 `max_keys` 檢查**之前**
    憑空建桶，等於讓任何人以不重複的 key 繞過記憶體上界。
    """
    counter = SlidingWindowCounter(window_seconds=60)
    assert counter.count("nobody", now=100.0) == 0
    assert "nobody" not in counter._hits, "count 不得建立 key"


def test_counter_視窗過期後歸零():
    """滾動視窗：時間推進超過 window 後，舊紀錄不再計入。

    #234 的「每日上限」靠的就是這個性質，而整合測試從不推進時間
    （`now` 無法自 router 注入），少了本條則「滾動」這個承諾零覆蓋。
    """
    counter = SlidingWindowCounter(window_seconds=60)
    for i in range(3):
        assert counter.try_record("k", now=100.0 + i)
    assert counter.count("k", now=150.0) == 3
    # 邊界：now=161 時 cutoff=101，第三筆（102）仍在視窗內 ⇒ 還剩 1。
    # 這一條順便釘住「滑出是逐筆的、不是整桶丟掉」。
    assert counter.count("k", now=161.0) == 1
    assert counter.count("k", now=163.0) == 0, "全部滑出後歸零（額度於 24 小時後釋放）"


def test_counter_key_空間滿時_fail_open():
    """與 limiter **刻意相反**：滿時回 False 而不拋，呼叫端照常放行。

    拋 429 會讓 `/register` 多出一種回應（新的列舉面）；fail-closed 則讓大量不同 Email
    的嘗試把表塞滿、反而使正常註冊被拒（以 DoS 換 DoS）。
    """
    counter = SlidingWindowCounter(window_seconds=60, max_keys=2)
    assert counter.try_record("a", now=100.0)
    assert counter.try_record("b", now=100.0)
    assert counter.try_record("c", now=100.0) is False, "滿時回 False"
    assert counter.count("c", now=100.0) == 0, "未被記錄 ⇒ 不佔額度，呼叫端視為未達上限"


# ─────────────────────────────────────────────────────────────────────────────
# IP 分桶收斂（#198）
# ─────────────────────────────────────────────────────────────────────────────


def test_ipv6_同一_64_內不同位址落入同一桶():
    """持有一個 /64 的攻擊者不能靠換位址取得新配額。

    /64 是 VPS、行動網路、家用固網的標配配額，換位址不需偽造任何 header。
    """
    a = ip_bucket("2001:db8:1:2::1")
    b = ip_bucket("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert a == b, "同一 /64 內的位址必須同桶"


def test_ipv6_不同_64_落入不同桶():
    """收斂到 /64 而非更寬——不同 /64 仍是不同來源，不可互相拖累。"""
    assert ip_bucket("2001:db8:1:2::1") != ip_bucket("2001:db8:1:3::1")


def test_ipv4_維持_32_不同位址不同桶():
    """⛔ IPv4 刻意不收斂（SA 2026-10-29 裁示）。

    收到 /24 會把 NAT 後方整批使用者當成同一個人——院內網路與行動網路都是共用出口。
    而取得一個 IPv4 /24 的成本與取得一個 IPv6 /64 差好幾個量級，威脅結構不同。
    """
    assert ip_bucket("203.0.113.1") != ip_bucket("203.0.113.2")
    assert ip_bucket("203.0.113.1") == "203.0.113.1", "IPv4 原樣，便於排查時直接比對"


def test_ipv4_mapped_的_ipv6_視為_ipv4():
    """`::ffff:1.2.3.4` 是 IPv4 位址的 IPv6 表示法，收斂成 /64 會把整個 IPv4 空間併成一桶。"""
    assert ip_bucket("::ffff:203.0.113.1") != ip_bucket("::ffff:203.0.113.2")


def test_無法解析的來源原樣回傳():
    """`unknown`（無 client IP 時的 fallback）與任何非法字串都不得讓限流炸掉。"""
    assert ip_bucket("unknown") == "unknown"
    assert ip_bucket("") == ""


async def test_rate_limit_by_ip_以_64_分桶():
    """dependency 層級的驗證：同 /64 的兩個位址共用同一份配額。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip("2001:db8:aa:bb::1")
    try:
        await dep()  # 首次放行
        set_client_ip("2001:db8:aa:bb::9999")  # 同 /64，換位址
        with pytest.raises(AppError) as exc:
            await dep()
        assert exc.value.status_code == 429, "換位址不得取得新配額"
    finally:
        set_client_ip(None)


async def test_rate_limit_by_ip_不同_64_各自計數():
    """正向錨點：收斂不得過寬，不同 /64 必須各有配額。"""
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
    dep = rate_limit_by_ip(limiter, scope="login")
    set_client_ip("2001:db8:aa:bb::1")
    try:
        await dep()
        set_client_ip("2001:db8:aa:cc::1")  # 另一個 /64
        await dep()  # 不得被前一個 /64 拖累
    finally:
        set_client_ip(None)


def test_稽核的_source_ip_不經分桶收斂():
    """⛔ `DP_AUDIT_LOG.SOURCE_IP` 必須是完整位址——鑑識需要精確來源。

    反向：全庫不得有限流以外的 `ip_bucket` 引用。
    正向錨點：寫入點確實用的是 `get_client_ip`（否則反向斷言可能只是因為整個檔沒了）。

    🔴 **掃整棵 `backend/`，不是只掃 `app/dp/audit/`。** 不變量是「寫進 SOURCE_IP 的是完整
    位址」，而 `get_client_ip()` 的呼叫點散在近 30 個模組。最便宜也最致命的回歸是一行：有人
    為了「統一」把收斂搬到上游，此時全站稽核一起降解成 /64，而只掃 audit 目錄的斷言**仍然
    全綠**。

    ⚠️ **`main.py` 不在 `app/` 底下**（它在 `backend/` 根），而 `set_client_ip(...)` 正是最可能
    被動手腳的地方之一——只掃 `app/` 會漏掉它。本測試改掃 `backend/` 全部 `.py`。

    ⛔ **這條守不住的形狀**：有人**不引用 `ip_bucket`、直接就地重寫**收斂邏輯（例如在
    `get_client_ip()` 裡自己算前綴）。字串比對本質上抓不到那個，只能靠 review。寫在這裡是
    為了讓下一個人知道本測試的界線在哪，不要以為它保證了比實際更多的東西。
    """
    backend_dir = Path(__file__).resolve().parents[2]
    referrers = {
        p.relative_to(backend_dir).as_posix()
        for p in backend_dir.rglob("*.py")
        if "tests" not in p.relative_to(backend_dir).parts and "ip_bucket" in p.read_text(encoding="utf-8")
    }
    assert referrers == {"app/core/rate_limit.py"}, f"ip_bucket 外洩到限流以外：{referrers}"

    # 正向錨點：寫入點確實存在且取的是完整 client IP（否則反向斷言可能只是因為檔案沒了）。
    query_service = (backend_dir / "app" / "dp" / "audit" / "query_service.py").read_text(encoding="utf-8")
    assert "source_ip=get_client_ip()" in query_service, "稽核寫入點應取完整 client IP"


def test_counter_觸頂的_log_說明是照常放行():
    """fail-open 的後果是「該 key 的上限失效」，訊息必須這樣寫。"""
    counter = SlidingWindowCounter(window_seconds=60, max_keys=1)
    counter.try_record("a", now=100.0)
    with patch.object(rate_limit_module.logger, "warning") as warn:
        assert counter.try_record("b", now=100.0) is False
    assert warn.call_count == 1
    msg = warn.call_args.args[0]
    assert "放行" in msg and "失效" in msg, f"fail-open 的訊息寫錯方向：{msg}"


def test_limiter_觸頂的_log_說明是一律拒絕():
    """🔴 與上一條**相反**：limiter 觸頂是 fail-closed，後果是過度阻擋而非保護失效。

    兩者共用同一個 `SlidingWindowCounter`，訊息若只寫 fail-open 的語意，排查的人會去找
    「為什麼沒擋住」，而真實症狀是「擋太多」——方向完全相反。
    """
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60, max_keys=1)
    limiter.hit("a", now=100.0)
    with patch.object(rate_limit_module.logger, "warning") as warn:
        with pytest.raises(AppError) as exc:
            limiter.hit("b", now=100.0)
    assert exc.value.status_code == 429
    assert warn.call_count == 1
    msg = warn.call_args.args[0]
    assert "拒絕" in msg, f"fail-closed 的訊息寫錯方向：{msg}"
    assert "放行" not in msg, "limiter 觸頂不會放行"


def test_觸頂的_log_不得帶出_key():
    """key 可能含帳號 / Email（`login:acct:a@b.c`），不得寫進 log。"""
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=60, max_keys=1)
    limiter.hit("login:acct:someone@example.com", now=100.0)
    with patch.object(rate_limit_module.logger, "warning") as warn:
        with pytest.raises(AppError):
            limiter.hit("login:acct:victim@example.com", now=100.0)
    rendered = str(warn.call_args)
    assert "example.com" not in rendered, "log 不得帶出使用者可控的 key"


def test_zone_id_不造成分桶分裂():
    """🔴 `fe80::1%eth0` 與 `fe80::%eth0` 若不清 scope 會落入**兩個**桶。

    成因：`strict=False` 只在 host bits ≠ 0 時重建位址（順便丟掉 scope），全 0 時沿用
    原物件，於是 scope 原樣留在 network 字串裡。同一條鏈兩個桶。
    """
    assert ip_bucket("fe80::1%eth0") == ip_bucket("fe80::%eth0") == "fe80::/64"
    assert ip_bucket("fe80::1%eth0") == ip_bucket("fe80::1%1"), "zone 值不同不得分裂"
